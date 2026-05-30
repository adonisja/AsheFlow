## 2026-05-24 — Tier 1 Tote Verification: DBSCAN, Alpha Shapes, and Geographic Clustering

### The problem: a tote has no location of its own

A tote is a container. Only the packages inside it have coordinates (lat/lng). To verify a tote belongs on a given truck, you have to derive a geographic representation from its packages. This introduces two sub-problems: how do you represent the tote's location, and how do you define the truck's zone to check against?

### Truck zones are computed daily, not stored as fixed polygons

The packages assigned to a truck each day define its actual delivery area. Using a fixed polygon stored from a previous day is inaccurate — volume and distribution change daily. Instead, we cluster that day's packages to derive zones dynamically.

### Why DBSCAN, not K-means

K-means partitions every point into a cluster — there is no concept of an outlier. If a misaligned package exists, K-means absorbs it into the nearest cluster, distorting the zone boundary. You can no longer detect it as misaligned because the zone was stretched to include it.

DBSCAN (Density-Based Spatial Clustering of Applications with Noise) works differently:
- It finds dense regions of points and labels them as clusters
- Points that don't fit any dense region are labeled **noise** (outliers)
- You draw zone polygons only around the clusters
- The outlier set is your candidate misaligned packages — identified before the polygon is ever drawn

This eliminates the circular dependency: you can't detect outliers after using them to define the boundary, but DBSCAN separates the two in a single pass.

**Two parameters control what "dense" means:**

| Parameter | What it controls | Default |
|---|---|---|
| `eps` | Radius in degrees within which neighbors are searched | `0.015` |
| `min_samples` | Minimum points within `eps` to form a core point | `30` |

`eps = 0.015` was calibrated against real zone data: Truck 2 (8th–11th Ave, W36–W42 St) spans ~0.018° lat × 0.012° lng. An eps of 0.008 fragmented that single legitimate zone into multiple clusters. 0.015 connects packages across the full zone width.

`min_samples = 30` sits above the maximum tote size (22 packages) — a single stray tote can never accidentally form its own cluster.

### Convex hull vs concave hull — which shape do you draw around a cluster?

Once DBSCAN identifies a cluster, you need to draw a polygon around it.

**Convex hull** — imagine stretching a rubber band around all the points and letting go. It snaps to the outermost points and forms a shape that is always "puffed out" — it never curves inward. For an L-shaped or irregular delivery zone, the hull fills in the corner gap with area the truck doesn't actually cover. Neighboring truck zones can bleed in, causing false passes.

**Concave hull (alpha shapes)** — instead of a rubber band, imagine carefully tracing around the points with a pencil, following the actual shape of the cluster, curving inward where there are gaps. The result hugs the real delivery area much more closely — 10–30% less wasted coverage for irregular urban zones.

The trade-off: concave hull can produce invalid polygons (self-intersecting lines) on sparse or irregular point sets. The solution is to validate the output and fall back to convex hull when it fails.

```
Primary path:   alphashape with optimizealpha() → validate → buffer(0) self-heal if needed
Fallback path:  convex hull if concave still invalid after self-heal
```

### Tote location: centroid + standard deviation

Rather than running point_in_polygon on every package in every tote (expensive), a two-stage approach is used:

**Stage 1 — Bounding box pre-filter:**
Compute the tote's centroid (mean lat/lng of all packages). Check if it falls within the bounding box of any of the truck's zones. If yes, the tote is likely fine. If no, proceed to Stage 2.

**Stage 2 — Standard deviation check:**
Compute σ_lat and σ_lng across all packages. If σ exceeds 30% of the polygon's own lat/lng span, the tote is geographically scattered — the centroid is not a trustworthy representative. Escalate to full point_in_polygon per package.

**Why standard deviation, not raw spread:** σ captures the distribution of packages around the centroid, not just the extremes. A tote with one outlier far away has high σ. A tote uniformly spread across a zone has proportionally lower σ. This correctly identifies which totes need the expensive full check.

### Tote classification thresholds

After checking individual packages, each tote is classified:

**Small tote (< 10 packages) — count-based:**
Percentages are too sensitive at small sizes. 1 package out of 3 is 33% — that would over-classify as uncertain when it's just one package to pull.

| Strays | Classification |
|---|---|
| 0 | Clean |
| 1 | Stray — pull individually |
| 2–3 | Uncertain — dispatch review |
| 4+ | Misaligned — move whole tote |

**Standard tote (≥ 10 packages) — percentage-based:**

| % outside | Classification |
|---|---|
| 0% | Clean |
| 1–10% | Stray — pull individually |
| 11–40% | Uncertain — dispatch review |
| >40% | Misaligned — move whole tote |

The 10% stray boundary aligns with Six Sigma lean logistics baseline for incidental errors (<5% is ideal; 10% gives a practical working buffer).

### The multi-zone false positive problem

A truck can have multiple zones (multiple anchor points). A package that fails Zone A may pass Zone B — it belongs on this truck, just at a different anchor. Without this check, every such package would be a false positive misroute.

**Resolution order:**
1. Fails assigned zone → check all other zones on the same truck first
2. Passes any same-truck zone → not a misroute, belongs here at a different anchor
3. Fails all same-truck zones → search all other trucks' zones
4. Matches another truck → misrouted, correct truck identified
5. Matches nothing → unresolvable, manual dispatch review

---

## 2026-05-24 Alembic Migrations: `default` vs `server_default` and Type Delivery

### The difference between `default` and `server_default`

Both set a column's default value, but they operate at different layers:

| | `default` | `server_default` |
|---|---|---|
| Where it runs | Python / ORM layer | Database layer |
| When it fires | Before the INSERT is sent | At INSERT time inside PostgreSQL |
| Bypassed by raw SQL? | Yes — raw SQL skips the ORM | No — database always applies it |
| Type | Python value (True, 0, uuid4) | String of raw SQL or `sa.text()` |

```python
# Python-side — ORM sets this before sending INSERT
is_active = Column(Boolean, default=True)

# Database-side — PostgreSQL sets this at INSERT time
is_active = Column(Boolean, server_default="true")
```

`server_default` is preferred for production columns because:
- It applies even when rows are inserted via raw SQL (migrations, scripts, manual fixes)
- The database is the single source of truth — no dependency on the ORM being used
- Consistent with how `created_at` timestamps work across the codebase

### Why `server_default` takes a string, not a Python value

`server_default` is a **raw SQL fragment** pasted directly into the `CREATE TABLE` statement. SQLAlchemy needs it as a string because it doesn't know how to serialize arbitrary Python values into SQL syntax.

When you write:
```python
server_default="true"
```

PostgreSQL receives:
```sql
is_active BOOLEAN DEFAULT true
```

`true` there is a PostgreSQL boolean literal — not a Python string. The string in your migration file is just the delivery mechanism. The column stores and returns real booleans.

If you passed `server_default=True` (Python bool), SQLAlchemy would raise an error — it can't serialize a Python bool into a SQL fragment automatically.

**Common `server_default` values by type:**

| Column type | server_default value |
|---|---|
| Boolean | `"true"` or `"false"` |
| Integer | `"0"` or `"1"` |
| Timestamp | `sa.func.now()` |
| Text/String | `"'pending'"` (note the inner quotes — it's SQL string syntax) |
| Array | `"{}"` |

### Alembic migration file structure

Every migration file follows this pattern:

```python
"""short description of what this migration does

Revision ID: abc123
Revises: xyz789
Create Date: 2026-05-24
"""
import uuid
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB  # import dialect types you need

revision = 'abc123'
down_revision = 'xyz789'   # the migration this builds on top of
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "table_name",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("fk_col", UUID(as_uuid=True), sa.ForeignKey("other_table.id", ondelete="CASCADE"), nullable=False),
        # ForeignKey is a separate argument to sa.Column(), NOT nested inside UUID()
    )
    op.create_index("ix_table_name_col", "table_name", ["col"])


def downgrade() -> None:
    op.drop_table("table_name")  # reverse order if multiple tables
```

**Key syntax rules:**
- `ForeignKey` is an argument to `sa.Column()`, not nested inside the type: `sa.Column("x", UUID(as_uuid=True), sa.ForeignKey(...))`  not `sa.Column("x", UUID(as_uuid=True, sa.ForeignKey(...)))`
- Index naming convention: `ix_<table_name>_<column_name>`
- `downgrade()` drops tables in reverse creation order (child tables before parent tables)
- `ondelete="CASCADE"` vs `ondelete="SET NULL"` — CASCADE deletes children when parent is deleted; SET NULL nullifies the FK instead (requires `nullable=True` on the column)

---

## 2026-05-19 Geographic Data: Coordinates and Point-in-Polygon

### Coordinates

Every point on Earth is identified by two numbers:

- **Latitude** — how far north or south you are. Measured in degrees from the equator (0°). Increases as you go north. New York is ~40.7° N. Walking uptown = latitude increases.
- **Longitude** — how far east or west you are. Measured in degrees from the prime meridian (runs through London). West of London is negative. New York is ~-74°. Walking east = longitude becomes less negative.

A delivery stop becomes a coordinate pair:
```
(40.758, -73.997)  ← approximately 42nd St & 9th Ave, Manhattan
```

In Manhattan's grid: latitude tracks north-south (streets), longitude tracks east-west (avenues).

### Polygons

A geographic zone boundary is stored as a **polygon** — an ordered list of corner points connected by straight lines. The last point connects back to the first to close the shape.

```python
truck_zone = [
    {"lat": 40.771, "lng": -74.002},  # top-left
    {"lat": 40.771, "lng": -73.993},  # top-right
    {"lat": 40.746, "lng": -73.993},  # bottom-right
    {"lat": 40.746, "lng": -74.002},  # bottom-left
]
```

More vertices = more precise boundary. A simple rectangle needs 4 points. An irregular urban zone may need 12–20.

Stored in PostgreSQL as **JSONB** (list of `{lat, lng}` dicts). No geometry extension needed for the ray casting approach.

### Point-in-Polygon: Ray Casting Algorithm

**The question:** is a delivery coordinate inside a truck's zone polygon?

**The algorithm:**
1. Draw an imaginary ray from the point going east (increasing longitude)
2. Count how many polygon edges that ray crosses
3. **Odd crossings = inside. Even crossings = outside.**

**Why it works:** any straight line starting inside a closed shape must cross the boundary an odd number of times to exit. Starting outside, you cross in and back out — always even.

**Visual examples:**

```
Inside (1 crossing):
    ___________
   |           |
   |  • ——————————>
   |___________|
                ↑ 1 crossing = odd = INSIDE

Outside (2 crossings):
    ___________
   |           |
• ———————————————————>
   |___________|
    ↑         ↑
  enter      exit   = 2 crossings = even = OUTSIDE

Outside (0 crossings):
    ___________
   |           |
   |___________|

• ————————————————>   (ray misses entirely)
                    = 0 crossings = even = OUTSIDE
```

### The Implementation

```python
def point_in_polygon(lat: float, lng: float, polygon: list[dict]) -> bool:
    n = len(polygon)
    crossings = 0
    for i in range(n):
        current_point = polygon[i]
        next_point = polygon[(i + 1) % n]      # % n wraps last → first
        # Does this edge straddle our latitude?
        if (current_point["lat"] > lat) != (next_point["lat"] > lat):
            # Find the longitude where this edge crosses our latitude
            cross_lng = (
                current_point["lng"]
                + (lat - current_point["lat"])
                / (next_point["lat"] - current_point["lat"])
                * (next_point["lng"] - current_point["lng"])
            )
            if cross_lng > lng:     # crossing is to the east = counts
                crossings += 1
    return crossings % 2 == 1
```

**Key details:**

- `(i + 1) % n` — modulo wraps the last index back to 0, closing the polygon automatically
- `(current["lat"] > lat) != (next["lat"] > lat)` — True only when one endpoint is above our latitude and the other is below (straddles it). If both above or both below, the ray can't cross this edge.
- `cross_lng` formula — linear interpolation: finds how far along the edge (as a 0–1 fraction) our latitude sits, then scales that to find the corresponding longitude
- `cross_lng > lng` — only count the crossing if it's east of (to the right of) our point

### How It's Used in AsheFlow (Tier 1 Verification)

Every tote has a destination coordinate from the Cortex manifest. Every truck has a zone polygon stored in `TruckZone.polygon` (JSONB). Tier 1 verification runs `point_in_polygon` for each tote against its assigned truck's zone. If the tote's destination falls outside that zone, it's a Tier 1 misroute — flagged before the trucks leave the station.

### Three-Level Geographic Hierarchy

```
DSP Zone (company-wide)
  └── Truck Zones  — semi-fixed polygons, defined by management via map drawing UI
        └── Walker Clusters — fully dynamic, recomputed daily from today's package coordinates
```

- **DSP Zone** — derived as union of all truck zones, not stored separately
- **Truck Zones** — stored in `TruckZone` table as JSONB polygon; drawn in UI using Leaflet map library
- **Walker Clusters** — ephemeral; computed at sort time from coordinates, never persisted

### Overlap and Gaps

Real-world truck zones often overlap or have gaps between them. A point in an overlap zone could legitimately belong to either truck — Tier 1 verification surfaces it for dispatch to resolve. A point in a gap belongs to no truck — flagged as a data quality issue.

---

## 2026-05-08 Multi-Tenant: Super Admin Dependency Pattern

When a platform-level identity needs API access but has no row in the `employees` table, do not force one. Create a separate dependency that stops at the JWT:

```python
def get_super_admin(current_user: dict = Depends(get_current_user)) -> dict:
    if "super_admin" not in current_user.get("cognito_groups", []):
        raise HTTPException(status_code=403, detail="Super admin access required.")
    return current_user
```

Never use `get_caller_employee` on super admin endpoints — it raises 403 for any caller without an Employee row. Never use `get_super_admin` on company-scoped endpoints — it returns no `company_id`. The two dependencies are mutually exclusive by design.

## 2026-05-08 Multi-Tenant: Atomic Company + Config Provisioning

When creating a parent row and a dependent row in one request, use `db.flush()` between them to populate the parent's UUID before the FK reference:

```python
company = Company(name=..., slug=...)
db.add(company)
db.flush()                          # company.id is now set
db.add(CompanyConfig(company_id=company.id))
db.commit()
```

Without `flush()`, `company.id` is still `None` when `CompanyConfig` is constructed, and the FK will be null or fail depending on the DB.

Always create the config row at provisioning time, not lazily. Services that read config assume the row exists — making it optional forces every service to handle the "config missing" case.

## 2026-05-08 Multi-Tenant: Idempotent Bootstrap Pattern

Bootstrap endpoints (provisioning the first resource of a kind) should be safe to call multiple times. The pattern:

1. Look up the target by a natural key (email, slug, etc.)
2. If it exists and is already in the terminal state (e.g. `active`), return 409
3. If it exists but is not yet terminal, skip creation and fall through to re-issue the token/credential
4. If it doesn't exist, create it

```python
employee = db.query(Employee).filter(...email == payload.email).first()
if employee:
    if employee.account_status == "active":
        raise HTTPException(409, "Already active.")
    # else: re-issue invite below
else:
    employee = Employee(...); db.add(employee); db.flush()

# always re-issue token
db.query(InviteToken).filter(...employee_id == employee.id).delete()
db.add(InviteToken(...))
```

Return a `sent: bool` field when the endpoint fires a side-effect (email, SMS). The operation should commit even if the side-effect fails — the caller can retry the endpoint to re-fire it.

## 2026-05-08 Multi-Tenant: Scoping Indirect Models via Join

When a model doesn't carry `company_id` directly (e.g. `AssignmentChangeRequest` references `employee_id`, not `company_id`), scope it by joining through the model that does:

```python
db.query(AssignmentChangeRequest)
    .join(Employee, AssignmentChangeRequest.employee_id == Employee.id)
    .filter(
        AssignmentChangeRequest.id == request_id,
        Employee.company_id == caller.company_id,
    )
```

This is both a data-isolation guard and an ownership check — the record only exists in the result set if it belongs to the caller's company. A separate `if record.company != caller.company_id: raise 403` check is unnecessary when the join already enforces it.

## 2026-05-08 Multi-Tenant: Three Write-Path Checklist

Every endpoint that writes data needs three `company_id` stamps:

1. **New model row** — `company_id=caller.company_id`
2. **Notification rows** — `Notification(company_id=caller.company_id, ...)`
3. **Audit call** — `write_audit(db, actor_id=str(caller.id), company_id=str(caller.company_id), ...)`

Notification fanout queries must also be scoped: `Employee.company_id == caller.company_id` before `Employee.role.in_(["dispatch", "admin"])`. Without it, dispatchers from every tenant get notified for every company's events.

## 2026-05-08 Multi-Tenant: Helper Functions Need company_id Threaded Through

When a router delegates to helper functions (e.g. `_get_assignment`, `_crew_employee_ids`, `_notify` in `anchor_points.py`), those helpers must also receive and apply `company_id`. Don't let the helper re-query without it:

```python
# Bad — helper ignores tenant boundary
def _crew_employee_ids(db, truck_id, date):
    return [m.employee_id for m in db.query(AssignmentMember).join(...).filter(...).all()]

# Good — company_id threaded through
def _crew_employee_ids(db, truck_id, date, company_id):
    return [m.employee_id for m in
        db.query(AssignmentMember)
            .join(TruckAssignment, ...)
            .filter(TruckAssignment.company_id == company_id, ...)
            .all()
    ]
```

## 2026-05-08 Multi-Tenant: Direct Router Function Tests Need a Caller Object

Tests that call router functions directly (bypassing the HTTP test client) must pass a real `caller` employee when the function signature requires one. The `Depends(get_caller_employee)` dependency is not resolved when calling outside FastAPI — passing nothing leaves the parameter as a `Depends` object, which crashes on `.company_id`.

Pattern:
```python
def make_admin_caller(db) -> Employee:
    emp = Employee(id=uuid.uuid4(), company_id=SEED_COMPANY_ID, role="admin", ...)
    db.add(emp); db.commit(); db.refresh(emp)
    return emp

# In test
result = get_dispatch_fill_rate(start_date=..., end_date=..., db=db, caller=make_admin_caller(db), _={})
```

## 2026-05-08 Registration: Cognito AdminCreateUser Without TemporaryPassword

Calling `AdminCreateUser` without a `TemporaryPassword` field makes Cognito auto-generate the password and email it to the user's `email` attribute. The user is placed in `FORCE_CHANGE_PASSWORD` status and must reset on first login.

This is preferable to the `AdminCreateUser` + `AdminSetUserPassword(Permanent=True)` pattern when:
- You want the employee to set their own password (not have one chosen for them or by the backend)
- You want Cognito to handle credential delivery — one less SES call, and Cognito's email is transactional by nature

Tradeoff: you don't control the credential email format. Send your own branded welcome email alongside it for context.

## 2026-05-08 Registration: Server-Side Username Derivation

Let the server derive `firstname.lastname` rather than asking the user to choose:

```python
def _derive_username(name: str, db: Session) -> str:
    parts = name.strip().lower().split()
    first = re.sub(r"[^a-z0-9]", "", parts[0])
    last  = re.sub(r"[^a-z0-9]", "", parts[-1]) if len(parts) > 1 else ""
    base  = f"{first}.{last}" if last else first
    candidate = base
    suffix = 2
    while db.query(Employee).filter(Employee.username == candidate).first():
        candidate = f"{base}{suffix}"
        suffix += 1
    return candidate
```

The loop is safe because usernames are unique in the DB and the suffix increments — it can't loop forever unless there are thousands of employees with identical names.

## 2026-05-08 Backend: Role-Scoped Access Guards

When an endpoint should be accessible to multiple roles but must restrict which *targets* they can act on, use a helper guard rather than duplicating the check:

```python
PROTECTED_ROLES = {"management", "admin"}

def _assert_not_protected(caller_groups: set, target_role: str) -> None:
    if target_role in PROTECTED_ROLES and "admin" not in caller_groups:
        raise HTTPException(status_code=403, detail="Only admins can modify management or admin accounts.")
```

Call it immediately after the 404 check, before any mutation. For list endpoints use a DB-level filter (`.notin_()`) rather than filtering in Python — it scales and doesn't leak row count through pagination.

Apply the same split in the frontend: silently hide rows the caller can't act on, and remove disallowed options from forms. The UI guard is UX; the API guard is security.

## 2026-05-08 Multi-Tenant: PATCH Semantics with `exclude_unset=True`

Config PATCH endpoints should only write the fields the caller explicitly provided. Use Pydantic's `model_dump(exclude_unset=True)` to get only the submitted fields:

```python
def _apply_config_update(config: CompanyConfig, payload: CompanyConfigUpdate) -> None:
    data = payload.model_dump(exclude_unset=True)   # only fields in the request body
    for field, value in data.items():
        setattr(config, field, value)
```

If you use `model_dump()` without `exclude_unset=True`, every optional field that the caller didn't send becomes `None` and overwrites existing values with null — effectively a DELETE masquerading as a PATCH.

This matters most for partial updates to rows with many optional fields (config, preferences, profile) where callers routinely only update 1–2 fields at a time.

## 2026-05-08 Multi-Tenant: Field-Level Authorization in Config Endpoints

When some fields in a shared schema should only be editable by a privileged role, enforce it at the application layer inside the helper that does the write — not by creating a separate schema:

```python
_SUPER_ADMIN_ONLY_FIELDS = frozenset({"invite_expiry_days"})

def _apply_config_update(config, payload, allow_super_admin_fields=False):
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        if field in _SUPER_ADMIN_ONLY_FIELDS and not allow_super_admin_fields:
            raise HTTPException(403, f"'{field}' can only be changed by a super admin.")
        setattr(config, field, value)
```

Both endpoints call the same helper with different `allow_super_admin_fields`:
- Super admin endpoint: `_apply_config_update(config, payload, allow_super_admin_fields=True)`
- Company admin endpoint: `_apply_config_update(config, payload, allow_super_admin_fields=False)`

Don't hide the field entirely from the schema — company admins can still read it in the response. The lock is write-only.

## 2026-05-08 Multi-Tenant: Two Routers in One File

When a module has two distinct access paths (e.g. `/admin/companies/...` for super admin and `/companies/...` for company admin), put them in the same file as two `APIRouter` instances and register both in `main.py`:

```python
# companies.py
router = APIRouter(prefix="/admin/companies", tags=["companies"])
company_admin_router = APIRouter(prefix="/companies", tags=["company-config"])

# main.py
api_v1_router.include_router(companies.router)
api_v1_router.include_router(companies.company_admin_router)
```

This keeps related logic co-located while maintaining clean URL namespaces. The alternative — splitting into two files — creates a dependency cycle if the files need to share schemas or helpers.

## 2026-05-08 Frontend: Time Fields as Text Inputs

SQLAlchemy `Time` columns serialize to Python `datetime.time`, which JSON doesn't handle natively. The cleanest API contract is `"HH:MM"` strings both ways — input and output.

On the frontend, use `type="text"` with an `HH:MM` placeholder rather than `type="time"`. Browser `type="time"` inputs have inconsistent locale formatting (some show 12-hour, some 24-hour) and are visually inconsistent across OS and browser. A plain text input with format documentation is clearer for non-technical users.

Backend validation: split on `:` and construct `datetime.time(int(h), int(m))`. Raise a clear `ValueError` on bad format. The Pydantic `field_validator` converts on input; `from_orm_obj` converts on output.

## 2026-05-08 Backend: Promote/Demote as POST Endpoints

Role transitions with side effects (Cognito group sync, notification creation) belong on dedicated `POST /{id}/promote` and `POST /{id}/demote` endpoints, not on the general `PUT /{id}` update endpoint. Reasons:

- `PUT` is for field updates; a role transition is a state machine event with invariants (walker→trainer only, trainer→walker only)
- Side effects (Cognito call, notification) need to be clearly scoped — wrapping them in a generic update path makes them easy to miss or accidentally bypass
- Validation is simpler: check `current_role == expected` and raise 400 early; no need to diff old vs new role inside a general update handler

Cognito group sync is best-effort inside try/except — log the failure but don't roll back the DB change, since the DB is authoritative and groups are refreshed on next token issue.

## 2026-05-08 UI: Inline Feedback Pattern for One-Off Row Actions

For actions that affect a single table row (resend invite, resend verification,
etc.) where a modal would be overkill, use inline per-row feedback instead:

```tsx
const [resendingId, setResendingId] = useState<string | null>(null);
const [resendMsg,   setResendMsg]   = useState<{ id: string; ok: boolean; text: string } | null>(null);
```

- `resendingId` gates the spinner and `disabled` state on the exact row being acted on
- `resendMsg` is keyed by row ID so only that row shows the result
- Clear `resendMsg` at the start of the next action so stale feedback doesn't persist

## 2026-05-08 Registration: Alembic Autogenerate Drift

`alembic revision --autogenerate` compares the ORM models against the live DB
schema. If the live DB has constraints or columns that are no longer in the ORM
(e.g. FKs from a previous migration that was written by hand with different
naming), autogenerate will include `op.drop_constraint` / `op.drop_column` calls
for all of them — not just the table you're adding.

**Rule:** After running `--autogenerate`, always inspect the output and trim
everything outside the feature you're adding. Only commit the minimal diff. The
extra `drop_*` operations are not harmless — they can destroy constraints that
are still in use.

## 2026-05-08 Registration: AdminCreateUser + AdminSetUserPassword Pattern

To create a Cognito user with a permanent password (no force-change challenge on
first login):
1. Call `AdminCreateUser` with `MessageAction="SUPPRESS"` — this creates the user
   without sending a Cognito system email and without triggering a temp-password
   requirement.
2. Immediately call `AdminSetUserPassword` with `Permanent=True` — this promotes
   the password from temporary to permanent so the user can sign in without a
   challenge.

If step 2 fails, delete the Cognito user created in step 1 before re-raising,
otherwise the username is permanently blocked (Cognito `UsernameExistsException`
on retry).

## 2026-05-07 Multi-Tenant: Config NULL Fallback Pattern

When migrating from a hardcoded-constant system to per-company config, make all
config columns nullable and resolve values in order: `company_configs` row →
hardcoded constant. This lets the migration happen incrementally — existing
behavior is unchanged until a company admin explicitly sets a value. Never
delete the hardcoded constants until every company has a real config row.

**Rule:** Before touching a service that reads a constant (e.g. `GRADUATION_ASSIGNMENTS = 5`),
ensure the calling code resolves `company_config.graduation_assignments or GRADUATION_ASSIGNMENTS`.
Only then remove the constant.

---

## 2026-05-05 React Native: "Should Have a Queue" Is Not Always a Conditional Hook

The error "Should have a queue. You are likely calling Hooks conditionally" is React's generic "hook count changed between renders" panic. It does not always mean a conditional `useState`/`useEffect` call. Any synchronous `throw` that interrupts the hooks sequence mid-component produces the same message — even if every hook call is unconditional.

**Root cause pattern:** A hook helper (`useAuth`) called `throw new Error(...)` when its context was null. One hook (`useColorScheme`) had already run before the throw. On the next render, React counted one fewer hook and panicked with the queue error instead of the actual missing-provider message.

**Fix:** Never throw synchronously from a hook that is called during render. Return a safe fallback value instead. If the caller must know that the context is absent, return `null` or a typed sentinel — don't throw. Reserve throws for imperative call sites (event handlers, async functions) where the hooks queue is not active.

**Rule:** When you see "Should have a queue," first check whether any hook-like helper throws rather than looking for misplaced `if` statements around `useState`.

---

## 2026-05-04 Mobile: Stack Screens Are Dead Without a Navigate Call

Registering a screen in a `createNativeStackNavigator` does not make it reachable. If no code ever calls `navigation.navigate('ScreenName')`, the screen simply never appears — no error, no warning, just a silent dead end. This happened to `TrainerHistory`, `TrainerPerformance`, `Phase4`, and `TraineeHistory`, all of which were registered but orphaned.

**Fix:** when a feature has multiple sub-views (Today / History / Performance), own the tab bar in a wrapper component (`TrainerDashboard`) that renders the sub-screens directly. The navigator registers one screen; navigation is handled by `useState` inside the wrapper. This mirrors how the web works (tabs inside a page, not separate routes).

**Rule:** After adding a screen to a navigator, immediately verify there is a code path that reaches it. If there isn't one, the screen doesn't exist from the user's perspective.

---

## 2026-05-04 Mobile: `id_token` vs `access_token` in Cognito

Cognito issues two tokens after sign-in. The access token authorizes API calls but carries no user attributes — no `cognito:groups`, no `email`. The id_token carries all of that. If the backend reads `cognito:groups` from the JWT (as the `RoleChecker` dependency does), the Bearer token must be the id_token. Sending the access token causes silent 403s on every role-gated route — the API returns 403 but no network error, so screens just render empty.

**Rule:** Store and send the id_token for any backend that reads group membership or user attributes from the JWT payload.

---

## 2026-05-04 Mobile: UTC Date Bug in US Timezones

`new Date().toISOString().split('T')[0]` returns the UTC date. In US Eastern time at midnight to ~8am, that's yesterday's date. Any schedule or dispatch query using this will silently return the wrong day's data. Always derive local date with `getFullYear()` / `getMonth()` / `getDate()`.

---

## 2026-05-04 Mobile: Task List UX — Group, Not Card-Per-Row

Rendering each task as its own bordered card creates visual noise and wastes vertical space. The correct pattern (Things 3, iOS Settings, Linear): all tasks in a group share one rounded container (`overflow: hidden`), rows are separated by inset dividers only (no border on the last row). Description text is hidden by default and expands on row tap — the checkbox is an independent touch target with `hitSlop` so it doesn't conflict with the expand gesture.

---

## 2026-05-04 Backend: Excess-Trainer Walker Re-Slotting Corrupts Assignment Roles

The dispatch engine capped excess trainers by extending the walker pool with them. Because `assign_walkers` hardcodes `role="walker"` for every employee it receives, those trainers ended up in `assignment_members` with the wrong role. The corruption was silent — no guard compared `AssignmentMember.role` against `Employee.role`.

**Root cause pattern:** passing an employee ORM object to a pool that stamps a fixed role. Any future "spill-over" design must carry the original role through, not borrow the destination pool's role.

**Fix:** Remove the cap entirely. `assign_trainers` already does pure round-robin distribution with no ceiling — the cap was the only thing blocking it. With the cap gone, all available trainers distribute evenly across trucks (e.g. 12 trainers / 5 trucks → 2-2-2-3-3). "Excess trainers" is not a real concept when distribution is dynamic. Add a role-integrity guard at write time that auto-corrects any trainer assigned a non-trainer role and appends a `role_integrity_violation` warning.

**Takeaway:** When writing an employee into a pool, the pool must not overwrite their canonical role. Either the role travels with the member dict, or a guard verifies it before the DB write. Never let the slot type determine the stored role. And before adding a warning/fallback for an edge case, ask whether the algorithm already handles it — the cap created the "excess" problem that didn't need to exist.

---

## 2026-05-02 Dashboard Audit: Always Verify the Data Source Before Trusting a KPI

This section was written after auditing all dashboard views post-shift-lifecycle backend (ADR-055).

---

### A metric that reads from the wrong table is worse than no metric

`Fleet Today` in both DispatchView and ManagementView read from `Departure` rows. The intent was "how many trucks are out." The problem: `Departure` rows don't exist until drivers actually depart. At 6am the metric showed `0/0` — not "no data," but a confident wrong answer that looks like dispatch hasn't run yet.

The fix was to read from `TruckAssignment.status`, which is written the moment dispatch runs. All trucks start as `planned`. That's the correct baseline.

**Rule:** Before wiring a KPI, trace the full write path: *when is the first row written? What does zero mean?* A metric that's empty before noon every day isn't measuring anything useful.

---

### When a new column changes what a summary query means, update the UI to match

Adding `inspection_type` to `VehicleInspection` changed the meaning of the inspections summary — rows that previously represented "one inspection per driver" now represent "one inspection per driver per type." The management table was titled "Pre-Trip Inspections" and had no type column, so EOD inspections silently appeared as if they were pre-trip.

**Rule:** Whenever a unique constraint changes, grep for every UI that renders the affected table and check whether the display still makes sense. The constraint change is the signal; the UI audit is the required follow-up.

---

### Summary endpoints return different shapes — read them before wiring the frontend

The station handoffs summary returns `{ date, total_totes_returned, total_rts_returned, drivers: [...] }`, not a flat list. The check-ins summary returns a flat list but uses `latest_check_in`, not `check_in_count`. Both would have caused silent bugs (rendering nothing or crashing) if the frontend had assumed a flat list.

**Rule:** Before wiring any summary endpoint to the UI, read the actual backend implementation or run `curl` against it. Don't guess the shape from the field names.

---

## 2026-05-02 Shift Lifecycle Data Model

This section was written after implementing the full daily shift lifecycle (ADR-053, ADR-054).

---

### Always clarify the real-world flow before modeling it

The first attempt at the return-leg model (`RTSClearance`) conflated two physically distinct events into one table because the description "driver submits RTS before returning" sounded like a single action. It wasn't — it's a field gate (dispatch approval required) followed by a separate physical handoff at the station.

**Rule:** Before writing a model, ask "who does this, where, and what happens next?" If the answer changes mid-description, you have two models, not one. The split between `RTSReport` and `StationHandoff` came directly from that question.

---

### Wiring a field that already exists is not the same as adding it

`TruckAssignment.status` had a `planned | active | completed` constraint from the beginning but was never written. The management dashboard was reading it and always showing 0 active trucks — a silent wrong answer. When a column exists but has no write path, it's actively misleading.

**Rule:** After adding a column, immediately ask "what writes this?" If the answer is "nothing yet," either remove the column or wire the writes in the same PR. Never leave a column that exists but is never updated.

---

### Unique constraints determine what "one record per X" means — get it right up front

`VehicleInspection` had `UniqueConstraint("driver_id", "date")`, which sounded right for "one inspection per driver per day." But the shift has two inspections: pre-trip and EOD. The constraint had to be relaxed to `(driver_id, date, inspection_type)`.

**Rule:** When defining a unique constraint, explicitly list all the cases that need to coexist. "One per driver per day" is usually incomplete — ask "one *what* per driver per day?"

---

### Denormalize counts when they're the primary query target

`RTSReport.total_rts` is a sum of `rts_packages[].count`. Storing it redundantly as an integer avoids a JSONB aggregate on every dispatch queue query. Same pattern used in `PackageManifest` (no aggregation needed for the daily totals endpoint).

**Rule:** If the most common query is "give me the total," store the total. Recompute it at write time, not at read time. Only matters when the source is JSONB or a variable-length list.

---

### Application-layer gates vs DB constraints — know which to use

The `StationHandoff` endpoint enforces that the driver's `RTSReport` must be `approved` before they can submit. This is application-layer logic, not a foreign key or check constraint. That's correct — "approved" is a business state, not a referential integrity rule. A FK to `rts_reports` would only enforce that *a* report exists, not that it's *approved*.

**Rule:** Use DB constraints for structural integrity (the row exists, the value is in range). Use application-layer checks for business state (the row is in the right status). Don't try to encode business workflow rules into the schema.

---

### Log everything before moving on

Documentation was consistently skipped during implementation and had to be written as a separate catch-up step. This creates drift — details are harder to reconstruct and the journal ends up thinner than it should be.

**Rule:** After any session that produces new models, migrations, or endpoint changes: write the journal entry, ADR(s), and LEARNING_GUIDE additions before closing the session or moving to the next feature. The three artifacts take ~15 minutes and save hours of archaeology later.

---

## 2026-04-22 Bot DMs: Trainer-Trainee Pairing Callout and Simulation Reset

This section was written after addressing the trainer-trainee notification gap and the reset_on_graduation flag (ADR-047).

---

### The pairing gap in dispatch DMs

The dispatch bot DMs each employee a crew roster when assignments are published. But the roster is just a list — no explicit callout of who is paired with whom for training purposes. A trainer scanning a 10-person crew roster had to infer their trainee; a trainee had no idea who to approach when they arrived at the truck.

The fix is role-specific pairing blocks appended to the DM description:

- **Trainee DM** shows `🎓 Your trainer today:` with the trainer names. If no trainer is on the truck, it shows a warning so the trainee knows to contact dispatch.
- **Trainer DM** shows `📋 Your trainee(s) today:` with each trainee's name and their current training phase (fetched live from `GET /training/trainee/{id}`).

The phase lookup is non-blocking — if the API call fails, the phase shows as `?` and the DM still sends. The cost is one extra HTTP round-trip per trainer at publish time, acceptable for a typical crew size of 1–3 trainers.

### Why not send the pairing callout post-confirmation?

The alternative is to wait until a trainee confirms, then DM their trainer with the phase info. This avoids wasting API calls on employees who decline, and ensures the trainer only gets the callout for trainees who are actually showing up.

The tradeoff: you need bot-side state to correlate the confirmation event back to the trainer. The current design fires at publish time — simpler, slightly wasteful, but never blocks or loses a notification. Revisit if volume grows.

### reset_on_graduation: cycling simulation accounts without polluting the walker roster

The graduation service unconditionally promotes any trainee with 5+ dispatches to walker. For a simulation account used in integration testing (Timmy Trainee), this is wrong — promotion removes them from the training system permanently.

`reset_on_graduation = True` on an `Employee` tells `graduate_trainees.py` to delete all training records for that trainee instead of promoting them. The next dispatch injection sees no open record and reinjects Phase 1 — the full training cycle restarts cleanly.

**Why hard-delete records instead of a soft-reset field?** `training_injection.py` reads `last_record.current_day_number` to determine next phase. A stale record with `current_day_number = 4` would cause Phase 4 to reinject instead of Phase 1. Hard-deleting is simpler and correct for simulation use.

---

## 2026-04-22 Training System: Phase-Based Gating, Debt Attribution, and Trainer Accountability

This section was written after the training system phase-based redesign (ADR-046).

---

### Why calendar-day gating was wrong for this operation

The original training system incremented `day_number` linearly — Day 1 on Monday, Day 2 on Tuesday. This produced false debt whenever a trainer covered early. If Phase 1 was completed by noon and a trainer previewed Phase 2 topics that afternoon, the system would flag those Phase 2 topics as "debt" on Day 2.

The fix: **phases are curriculum units, not calendar dates.** A phase advances when all mandatory tasks are complete, regardless of the date. The `training_injection.py` service checks `last_record.phase_closed` — not `last_record.record_date + 1`.

This also means missed days are free. If a DA calls out, training simply pauses. No debt, no penalty. The clock only runs on days the DA is physically dispatched.

### Debt attribution: one mark per incident, context only downstream

The instinct when a debt chain persists across multiple trainers is to mark every trainer who failed to close their phase. This is wrong — it penalizes trainers for someone else's failure.

The correct model: one mark goes to the trainer who originated the chain (failed with no inherited debt). Everything downstream is context, not punishment. The `debt_chain_context` field on `TrainerMark` documents the impact; the `debt_originated` flag identifies the root cause. Subsequent trainers who fail to close because of inherited debt receive no mark.

This preserves trainer accountability without creating a perverse incentive: under the wrong model, inheriting debt would always result in a mark regardless of effort.

### Topic-level coverage logging enables handoff tracing

The original design assumed the `trainer_id` on a `TrainingRecord` covered all topics on that record. When a trainer leaves mid-shift and a second trainer picks up, this assumption breaks. You lose the handoff point entirely.

`TrainerCoverage` writes one row per topic per trainer at completion time. The handoff is visible in the log as a timestamp boundary — topics covered before 11 AM by Trainer A, topics covered after 2 PM by Trainer B. End-of-day attribution for mark purposes follows whoever was active last.

### Phase 4 is observation, not instruction

Phase 4 tasks are not seeded statically in `training_curriculums`. They are generated at dispatch time in `training_injection.py` by mirroring all mandatory Phase 1–3 items as `record_type = "demonstration"` tasks. This means the Phase 4 checklist automatically reflects any changes to the Phase 1–3 curriculum — no manual sync required.

On submission, `score_phase4()` computes pass/fail (90% threshold, all mandatory items must individually pass). On fail, `generate_remediation_record()` creates a Phase 5 record containing only the failed topics — targeted remediation, not a full restart.

---

## 2026-04-18 Bulk Operations: Parse Client-Side, Validate Before Sending, Report Per-Row

This section was written after building the bulk employee import flow.

---

### Parse files in the browser, not on the server

A common instinct is to send the raw file to the server and parse it there. This adds multipart upload handling, a file parsing dependency in the backend, and a new failure mode (file too large, wrong encoding). None of that buys you anything.

The browser can parse CSV and Excel perfectly well before a single byte is sent to the API:
- `papaparse` — streaming CSV parser, handles encoding edge cases and quoted commas correctly
- `xlsx` (SheetJS) — reads `.xlsx`, `.xls`, and Google Sheets exports, converts to plain JS objects

The backend receives a clean JSON array. It never sees the file.

### Normalize column names before validation, not after

HR spreadsheets use inconsistent headers: "Phone Number", "phone", "mobile", "cell". Rejecting anything that isn't an exact match forces HR to reformat their data before importing. Instead, build a normalization map upfront:

```ts
const ALIASES: Record<string, keyof ImportRow> = {
  phone:        'phone_number',
  mobile:       'phone_number',
  discord:      'discord_id',
  full_name:    'name',
  position:     'role',
  // ...
};
```

Normalize first, validate second. The user never sees column mapping errors — only data errors.

### Validate before the network call, not after

Showing validation errors in a preview table before the user clicks Import is strictly better than surfacing them from the API response. The user can fix mistakes in the browser without a round trip. The API still validates (defense in depth), but it should rarely see bad data from the UI.

### Individual row failures should never abort the batch

If row 34 has a Cognito error, rows 35–70 should still be processed. A batch that fails atomically on one bad row forces HR to fix that row, re-upload, and risk re-processing rows that already succeeded.

The endpoint processes each row independently, accumulates results, and always returns 200 with a per-row outcome array. HR gets a clear report of what happened and can re-import only the failed rows.

### Always give the user a paper trail for batch operations

After a 70-employee import, HR needs to know exactly which accounts were created, which were skipped (already existed), and which failed. The results table is enough for review — but "Export results" as a CSV gives them a file they can attach to an onboarding ticket or share with a manager.

---

## 2026-04-18 Account Lifecycle States and Scheduled Cleanup with Celery Beat

This section was written after implementing email verification, pending account states, and automated invite expiry.

---

### Don't trust what you haven't verified

The original flow stamped `email_verified: true` on the Cognito user at creation time. This pre-trusts the email before anyone has proven they can receive mail at that address. If the admin typo'd the email, the account was permanently broken with no clean recovery path.

The fix: remove `email_verified: true` from `AdminCreateUser`. Let Cognito do what it was built for — send a temp password, require verification on first login. Only when the person successfully logs in do we know the email was real.

### Use explicit state over implicit boolean inference

`is_active = False` means two different things: "hasn't verified yet" and "was active, got deactivated." Code that checks `is_active == False` can't tell which. A Celery cleanup job that deletes `is_active = False` employees older than 7 days would silently delete deactivated employees.

The fix: an explicit `account_status` enum — `pending_verification`, `active`, `deactivated`. Now the cleanup query is unambiguous:

```python
db.query(Employee).filter(
    Employee.account_status == "pending_verification",
    Employee.invited_at < cutoff,
)
```

`is_active` stays as a fast boolean for dispatch eligibility checks, but it's derived from `account_status`, not the source of truth.

### The activation moment is a first-class event

"When does an account become active?" should be a deliberate decision, not something that happens as a side effect of a query. In this system, the activation moment is the first time `get_caller_employee` stamps `cognito_sub` — that's the proof that a real person logged in with a verified email. Putting the state transition there means it's atomic with the login, not a separate job that might miss it.

### Celery Beat: the clock and the worker are separate concerns

Beat is just a scheduler — it fires a task message onto the Redis queue at 03:00 UTC. The worker picks it up and executes it. Neither knows about the other's implementation. This separation matters when you scale: if you need two workers for throughput, Beat still fires once. Beat itself is stateless.

For a single-container deployment, `celery worker --beat` runs both in one process. The comment in `docker-compose.yml` explains when to split them.

### Best-effort side effects belong in background threads

The Discord invite webhook fires from a daemon thread in `_send_discord_invite()`. If the bot is down, the thread fails silently after 5 seconds. The login response still completes — the account is still activated. Side effects that don't affect correctness should never block the main path.

---

## 2026-04-18 Time-Gating Business Logic with Config-Driven Windows

This section was written after adding departure-based gating to walker rating submissions.

---

### The pattern: gate on a real-world event, not just calendar time

A naive approach to "only accept ratings today" would check `payload.date == date.today()`. This doesn't prove anything happened — a driver who never left the yard could still submit ratings for the correct calendar date.

The stronger gate checks for a real-world event: did this driver actually depart? Query the `Departure` table for `(employee_id, date)`. If the row doesn't exist or `departed_at` is NULL, the event didn't happen. Reject the request regardless of what date is on the payload.

```python
departure = db.query(Departure).filter(
    Departure.employee_id == payload.driver_id,
    Departure.date == payload.date,
).first()
if not departure or departure.departed_at is None:
    raise HTTPException(status_code=400, detail="...")
```

### Layering a window on top of the event gate

Once you've confirmed the event happened, you can add a staleness window. The key is to anchor the window to the event timestamp, not to midnight or some other arbitrary reference:

```python
window_close = departure.departed_at + timedelta(hours=settings.rating_window_hours)
if datetime.now(timezone.utc) > window_close:
    raise HTTPException(status_code=400, detail="...")
```

This is more accurate than a fixed cutoff time because different drivers depart at different times.

### Why the window belongs in config, not in code

A 6-hour hardcoded constant looks reasonable today. But shift patterns change — a new service area might have a 10-hour window. Encoding the value in `pydantic_settings` with a safe default means:

- Development: default kicks in, no `.env` entry required
- Production: set `RATING_WINDOW_HOURS=8` in the environment, no deployment needed
- The default is visible in code review as an explicit value, not a magic number

### Gate ordering matters

In `submit_rating`, the gates run in this order:
1. Ownership (caller must be the driver)
2. Departure exists and `departed_at` is set ← event gate
3. Window is still open ← staleness gate
4. Payload validation (stars range)
5. Same-truck check
6. Duplicate check

Event and staleness gates come early because they're database reads that can short-circuit before more expensive checks. Ownership comes first because it's a security boundary — no query needed beyond the session.

---

## 2026-04-18 Audit Trails: Write Alongside the State Change, Not After It

This section was written after adding `write_audit()` to seven approval endpoints.

---

### The wrong mental model: audit as a separate step

A common mistake is to think of logging as something that happens *after* the action succeeds — a side effect, a fire-and-forget call, something that runs in a background task. This is wrong for audit trails. If the state change commits and the audit write fails, you have a gap in the audit trail with no way to reconstruct it.

### The right model: same transaction

```python
# BAD — two separate commits, audit can succeed without state or vice versa
db.commit()                     # state change lands
write_audit(...)                # might fail
db.commit()                     # audit row lands (or doesn't)

# GOOD — one commit, both land or neither does
write_audit(db, ...)            # appends to session, does NOT commit
db.commit()                     # state change + audit row are atomic
```

`write_audit()` in this codebase takes the session as its first argument and calls `db.add()` but not `db.commit()`. The caller always commits. This is the contract — never commit inside the helper.

### Snapshot only what changed

`before_snapshot` and `after_snapshot` are not full row dumps — they are the fields that actually changed:

```python
write_audit(
    db,
    action_type="pto.approved",
    target_table="time_off_requests",
    target_id=str(db_request.id),
    before={"status": "pending"},
    after={"status": "approved"},
)
```

Full row dumps make diffs unreadable and bloat the JSONB column. Capture the minimum that lets a reviewer reconstruct what happened.

### `action_type` naming: dot-namespaced verbs

`pto.approved`, `schedule_change.rejected`, `incident.resolved` — not `APPROVE_PTO` or `update_status`. The dot namespace lets you filter by prefix (`action_type LIKE 'pto%'`) to pull all PTO-related entries without needing to enumerate every variant.

### Capturing `actor_id` requires not discarding the dependency

Several endpoints had `_: dict = Depends(allow_mgmt)` — the current user dict was discarded because it wasn't needed at the time. Adding audit logging requires the actor's ID. Change `_` to `current_user` and pass `current_user.get("id")` to `write_audit`. This is always a safe change — you are not adding a new dependency, just using the one that was already there.

---

## 2026-04-18 React Rules of Hooks: What Breaks and Why

This section was written after fixing a TDZ `ReferenceError` in `Preferences.tsx`.

---

### The rule

React hooks must be called at the top level of a component — never inside conditions, loops, or after a conditional return. They must also be called in the same order on every render.

### The `const` TDZ mistake

```tsx
// WRONG — useEffect is declared before the const function it calls
useEffect(() => {
  loadPreferences(myId);   // ReferenceError at runtime
}, [myId]);

if (isAdmin) return <PreferenceAnalytics />;  // also wrong — hook appears before this

const loadPreferences = async (id: string) => { ... };  // defined here
```

JavaScript `const` bindings are not hoisted. The function exists in memory from the start of the closure but cannot be accessed until the interpreter reaches its declaration — this window is the Temporal Dead Zone (TDZ). Calling it before the declaration line throws `ReferenceError: Cannot access 'loadPreferences' before initialization`.

### The early return mistake

A conditional return (`if (isAdmin) return ...`) before a hook call is a Rules of Hooks violation even if it seems logically safe. React tracks hooks by call order — if an early return skips a hook on some renders, the order changes and React throws.

### The fix: all hooks first, early returns last

```tsx
// CORRECT — all hooks at top, early return after
const loadPreferences = async (id: string) => { ... };
const loadChangeRequests = async (id: string) => { ... };

useEffect(() => {
  loadPreferences(myId);    // defined above, no TDZ
}, [myId]);

if (isAdmin) return <PreferenceAnalytics />;  // after all hooks — safe
```

`const` helper functions defined in the component body before the hooks that call them are not hooks themselves — they don't need to be at the very top. The rule is about hooks (`useEffect`, `useState`, etc.), not regular functions.

---

## 2026-04-18 Frontend Role Guards: The Navbar Is Not the Auth Layer

This section was written after the navbar overflow fix revealed management tabs had been silently removed.

---

### The problem with removing links from the navbar

When the navbar became overcrowded for admins, the fix was to remove management tool links (Assets, Trainees, Compliance, Walkers). This correctly fixed the overflow — but it also silently removed those links for management users who depended on them.

The root cause: navbar link visibility was controlled by a single `isAdminOrMgmt` boolean. Removing the block removed it for both roles at once.

### Separate role checks, even when they look the same now

```tsx
// WRONG — one block hides the links for both roles
{isAdminOrMgmt && (
  <NavLink to="/assets">Assets</NavLink>
  ...
)}

// RIGHT — separate blocks so each role can be adjusted independently
{isMgmt && (
  <NavLink to="/assets">Assets</NavLink>
  ...
)}
{isAdmin && (
  <NavLink to="/admin">Admin</NavLink>
)}
```

If two roles need the same links today but might diverge tomorrow, separate the blocks now. Merging them saves two lines of JSX but costs you the ability to adjust them independently later.

### The navbar is not the only place to check

Removing a navbar link does not remove access to the route — `ProtectedRoute` in `App.tsx` is the actual guard. A management user who knows the URL can still reach `/assets` even if the navbar link is gone. Always verify that:
1. The route has the correct `allowedRoles` in `App.tsx`
2. The navbar shows the correct links for each role
3. The command palette actions are visible to the correct roles

These three are independent and all must be kept in sync.

---

## 2026-04-11 How to Think About Role Scope When Building Multi-Role Systems

This section was written after a full audit of every tool, route, endpoint, and nav link in the application revealed systematic role scope mistakes. Every mistake here was made by the developer first, then corrected. Use this as a checklist before you ship any feature that touches roles.

---

### The core mistake: designing features first, roles second

The pattern that created the most bugs in this project was: build the feature → add a role check as an afterthought → miss the edge cases.

The correct pattern is the reverse: **define who can do what before you write a line of code.** Ask these four questions about every feature:

1. **Who submits this action?** (which specific roles, not "anyone logged in")
2. **Can they only do it for themselves, or for others?** (ownership)
3. **Are there state preconditions that must be true before they can act?** (business rules, not just roles)
4. **Who can read and review the results?**

If you cannot answer all four before writing the endpoint, you will write the wrong endpoint and then patch it later — which is what happened throughout this codebase.

---

### Mistake 1: Conflating "authenticated" with "authorized"

Several routers in this project were entirely unauthenticated at launch:
- `trucks.py`, `time_off_requests.py`, `employee_off_days.py`, `employee_relationships.py`, `schedule.py`, `notifications.py`

The reasoning was: "authentication is handled by Cognito upstream, so everything that reaches FastAPI is authenticated." This conflates two different things:

- **Authentication** = you are who you say you are (handled by the JWT)
- **Authorization** = you are allowed to perform this specific action (handled by `RoleChecker`)

Any authenticated user — a driver, a walker, a trainee — could have approved their own time-off request, created bans against other employees, or read any employee's notification feed. These are authorization failures, not authentication failures.

**Rule:** Every endpoint needs a `RoleChecker` or `get_caller_employee` dependency. "Authenticated" is not a sufficient access policy on its own.

---

### Mistake 2: Defining role guards at the file level but not wiring them to endpoints

In `field_ops.py`, `allow_driver = RoleChecker(["driver"])` was defined at the top of the file. It was never passed as a dependency to any endpoint. Every submission POST endpoint — check-in, departure, inspection, fuel log, walker rating — could be called by any authenticated user.

The constant existed. The intent was correct. The wiring was missing.

**Rule:** When you define a role constant (e.g., `allow_driver`), immediately trace it to every endpoint it should protect. If you define it and don't use it, it means the protection is incomplete. Unused role constants are a code smell — they signal intent without enforcement.

---

### Mistake 3: Missing ownership checks

`assignment_change_requests.py` had no check that `payload.employee_id == caller.id`. Any walker or trainer could submit a reassignment request on behalf of any other walker or trainer. The role check (walker/trainer only) existed. The ownership check did not.

These are two separate guards and both are needed:

```python
# Role check — is this person allowed to do this at all?
_: dict = Depends(allow_submitter)

# Ownership check — are they doing it for themselves?
if payload.employee_id != caller.id:
    raise HTTPException(status_code=403, detail="You can only submit for yourself.")
```

**Rule:** Role guard answers "can this type of user do this?" Ownership guard answers "can this specific user do this for this specific target?" Both are required for write actions on personal data.

---

### Mistake 4: Letting one role boolean do the work of three

The original dashboard used a single `isManagement` predicate:

```typescript
const isManagement = groups.some(r => ['admin', 'management', 'dispatch'].includes(r));
```

All three roles saw the same UI, the same quicklinks, the same pending approval cards. The result:
- Dispatch saw management report panels they had no business reading
- Management saw the Dispatch Center link implying they should run dispatch
- Admin was routed to the trainer daily task form and trainee progress page

**Rule:** When a system has roles with distinct responsibilities, each role gets its own predicate. Don't group roles together in a boolean unless they genuinely share every permission.

```typescript
// Wrong
const isElevated = groups.some(r => ['admin', 'management', 'dispatch'].includes(r));

// Right
const isDispatch   = groups.includes('dispatch');
const isManagement = groups.includes('management');
const isAdmin      = groups.includes('admin');
```

---

### Mistake 5: Extending field access to roles without verifying the business domain first

ADR-016 opened `/field-ops` to all field staff (driver, walker, trainer, trainee) based on the reasoning that "check-in is for all field staff." This was factually wrong: walkers and trainers meet at the Anchor Point, not the yard. They do not drive the vehicle and do not perform pre-trip inspections. The route was corrected in the very next session.

The mistake was making a technical decision (route access) before verifying the operational reality (where these people actually go in the morning).

**Rule:** Before adding a role to a route or endpoint, ask: does this person perform this action in real life? Not "could they theoretically" but "do they, in the actual workflow?" If the answer requires you to ask someone who knows the domain, ask before you code.

---

### Mistake 6: Forgetting to enforce business preconditions at the API layer

Truck reassignment had:
- ✅ Role check (walker/trainer only)
- ❌ Today-only date guard
- ❌ Active assignment check
- ❌ Ownership check

A walker could submit a reassignment request for a date two weeks in the future, for a day they are not assigned, on behalf of another employee. All three were silent failures — no error, just a bad row in the database.

Business rules belong in the API, not just in the UI. The UI should guide the user (remove the date picker, show a warning if no pending assignment), but the API must reject invalid states regardless of what the UI does.

**Rule:** For every write endpoint, list the preconditions that must be true. Add a check for each one. "The UI prevents this" is not an excuse for a missing backend guard — the API is a public surface and can be called directly.

---

### Mistake 7: Embedding growing features inside unrelated pages

The Schedule Change Request feature started as a single off-day selector inside `Preferences.tsx`. Over time the requirements grew to three modes (add_day, drop_day, full_rework), a current schedule display, selectable day filtering derived from off-day state, a history list, and a reviewer panel. All of this was being embedded inside a page designed for fav/ban and reassignment preferences.

When a feature grows, it needs its own page. The sign that a feature has outgrown its host page is when the host page starts accumulating state variables, API calls, and JSX sections that are not related to the page's core purpose.

**Rule:** Give features their own page when they need more than a simple form + list. The threshold is roughly: two or more distinct modes, or a reviewer workflow, or state that requires multiple API calls to populate.

---

### Mistake 8: Removing state without removing all its dependents

When removing the schedule change section from `Preferences.tsx`, the state variables (`offDays`, `selectedDay`, `changeRequestDate`) were removed first, but the handlers (`handleAddOffDay`, `handleDeleteOffDay`), the useEffect (`loadOffDays`), and the JSX section were still present and still referenced the now-missing state. This caused 15+ TypeScript errors.

**Rule:** When removing a feature from a component, remove all four of its parts together: state, effects, handlers, JSX. They are a set. If any piece remains, it will reference the missing pieces and break. When the deletions are spread across a large file, a full component rewrite is safer than targeted edits.

---

### The role enforcement checklist

Use this before shipping any feature that involves role-gated actions:

**Backend:**
- [ ] Does the endpoint have a `RoleChecker` or `get_caller_employee` dependency?
- [ ] If the action is on personal data, is there an ownership check (`payload.X != caller.id`)?
- [ ] Are business preconditions validated (date constraints, state preconditions, existence checks)?
- [ ] Are all role constants that are defined actually wired to an endpoint?

**Frontend:**
- [ ] Is the route in `App.tsx` gated to the correct `allowedRoles`?
- [ ] Is the nav link in `Navbar.tsx` visible only to the correct roles?
- [ ] Are component sections inside the page guarded by role predicates (not just the route)?
- [ ] Does each role have its own predicate variable (`isDriver`, `isTrainee`), not shared with other roles?

**Domain:**
- [ ] Have you verified with the business domain that each role actually performs this action?
- [ ] Is the feature's scope appropriate for its host page, or does it need its own page?

---

## 2026-04-09 Role-Based Filtering & Non-Destructive Seeding

### Non-Destructive Seeding
When merging test and seed data, always avoid destructive deletes. Instead, upsert or check for existence before inserting. This preserves manual test users and prevents accidental data loss during development.

### Role-Based Filtering (Backend & Frontend)
Business rules (such as who can be favorited or banned) must be enforced at both the backend (API, seed logic) and frontend (UI selection lists). This prevents privilege escalation and ensures a consistent user experience.

### Full-Stack Role Expansion
When adding new roles (e.g., "trainee"), update all enums, database constraints, backend logic, and frontend filters. Failing to do so can cause silent bugs, constraint violations, or crashes.

### Defensive Coding for Role Logic
Always handle unknown or future roles gracefully in backend logic (e.g., with try/except or default dicts) to prevent crashes when new roles are introduced.



## 2026-04-08 Frontend Build & Auth
### Vite vs. Node.js Polyfills
When using legacy cryptographic libraries built for Node.js (like `@aws-crypto/sha256-js` inside AWS Amplify) within a modern frontend bundler like Vite, you'll encounter a missing `global` object error in the browser console.
**Solution:** Vite intentionally breaks from Webpack's behavior by not auto-injecting `window.global`. You can manually polyfill this in `index.html`: `<script>window.global = window;</script>`.

### OAuth Tokens (IdToken vs AccessToken)
AWS Cognito Federated Identity provides two distinct JSON Web Tokens upon successful SSO (like Discord or Google). 
- **AccessToken**: Meant for authorizing AWS API calls natively. **It does not contain custom user claims or groups.**
- **IdToken**: Contains standardized OAuth user profile claims (Email, Username, Subject), and uniquely, the custom `cognito:groups` array required by our FastAPI `RoleChecker`.
**Solution:** The Axios interceptor explicitly pulls the `IdToken` and passes it as a Bearer Token.

### FastAPI CORS Configuration
React runs on `localhost:3000` (or `3001` via Vite), while the FastAPI backend runs on `localhost:8000`. Browsers enforce Cross-Origin Resource Sharing (CORS) policies. A naked FastAPI backend silently blocks all requests from a React domain.
**Solution:** Implementing FastAPI's `CORSMiddleware` explicitly authorizes `OPTIONS` preflight checks, allowing data to flow seamlessly between the Vite frontend and local API runtime.


### Authentication Flows: SRP vs USER_PASSWORD_AUTH
AWS Cognito supports multiple login flows.
- **USER_PASSWORD_AUTH**: The React frontend sends the plaintext password over HTTPS. Safe enough for dev, but standard.
- **USER_SRP_AUTH**: (Secure Remote Password). A zero-knowledge proof algorithm. The password never physically leaves the browser; instead, a mathematical proof of the password is sent. This is Enterprise-grade.

**AWS Amplify v6** defaults to SRP, but it requires explicit configuration in the AWS App Client settings (`ALLOW_USER_SRP_AUTH`). Our temporary dev workaround was overriding the `authFlowType` to `USER_PASSWORD_AUTH`.

## 2026-04-08 Dual-Layer Time-Off Architecture
### Explicit Calendar Date vs. Day of Week Constraints
When scheduling workers, two types of unavailabilities exist in the business domain that cannot be reconciled into a single data model:
1. **Recurring Constraints:** "This employee never works on Tuesdays." (Dependent purely on the 1-7 Day of Week integer).
2. **Explicit PTO Constraints:** "This employee requested May 14th, 2026 off." (Dependent entirely on an exact `YYYY-MM-DD` Calendar Date).

If you attempt to merge them into a single API or database row structure, you run into validation leaks. A worker who inherently doesn't work on Tuesdays could accidentally be allowed to request a PTO day on a Tuesday, which functionally creates overlapping identical statuses or throws the total allocated PTO logic into disarray.

**Solution:** 
Create two distinct physical tables with separate router controllers: `EmployeeOffDay` (for Day Of Week logic) and `TimeOffRequest` (for specific Date logic).
In the specific Date router, manually parse the Python `datetime.strftime("%A")` of the target request, cross-reference it with the employee's `EmployeeOffDay` array, and throw an explicit HTTP 400 Exception (`"You cannot request time off on a day you are already scheduled off"`) before writing to the database. Upon rendering to the user, the single `schedule.py` endpoint fetches both arrays and constructs a single visual string map, distinguishing between `"Off (Recurring)"` and `"Time Off"` to preserve absolute clarity for the UX.

## 2026-04-09 Trainer Dashboard & Curriculum Injection
### Managing State Across a Multi-Day Lifecycle
The **Trainer Dashboard** orchestrates a complex 5-day stateful relationship between Trainers and Trainees. Because Trainees may rotate their assigned Trainer day over day, the `TrainingRecord` table acts as an immutable historical log of training events specific to one calendar day. 
Our Dispatch algorithm natively leverages a dynamic "Curriculum Injection" hook. When the dispatch engine runs, it detects any Trainee allocations and programmatically searches for prior historical training days. It then intelligently rolls over incomplete mandatory tasks—flagged as "Training Debt"—into the current day's record before appending the current day's scheduled curriculum content. This ensures no training gaps occur even as Trainees change trucks or miss days.

### Soft Deleting via Reassignment Bumping (Trainee Overrides)
Manually overriding Trainees via the dispatch portal necessitates structural cascading un-assignments ("bumping"). When a manager manually places a Trainee onto a truck that already features a Trainee, the algorithm safely deletes the prior seating arrangement. It then automatically scans the pool of available trucks for one that possesses a Trainer mapping but lacks a Trainee mapping, and automatically shifts the bumped individual onto that valid fallback truck.

---

## 2026-04-11 Unit Testing the Dispatch Service Layer

### Why SQLite in-memory for a PostgreSQL app
The dispatch services use SQLAlchemy ORM, which is database-agnostic. SQLite in-memory databases (`sqlite:///:memory:`) spin up in milliseconds, need no Docker container, and are fully isolated per test. Each test gets a completely fresh schema — nothing leaks between tests.

The tradeoff: some PostgreSQL-specific column types (`JSONB`, `ARRAY`) cannot be compiled by SQLite. The solution is a **targeted MetaData** approach — build a list of only the tables your services actually touch, copy them into a fresh `MetaData` object via `table.to_metadata(meta)`, and call `meta.create_all(engine)`. Never use `Base.metadata.create_all` in SQLite tests — it will try to create every model, including ones with PostgreSQL-specific types that will crash.

### The working set principle
Service functions build their state (ban maps, crew maps, lookup dicts) once at the start of the call from the inputs they were given. Data inserted *during* the call (e.g., walkers placed mid-loop) is not visible to state built at the top of the function unless the function explicitly re-queries. This is the most common source of confusion when testing services: "I set it up, why doesn't the function see it?" — because the function's working set was already built from the initial inputs.

In `assign_walkers`, the ban map is built once from the initial `assigned_crews`. Walkers placed during the loop don't appear in the ban map for subsequent iterations. This means the walker-vs-walker ban override can only fire for walkers who were already in `assigned_crews` at call time — not walkers placed within the same call. This is a known architectural limitation documented in `TEST_LOG.md`.

### Never rely on random outcomes in tests
`assign_drivers`, `assign_trainers`, and `assign_walkers` use `random.choices` for weighted selection. Any test that asserts which specific truck was chosen must patch `random.choices` using `unittest.mock.patch`. A test that only passes when a particular random outcome occurs is not a test — it is a gamble. It will pass most of the time and fail occasionally, making it worse than useless (it creates false confidence and occasional mysterious CI failures).

```python
with patch("app.services.assign_walkers.random.choices", side_effect=fake_choices):
    assign_walkers(...)
```

The patch target must be the module where `random.choices` is *used*, not where `random` is defined.

### Never mutate ORM objects to represent ephemeral state
SQLAlchemy tracks all attribute changes on session-attached objects. If you do `employee.role = "walker"` to temporarily re-slot a trainer, the next `db.commit()` will permanently write that change to the database — even if you only intended it as in-memory state for the current dispatch run. Use separate data structures (dicts, lists of tuples) for ephemeral dispatch state. ORM objects are DB records, not scratch space.

This was the root cause of the excess-trainer re-slot bug in `run_dispatch`: the code used `t["role"] = "walker"` (dict syntax, which raises `TypeError` on ORM objects) — but even if it had used `t.role = "walker"`, every dispatch with excess trainers would have silently demoted real trainers in the database.

### Test at the right level
- **Unit tests** cover individual services in isolation — ban logic, spread guarantees, weight calculations.
- **Integration tests** cover `run_dispatch` — pipeline wiring, DB write verification, warning thresholds.
- Don't re-test sub-service internals at the integration level. If `assign_trainers` is already tested to enforce even spread, `run_dispatch` doesn't need to verify that again. The integration test checks: did the pipeline call the right things? Did the rows get committed?

### Bugs are most often found at the boundary
All three production bugs found during this test session were at boundaries:
1. The interface between `ban_override.py` and `assign_walkers` (wrong argument count)
2. The interface between the available pool (ORM objects) and the re-slot logic (dict syntax assumption)
3. The interface between `check_ban_override` (returned `True`) and the caller that expected the evicted walker to be re-placed

Boundary bugs are silent because both sides work in isolation — the failure only appears when they're connected. Integration tests and tests that cross function boundaries are what catch these.

---

## 2026-04-14 Dispatch Warning Timing and Trainer Context Design

### Mistake: Warning emitted at code-path entry, not at outcome

In `assign_walkers`, a ban conflict warning was appended as soon as the fallback path was entered — before `selected_truck` was determined. The reasoning was: "we fell back, therefore there must be a conflict." But falling back does not guarantee a conflict. The fallback pool excludes banned trucks; if the fallback pool is non-empty, the walker is placed on an unbanned truck and no conflict occurred.

The result: dispatchers saw a warning that two employees had a ban conflict and were placed together — but looking at the actual crew assignments, they were on different trucks.

**Rule:** Warnings that describe placement outcomes must be placed *after* the placement, conditional on the outcome. "Entered a constrained code path" and "produced a constrained outcome" are not the same thing. Always ask: is this warning logically true at the point I am emitting it?

```python
# Wrong — warns before placement; placement may avoid the conflict
warnings.append({"employee_id": walker.id, ...})
selected_truck = random.choices(...)

# Right — warns only if placement actually landed on a banned truck
selected_truck = random.choices(...)
assigned_crews[selected_truck].append(...)
if selected_truck in hard_banned:
    warnings.append({"employee_id": walker.id, ...})
```

This is a general principle: **side effects (logs, warnings, notifications) belong after the action that determines their truth, not before.**

---

### Literal path segments must be declared before parameterized ones

FastAPI matches routes in declaration order. If you have:

```python
@router.get("/trainer/{trainer_id}/history")  # declared first
@router.get("/trainer/today")                 # declared second
```

A request to `/trainer/today` will try to parse `today` as a UUID for `trainer_id`. FastAPI returns a 422 validation error — it does not fall through to the next route. The literal route is unreachable.

**Fix:** Always declare routes with literal path segments before routes with parameterized segments at the same position.

```python
@router.get("/trainer/today")                 # literal first
@router.get("/trainer/{trainer_id}/history")  # parameterized second
```

The same issue applies to `/employees/me` vs `/employees/{employee_id}` — `me` must come first.

---

### `GET /me` is worth adding early to any multi-role API

The frontend frequently needs to know the authenticated user's own employee UUID — for fetching their history, submitting their own records, and populating forms. Requiring the frontend to derive this from JWT claims or store it in auth context creates coupling between the auth system and every component that needs it.

A `GET /employees/me` endpoint that resolves via the same `get_caller_employee` dependency used throughout the API makes this a single, consistent call. The frontend calls it once on mount, gets the employee UUID, and passes it to any component that needs it.

**Pattern:**
```python
@router.get("/me", response_model=EmployeeResponse)
def get_my_employee(caller: Employee = Depends(get_caller_employee)):
    return EmployeeResponse.model_validate(caller)
```

---

### Handoff notes belong above the task list, not in history

When redesigning the TrainerDashboard, the initial structure placed trainer-to-trainer handoff notes inside the historical log — the trainer would have to scroll past today's tasks and look through past records to find what the previous trainer had written.

This is the wrong priority. A handoff note from the prior session is the most actionable context a trainer has when they sit down with a trainee. It should be the first thing they see — above the checklist, not below it. The UX should mirror the paper handoff: you read the previous shift's notes before you start work, not after.

**Rule:** Surface time-sensitive, actionable context at the top of the view. Historical context belongs below current-day context.

---

### Per-role history is more useful than aggregated history

The original TrainerDashboard showed the current trainee's history across all trainers. The reworked dashboard shows the trainer's history across all trainees.

Both are useful views, but they serve different audiences:
- **Management** needs the trainee-centric view: how is this trainee progressing regardless of who trained them?
- **Trainers** need the trainer-centric view: what trainees have I worked with, how did they do with me specifically, what notes did I leave?

Mixing both into one view for trainers creates noise. A trainer doesn't need to see what other trainers wrote about a trainee they've never worked with — that context belongs in the management hub, not the trainer's personal dashboard.

**Rule:** When designing a dashboard for a specific role, ask what decisions that role needs to make. Build the view around those decisions, not around the complete data model.

---

## 2026-04-14 Role-Specific Views and the Limits of Conditional Hiding

### Mistake: hiding a form is not the same as removing a page section

The `/schedule-changes` page used a single `isReviewer` flag to hide the submission form for management and admin. But the "Your Current Schedule" summary and "My Requests" history sections were rendered unconditionally — they showed the reviewer's own off-days and their own empty request history, which are meaningless for roles that cannot submit requests.

The fix required recognising that `isReviewer` only hid the action, not the context that surrounded it. Management and admin got a page that was 80% personal data they had no stake in, plus 20% reviewer queue at the bottom.

**Rule:** When a role has no personal stake in a page's subject matter, none of the personal sections should render — not just the action buttons. Hiding the form while leaving the surrounding context is an incomplete fix.

---

### Use branched rendering when roles have meaningfully different purposes on the same page

The correct fix for reviewer vs. field-staff on `/schedule-changes` was not to add more conditionals to the existing JSX tree — it was to split into completely separate render paths:

```typescript
if (isAdmin)      return <AdminView />;
if (isManagement) return <ManagementView />;
return <FieldStaffView />;
```

Each branch renders only what that role needs. There is no shared JSX that partially applies to multiple roles. This approach:
- Makes it impossible for personal sections to leak into reviewer views
- Makes each role's view independently readable — you don't have to mentally subtract conditionals to understand what a given role sees
- Makes future changes to one role's view safe — you edit one branch, not a shared tree with many guards

**Threshold:** Split into branches when two roles have different *purposes* on the page, not just different *permissions*. If the difference is "can edit vs. can only view," a conditional is fine. If the difference is "tracks their own data vs. reviews others' data," branch.

---

### Ask whether a role has a personal stake before granting page access

Admin was given access to the `/schedule` page as a default "admins can see everything" posture. But the Schedule page is a personal schedule viewer and PTO request tool — it only makes sense for roles that are dispatched and have a schedule to view.

The check that was missing: **does this role have a personal stake in the subject matter of this page?**

- Drivers, walkers, trainers, trainees: yes — they are dispatched, they have schedules, they submit PTO.
- Management: yes — they view *others'* schedules and check available staff.
- Admin: no — admins are not dispatched, have no personal schedule, and have better tools for availability data.

**Rule:** Before adding a role to a route, ask: does this role perform actions or consume information that this page provides? "Admin can see everything" is not a policy — it is an abdication of design. Admins should have access to the tools they need, not every tool that exists.

---

### Admin and management are both reviewers but not the same reviewer

Admin and management both review and approve schedule change requests. The initial implementation treated them identically (`isReviewer = isAdmin || isManagement`). But they have different oversight functions:

- **Management** needs the operational queue — what requests are pending right now, approve or reject.
- **Admin** needs the organizational view — how many requests, what types, what's the approval rate, which days are most volatile.

Collapsing them to `isReviewer` loses this distinction. Admins got only the queue; management got the queue plus personal sections they had no use for.

**Rule:** When multiple elevated roles share a capability (reviewing), check whether they share the *same purpose* for that capability. If they don't, give them different views. "Both can approve" is not sufficient reason to show them identical pages.

---

## 2026-04-14 Global vs. Intra-Scope Fairness in Assignment Algorithms

### The mistake: assuming global fairness implies local fairness

`assign_trainees` used a global round-robin: pick any trainer whose paired-trainee count equals the current global minimum. This produces system-wide even distribution — no trainer across all trucks ever gets N+1 before every other trainer reaches N.

But it says nothing about trainers *on the same truck*. A trainer can reach count 2 while their truck-mate is still at 1, as long as everyone else globally is also at 1. From the system's view: balanced. From Truck A's crew's view: one trainer is handling twice the workload.

**Rule:** Global fairness guarantees aggregate balance. It does not guarantee fairness within any subgroup. If the unit of operation cares about subgroup balance (a truck's crew, a team's workload), you must add a subgroup-level constraint explicitly.

---

### The fix: two-level eligibility

The correct pattern for assignment with hierarchical fairness:

1. **Outer scope minimum** — eligible only if at the global minimum across all entities.
2. **Inner scope minimum** — eligible only if at the minimum within your own subgroup (truck, team, region).

A trainer blocked by rule 2 cannot advance even though rule 1 would permit it. Their subgroup peers must catch up first.

```python
global_min = min(paired_counts.values())

def is_eligible(t_id):
    if paired_counts[t_id] != global_min:
        return False                              # blocked by global check
    truck_mates = truck_to_trainers[trainer_to_truck[t_id]]
    truck_min = min(paired_counts[mate] for mate in truck_mates)
    return paired_counts[t_id] == truck_min      # blocked if ahead of truck-mate
```

Build the reverse map (`truck_to_trainers`) once before the loop — not inside it — to avoid O(n²) cost on large crews.

---

### Pre-pass interactions: count early placements before the round-robin runs

`run_dispatch` has a continuation pre-pass that places trainees with their continuation trainer before `assign_trainees` runs. This gives some trainers a head start of 1 before the round-robin begins.

The fix handles this correctly because `paired_counts` is computed from `assigned_crews` at the start of each iteration — it reflects whatever is already in the crew list, whether placed by the pre-pass or a prior round-robin iteration. A trainer with a pre-pass trainee will have count 1 and will be blocked by the intra-truck check until their truck-mates reach 1.

**Rule:** If a service runs after a pre-population step, count the pre-populated state as part of the initial distribution. Never assume a clean-slate count at the start of a sub-service call.

---

### Always add a defensive fallback, but do not rely on it

The two-level check has a theoretical edge case: if every trainer is ahead of their own truck-mates simultaneously (impossible in normal operation but logically possible with circular dependency), the eligible list is empty. An empty `eligible` passed to `random.choice` raises `IndexError`.

The fix includes a fallback that relaxes to global minimum only:

```python
if not eligible:
    eligible = [t_id for t_id, cnt in paired_counts.items() if cnt == global_min]
```

This fallback should never fire. If it does, a log warning should be emitted so the condition can be investigated. **Do not silently swallow unexpected states** — the fallback is a safety net, not a normal code path.

---

## 2026-04-14 Authenticated API Client — Never Use Raw axios

### The mistake: importing axios directly in a page component

`AdminDashboard.tsx` was the only page that imported `axios` directly instead of `axiosClient`:

```typescript
import axios from 'axios';
const API = 'http://localhost:8000/api/v1';
axios.get(`${API}/employees/`)
```

Every other page uses `axiosClient`, which attaches the Cognito `idToken` as `Authorization: Bearer <token>` on every request. Raw `axios` has no interceptor — requests go out without a token.

The backend `RoleChecker` rejected every request with 401. The dashboard rendered completely empty with no error shown and no console warning, because `Promise.allSettled` absorbed all four failures silently.

**Rule:** `axiosClient` is the only permitted way to make API calls in this frontend. Never import `axios` directly in a page or component. The base URL and auth token are already handled — callers only need to provide the path.

---

### Why `Promise.allSettled` makes unauthenticated requests invisible

`Promise.allSettled` is the correct pattern for fan-out fetches: one failure should not block the others from completing. But it means every failure is silently swallowed unless you explicitly inspect each result's `.status` field.

This makes auth failures particularly dangerous. Instead of an error state or a rejected promise, the component receives nothing — state stays at its initial empty value, and the UI renders as if the server returned empty data. There is no visual signal of failure.

The fix eliminates the auth failure vector entirely (use `axiosClient`). But the lesson is broader: **when using `Promise.allSettled`, always log or surface settled rejections.** Silent failure is not the same as graceful degradation.

```typescript
const results = await Promise.allSettled([fetch1, fetch2, fetch3]);
results.forEach(r => {
  if (r.status === 'rejected') console.error('Fetch failed:', r.reason);
});
```

---

### The `include_inactive` pattern for admin-scoped list endpoints

The employee roster on the admin dashboard needs to show all employees — active and inactive — so the admin can see who has been deactivated and the workforce breakdown's "Inactive Employees" section can populate.

The `GET /employees/` endpoint previously hard-filtered `is_active == True` with no override. The fix mirrors the same `include_inactive: bool = False` pattern already on `GET /trucks/`:

- Default (`include_inactive=false`): all callers receive active-only — existing behaviour preserved.
- `include_inactive=true`: restricted to management/admin; returns all records regardless of active status.

**Rule:** When an endpoint needs to serve different scopes to different roles (active-only for field staff, all records for admin), add a query param with a safe default rather than duplicating the endpoint. Gate the elevated scope behind a role check inside the handler.

---

## 2026-04-14 Pagination Limits and Aggregate Counts

### Never derive aggregate counts from a paginated fetch

The admin Workforce Breakdown computed role counts by reducing the `employees` array returned from `GET /employees/`. The endpoint uses a default `limit=100`. With 193 employees, only the first 100 rows were returned — so the breakdown showed 1 trainee instead of 6.

The frontend had no way to know the list was truncated. There was no error, no warning, just wrong numbers.

**Rule:** If a UI element derives aggregate counts (totals, breakdowns, percentages) from a list, that list must be complete. Either fetch without a limit, raise the limit high enough to cover the realistic dataset, or use a dedicated summary endpoint. Never compute aggregates from a paginated slice.

In this codebase: workforce breakdown and KPI counters use `limit=500` on the employees fetch. The backend caps at 500, which comfortably covers the roster. If the roster ever exceeds 500, a dedicated `/employees/summary` endpoint returning pre-computed role counts is the right next step.

---

### Separate the fetch limit from the display limit

The fix for the truncated roster was:
1. Fetch all employees (`limit=500`) — needed for accurate counts
2. Display 50 at a time — needed to avoid an unusable 193-row table

These are independent concerns. The fetch limit is a data-correctness constraint. The display page size is a UX constraint. Conflating them (fetch 50, show 50) produces wrong counts. Separating them (fetch all, show 50) gives correct counts with manageable presentation.

**Pattern for client-side pagination:**
```typescript
// Fetch: get everything needed for counts and search
const allEmployees = await axiosClient.get('/employees/?limit=500');

// Derive: counts use the full array
const roleGroups = allEmployees.reduce(...);

// Display: slice for the current page
const pageSlice = allEmployees.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
```

Reset `page` to 0 whenever the filter or search changes — otherwise the user can be left on page 4 of a 1-result search.

---

## 2026-04-14 Role-Based Home Routing

### The mistake: a single `"/"` route for all roles

The Home navbar link and the `"/"` route both sent every authenticated user to the same `<Dashboard>` component. Admin users saw a generic multi-view widget. Dispatch users saw it too. Trainers and trainees had dedicated dashboards that required manual navigation to reach.

The implicit assumption was "authenticated means you belong on the dashboard." But the dashboard is a lowest-common-denominator view. Roles with dedicated pages should land on those pages.

**Rule:** When a role has a purpose-built home page, they should land there on login and when clicking Home — not on a generic fallback. "Authenticated" is not a sufficient criterion for where to send a user.

---

### Fix: `homeRoute` in the navbar + `RoleRedirect` at `"/"`

Two surfaces need updating — both the navbar link and the route itself:

```typescript
// Navbar: compute homeRoute from groups
const homeRoute = (() => {
  if (groups.includes('admin'))      return '/admin';
  if (groups.includes('dispatch'))   return '/dispatch';
  if (groups.includes('management')) return '/';
  if (groups.includes('trainer'))    return '/trainer-dashboard';
  if (groups.includes('trainee'))    return '/my-training';
  return '/';
})();

// App.tsx: redirect at "/" before rendering Dashboard
function RoleRedirect() {
  const { groups } = useAuth();
  if (groups.includes('admin'))    return <Navigate to="/admin" replace />;
  if (groups.includes('dispatch')) return <Navigate to="/dispatch" replace />;
  if (groups.includes('trainer'))  return <Navigate to="/trainer-dashboard" replace />;
  if (groups.includes('trainee'))  return <Navigate to="/my-training" replace />;
  return <Dashboard />;
}
```

Fixing only the navbar link is incomplete — users can navigate directly to `localhost:3000` or arrive there from a post-login redirect. `RoleRedirect` at the route level handles both cases.

Use `replace` on the `<Navigate>` so the browser history does not gain a `/` entry — the back button skips over the redirect rather than bouncing the user between `/` and their home page.

---

### A rich role-specific view is a page, not an embedded component

`ManagementView` was initially embedded inside `<Dashboard>` at `"/"`. It is a full operations dashboard — KPI row, incident trend, walker performance, training pipeline, fleet compliance. Despite its depth, it had no dedicated route and no page header of its own.

When management was given a dedicated `/management` route, the component needed promotion: add `useAuth` for the user's name, add a greeting header matching the pattern of other dashboards, register the route, and update `RoleRedirect` and `homeRoute` to point there.

**Rule:** If a component has enough content to constitute a user's primary work surface, it should be a standalone page with its own route and header — not a section inside a generic wrapper. The test: would a user bookmark this view directly? If yes, it is a page.

---

## 2026-04-15 Role Branching Within a Page and Self-Resolution via `/employees/me`

### When a page serves two roles with completely different purposes, branch at the top

`/field-ops` is granted to both `driver` and `admin`. Drivers use it as an action tool — check-in, inspection, departure, return, walker rating. Admin uses it as an analytics surface — read-only view of today's field activity across all drivers.

These two purposes share nothing. The correct pattern is a branch at the top of the page export:

```typescript
export default function FieldOps() {
  const { groups } = useAuth();
  const isAdmin = groups.includes('admin');

  if (isAdmin) return <AdminFieldOpsView />;
  // ... driver flow below
}
```

`AdminFieldOpsView` has no knowledge of the driver panels and vice versa. Adding features to one branch never risks breaking the other.

**Rule:** When two roles share a route but have different purposes, branch immediately — don't add conditionals throughout a shared JSX tree. The branch point is the page component itself.

---

### Resolve the authenticated user's employee record with `/employees/me`, not a list search

The driver flow needed the caller's Employee DB ID. The original code fetched `GET /employees/` (active only, default limit 100) and searched for `discord_id === user.username`. This fails silently when:
- The employee is beyond the first 100 records in the default ordering
- The Cognito `username` doesn't match the stored `discord_id` format
- The employee is inactive

`GET /employees/me` resolves directly from the JWT's `sub` / `email` claims — one request, no search, no pagination risk:

```typescript
axiosClient.get('/employees/me').then(res => setEmployeeId(res.data.id))
```

**Rule:** Never resolve "who am I?" by fetching a list and searching it. Use a dedicated `/me` endpoint that the server resolves from the authenticated token. List searches are fragile under pagination and field-matching assumptions.

---

## 2026-04-15 Building Aggregate Analytics Views for Admin Roles

This section was written after replacing the admin's per-employee preference selector with a system-wide analytics view. The pattern applies any time you have a page that serves field staff in edit mode but should serve admin in analytics mode.

---

### Stale role-conditional code is a maintenance hazard

The original `Preferences` page had `isAdmin` sprinkled across six places:
- One `useEffect` gate
- One stale call inside `loadPreferences`
- One JSX block rendering an employee selector
- Three conditions on `canReassign`, `canFavBan`, and the trainee placeholder

When admin's purpose changed (from viewing individual records to viewing aggregates), each of these six spots became stale at different times, creating an inconsistent state where admin would early-return from effects but still render parts of the field-staff UI.

The fix was to move the role branch to a single point — the top of the component:

```typescript
const Preferences = () => {
  const { groups } = useAuth();
  const isAdmin = groups.includes('admin');

  if (isAdmin) return <PreferenceAnalytics />;

  // field staff only below this line
  const isTrainee = groups.includes('trainee');
  ...
};
```

After the early return, every remaining `isAdmin` reference in the component is dead code and should be removed. TypeScript won't catch these — you have to do it manually.

**Rule:** Role branching belongs at the top of the component, not distributed through effects and JSX conditions. One branch point → one cleanup location → no stale guards.

---

### `useMemo` for derived analytics data

Preference analytics derives multiple computed values from the same two raw lists (relationships + employees):

- `empMap` — id-keyed lookup (used by every other derived value)
- `favs` / `bans` — filtered lists
- `mutualBans` — set intersection
- `matrix` — 3×3 role counts
- `matrixMax` — normalizer for color intensity
- `favCounts` / `banCounts` — top-10 sorted aggregates

Without `useMemo`, every one of these recomputes on every render — including renders triggered by expand/collapse toggles that have nothing to do with the data.

Wrap each in `useMemo` with its actual dependencies. The dependency list documents what each value depends on:

```typescript
const empMap = useMemo(() => Object.fromEntries(emps.map(e => [e.id, e])), [emps]);
const favs   = useMemo(() => rels.filter(r => r.relationship_type === 'fav'), [rels]);
const matrix = useMemo(() => { ... }, [rels, empMap]);     // depends on both
const matrixMax = useMemo(() => { ... }, [matrix, matrixTab]); // depends on which tab
```

**Rule:** Derived analytics values should always be memoized. The dependency list is also documentation — it tells you what re-triggers each computation.

---

### Relative color intensity, not absolute thresholds

The role interaction matrix uses heat-map coloring to make the dominant patterns visible at a glance. The naive approach is to pick thresholds: "0–5 = light, 6–15 = medium, 16+ = dark." This breaks the moment the data doesn't fit those ranges.

The correct approach is relative intensity:

```typescript
const intensity = val / matrixMax;
const bg = `rgba(34,197,94,${intensity * 0.35})`;
```

`matrixMax` is the largest value in the current tab (favs or bans). Every other cell is colored proportionally. A dataset with max=3 and a dataset with max=300 both produce a visible gradient — the darkest cell is always clearly darkest.

**Rule:** Heatmap coloring should be relative to the dataset maximum, not absolute. Hard-coded thresholds require ongoing calibration as data grows.

---

### Mutual ban detection via set membership (O(n), not O(n²))

Finding mutual bans — pairs where A bans B *and* B bans A — could be done with a nested loop over the ban list. That's O(n²) and runs on every render.

The efficient approach:

1. Build a `Set` of all ban pairs as `"employeeId:targetId"` strings — O(n)
2. Iterate the ban list once, check `banSet.has(reverse)` — O(1) per lookup
3. Track seen pairs with a sorted key to avoid duplicates

```typescript
const banSet = new Set(bans.map(r => `${r.employee_id}:${r.target_employee_id}`));
const seen = new Set<string>();
const pairs: { a: string; b: string }[] = [];
for (const r of bans) {
  const reverse = `${r.target_employee_id}:${r.employee_id}`;
  const key = [r.employee_id, r.target_employee_id].sort().join(':');
  if (banSet.has(reverse) && !seen.has(key)) {
    seen.add(key);
    pairs.push({ a: r.employee_id, b: r.target_employee_id });
  }
}
```

Total: O(n). The sorted key (`[a, b].sort().join(':')`) ensures the pair `(A,B)` and `(B,A)` both map to the same dedup string.

**Rule:** Intersection problems (does X also appear in set Y?) are O(1) per lookup with a Set. Don't use nested loops for membership checks.

---

## 2026-04-15 Designing Consolidated Management Views

This section was written after consolidating management's schedule oversight from two separate pages into one unified `ScheduleManagementView` component on the `/schedule` route.

---

### The "same route, different purpose" pattern applies to management too

When a route's purpose differs completely between two role groups, branch immediately at the component level. This is true even when the roles seem related.

Management and field staff both have a legitimate interest in `/schedule`, but for opposite reasons:
- Field staff: "What am I assigned to? Can I request PTO?"
- Management: "What requests are pending? Who is available next week?"

Putting both views in one component, gated by `isPrivileged` flags scattered through JSX, means every change to the management view risks touching field-staff rendering logic. Branching early prevents this:

```typescript
if (isPrivileged) return <ScheduleManagementView isAdmin={isAdmin} />;
// field staff view below — completely isolated
```

**Rule:** When two role groups visit the same route for fundamentally different reasons, branch at the top of the component. Don't add `{isPrivileged && (...)}` blocks inside a shared JSX tree.

---

### Unified queues need triage tools built in

The original approval queue was a flat 2-column grid of all pending request types. It had no sort order, no filter, and no indication of how long each request had been waiting. A manager scanning 15 pending items had no way to identify the most urgent without reading every card.

A useful approval queue has three things:

1. **Type filter** — switch between All / PTO / Workday / Rework. Allows focused review of one category at a time.
2. **Sort order** — "Oldest first" surfaces requests that have been waiting longest. This is the de facto SLA enforcement mechanism without needing formal SLA tooling.
3. **Age badge** — makes the wait time visible without requiring the reviewer to do date math:

```typescript
const daysSince = (isoStr: string) => Math.floor((Date.now() - new Date(isoStr).getTime()) / 86_400_000);

// Color-coded: neutral < 3d, yellow 3–6d, red ≥7d
const cls = days >= 7 ? 'bg-danger/10 text-danger'
  : days >= 3 ? 'bg-warning/10 text-warning'
  : 'bg-accent text-muted-foreground';
```

**Rule:** Any approval queue that can accumulate items needs: type filtering, age visibility, and oldest-first sort. Without these, the oldest items sink to the bottom and get missed.

---

### Use parallel requests for day-by-day aggregation when no summary endpoint exists

The 4-week availability heatmap needed availability data for 28 consecutive days. The existing endpoint was `GET /schedule/available/{date}` — one call per day.

Two options:
1. Add a backend endpoint `GET /schedule/availability-summary?start=...&end=...` that returns all 28 days in one response
2. Fire 28 parallel requests in the frontend

Option 1 is correct at scale. Option 2 is acceptable when:
- The endpoint is cheap (a simple DB query per date)
- The number of calls is bounded and small (28 is reasonable; 365 is not)
- A new backend endpoint would add complexity that isn't yet justified

```typescript
Promise.allSettled(
  dates.map(dt =>
    axiosClient.get(`/schedule/available/${dt}`).then(r => ({ dt, data: r.data }))
  )
).then(results => {
  const map: Record<string, {...}> = {};
  for (const res of results) {
    if (res.status === 'fulfilled') map[res.value.dt] = summarize(res.value.data);
  }
  setHeatmapData(map);
});
```

`Promise.allSettled` ensures partial failures (a single date returning 500) don't blank the entire heatmap — the other 27 days still render.

**Rule:** Parallel requests with `Promise.allSettled` are an acceptable substitute for a summary endpoint when the call count is small and bounded. Document the threshold in the ADR so future maintainers know when to add the endpoint instead.

---

### Route access flags need to be updated in both the route config and the navbar

Every route has two access controls:
1. The `allowedRoles` array on the `<ProtectedRoute>` in `App.tsx` — determines whether navigation to the URL succeeds
2. The visibility condition on the `<NavLink>` in `Navbar.tsx` — determines whether the link appears in the navigation

These must stay in sync. Adding a role to `allowedRoles` without updating the navbar means the role can navigate directly to the URL but won't see the link. Updating the navbar without updating `allowedRoles` means the link appears but clicking it produces an "Access Denied" page.

When you add a role to a route, update both surfaces in the same commit.

```typescript
// App.tsx
<Route path="/schedule" element={
  <ProtectedRoute allowedRoles={['driver', 'walker', 'trainer', 'trainee', 'management', 'admin']}>
    <Schedule />
  </ProtectedRoute>
} />

// Navbar.tsx
const canAccessSchedule = isFieldStaff || groups.includes('management') || groups.includes('admin');
```

**Rule:** Route access is a two-surface change: `allowedRoles` in the route config AND the visibility flag in the navbar. Never update one without the other.

---

## 2026-04-15 Designing Drill-Down Pages for Aggregate Dashboard Cards

This section was written after building the Vehicle Compliance page in response to the management dashboard's "Vehicle Compliance (7d)" card being uninterpretable.

---

### Aggregate metrics without explanation read as per-record facts

The original card showed: **"Brakes — 3 failures, 15% fail rate"**.

A manager reads this as: "There is a truck with brake problems." What it actually means is: "Of all pre-trip inspections submitted fleet-wide in the last 7 days, 3 of them marked brakes as failed." The "15% fail rate" is the percentage of all inspections — not the percentage of trucks that have brake issues.

Aggregate summaries are useful (they surface patterns invisible in individual records), but they must be labeled as aggregates. Add an explanatory sentence wherever an aggregate number is displayed that could be misread as a per-entity fact:

```tsx
<p className="text-xs text-subtle mb-4">
  How many inspections flagged each item as failed across all drivers and trucks this week.
  A high fail rate signals a recurring mechanical issue — visit{' '}
  <a href="/vehicle-compliance">Vehicle Compliance</a> to see which trucks and drivers are responsible.
</p>
```

**Rule:** Every aggregate metric on a dashboard card needs one sentence explaining what the unit of measurement is. If a number could be misread as a per-entity count, it probably will be.

---

### Dashboard cards should link to their drill-down page

A dashboard is a summary surface. When a card shows something actionable (a high failure rate, an escalated trainee, an unresolved incident), the manager's next step is to investigate. If there's no clear path from the card to the detail view, they have to navigate manually or won't follow up at all.

Every dashboard card that summarizes something with a dedicated page should end with a link:

```tsx
<a href="/vehicle-compliance" className="block text-center text-xs text-primary hover:underline pt-4">
  View full compliance report →
</a>
```

This is a one-liner that dramatically improves discoverability. Apply it retroactively to existing cards (Incidents → `/incidents`, Training Pipeline → `/trainee-management`, etc.).

**Rule:** Dashboard cards are entry points, not endpoints. Always include a "View all →" or "Full report →" link to the detail page.

---

### The heatmap axis toggle resolves two conflicting analysis needs

The Vehicle Compliance heatmap answers two different questions:
1. **Which truck keeps failing brakes?** → need item × truck axis
2. **Which driver keeps submitting failed inspections?** → need item × driver axis

Both are valid. Building separate tables for each wastes space. A tab toggle with two states (`by truck` / `by driver`) lets the same heatmap answer both:

```tsx
const [axis, setAxis] = useState<'truck' | 'driver'>('truck');
// ... matrix is re-derived from useMemo([failed, axis])
```

The toggle costs two lines of state and one extra `useMemo` dep. The alternative — two full heatmap tables always rendered — doubles the DOM and makes the page harder to read.

**Rule:** When a visualization answers two related but distinct questions by changing one axis, implement a toggle rather than two separate sections. Keep the toggle state as minimal state (`useState`), derived data as `useMemo`.

---

### Client-side filtering is correct when the full dataset is already fetched

The history table filter (by driver, truck, pass/fail) runs entirely in the browser against the already-fetched dataset. This is the right choice when:

1. The dataset was already fetched in full for other purposes (KPIs, heatmap)
2. The record count is small enough to hold in memory (hundreds, not tens of thousands)
3. Filter changes should feel instant (no loading states)

The alternative — server-side filtering via query params — is correct when:
1. The dataset is too large to fetch in full
2. Only a small fraction of records will ever be viewed
3. The page only shows filtered results, not aggregates derived from the full set

In this case, the KPIs and heatmap need the complete unfiltered dataset anyway, so fetching filtered subsets per filter change would waste both — you'd need to maintain two fetches (full for aggregates, filtered for table). Fetch once, filter in memory.

**Rule:** Client-side filtering is correct when the full dataset is already in memory for other computations. Only move to server-side filtering when the dataset size makes the full fetch impractical. Document the threshold.

---

## 2026-04-15 Building Performance Grading Systems

This section was written after adding all-time letter grades, a leaderboard, and a per-walker profile panel to the walker performance view.

---

### Letter grades give management a normalised signal; raw numbers do not

A dashboard card showing "84% presence, 3.7 ★" requires the viewer to do interpretation work: Is 84% good? Is 3.7 out of 5 acceptable? How does this compare to other walkers?

A letter grade collapses that interpretation into one character that is immediately actionable:
- A/B = this person is performing well, no action needed
- C = worth watching, check the trend
- D/F = escalate, start a performance conversation

The grade is computed once on the backend from a stable formula, so management always sees the same signal regardless of how they access the data (dashboard card vs full page).

```python
def grade(presence_rate, avg_stars):
    p = (presence_rate or 0) / 100
    s = (avg_stars or 0) / 5.0
    combined = p * 0.5 + s * 0.5
    if combined >= 0.90: return "A"
    if combined >= 0.75: return "B"
    if combined >= 0.60: return "C"
    if combined >= 0.45: return "D"
    return "F"
```

**Rule:** When a summary metric has multiple dimensions (presence + quality), compute a single normalised score on the backend. Expose the raw dimensions alongside it, but lead with the grade. Viewers should not have to do math.

---

### Fixed thresholds outperform percentile rankings for absolute quality signals

An alternative grading approach is to rank by percentile: top 20% = A, next 20% = B, etc. This feels objective but has a critical flaw: if the entire fleet performs badly, the top performer still earns an A. The grade becomes meaningless as an absolute quality signal.

Fixed thresholds (A ≥ 90%, B ≥ 75%, etc.) mean a C-grade is a C-grade regardless of who else is on the team. This is the correct choice when the grade is used to trigger performance action rather than just to rank people relative to each other.

**Rule:** Use fixed thresholds for grades when the grade is an absolute quality signal. Use percentile ranking only when the purpose is purely relative comparison (e.g., "who is the top performer this week?").

---

### Trend detection requires splitting the history, not comparing to a static baseline

The wallet profile panel shows whether a walker is Improving, Stable, or Declining. The naive approach is to compare this week's average to their all-time average — but this is meaningless if their all-time history is three weeks old.

The correct approach splits the full rating history in half chronologically, compares the first half (older) to the second half (more recent), and interprets the direction:

```typescript
const recent = rated.slice(0, Math.ceil(rated.length / 2));  // newer
const older  = rated.slice(Math.ceil(rated.length / 2));      // older
const diff = recentAvg - olderAvg;
if (Math.abs(diff) < 0.2) return 'stable';
return diff > 0 ? 'up' : 'down';
```

The 0.2-star threshold filters out noise — small fluctuations aren't meaningful trends. Require a minimum sample (≥4 rated shifts) before showing a trend at all.

**Rule:** Trend detection should split history into time buckets and compare them, not compare to a global average. Apply a noise threshold to avoid flagging small fluctuations as meaningful trends.

---

### Slide-in panels are better than modals for record detail

When a user clicks a row in a table to see detail, the two common approaches are:

1. **Modal** — a floating dialog centred on screen, usually with a dark overlay
2. **Slide-in panel** — a fixed drawer that appears from the right, occupying a partial-width side panel

Modals are correct for confirmations and short forms. They're wrong for detail views because:
- The overlay blocks the table behind — the user loses context about where they are
- Modals don't scroll well when content is long (rating history can be many entries)
- Modals feel disruptive for browse-and-review workflows

A slide-in panel keeps the table partially visible, has natural vertical scroll, and visually signals "you're looking at a detail of the thing you clicked" without a full-page navigation:

```tsx
// Panel anchored to the right edge, full height
<div className="fixed inset-0 z-50 flex justify-end">
  <div className="absolute inset-0 bg-black/30 backdrop-blur-sm" onClick={onClose} />
  <div className="relative w-full max-w-lg bg-card border-l border-border shadow-2xl flex flex-col overflow-hidden">
    {/* content */}
  </div>
</div>
```

**Rule:** Use slide-in panels for record detail views, not modals. Modals are for confirmations and short forms. Panels are for browsing detail within a list context.

---

## Statistical Defensibility: Minimum Sample Thresholds

When computing aggregate metrics (grades, scores, ratings), a small sample size produces a misleadingly precise result. One shift with 5 stars = A grade, but that A means nothing.

The pattern: **gate the metric behind a minimum sample threshold, return `null` otherwise, and surface the reason in the UI.**

```python
# Backend: accept threshold as query param, mark eligibility in response
@router.get("/walker-leaderboard")
def get_walker_leaderboard(min_shifts: int = Query(1, ge=1)):
    ...
    grade_eligible = total_shifts >= min_shifts
    return {
        "grade": compute_grade(...) if grade_eligible else None,
        "grade_eligible": grade_eligible,
        ...
    }
```

```tsx
// Frontend: explain ungraded state contextually, not generically
{!w.grade_eligible && (
  <span className="text-xs text-subtle italic">({w.total_shifts} shifts)</span>
)}

// Info banner so users understand why some rows are blank
{ungraded.length > 0 && (
  <div className="...">
    {ungraded.length} walkers below the {minShifts}-shift threshold — adjust the threshold to include them.
  </div>
)}
```

**Rule:** Never display a metric that will mislead. Return `null` + a reason flag from the API. Explain the gap in the UI rather than hiding it or showing a confusing value.

---

## Filtering Without Touching KPIs

When a panel shows both summary statistics (KPIs) and a detail list, filtering should apply to the list only. Filtering the KPIs creates an inconsistency: the "Grade B" badge in the header would change to "Grade A" if you filtered to a good month, even though the canonical grade is B.

**Pattern:** always compute KPIs from the full dataset; apply filters only to the records list.

```python
# Backend: full history for KPIs, filter only the ratings list
all_rows = db.query(WalkerRating).filter(...).all()
filtered = [r for r in all_rows if r.date >= start_date]  # only for the list

total = len(all_rows)          # KPI: all-time
avg_stars = compute(all_rows)  # KPI: all-time
return { ..., "ratings": serialize(filtered) }  # list: filtered
```

**Rule:** KPIs are all-time unless the page is explicitly a "period report." Filters narrow what you browse, not what the aggregate says.

---

## Client-Side CSV Export

For datasets already fetched into the frontend, a server-side export endpoint is unnecessary overhead. Construct the CSV in the browser and trigger a download:

```tsx
function exportToCSV(rows: Row[]) {
  const headers = ['Name', 'Grade', 'Avg Stars'];
  const data = rows.map(r => [r.name, r.grade ?? '', r.avg_stars?.toFixed(2) ?? '']);
  const csv = [headers, ...data]
    .map(row => row.map(v => `"${String(v).replace(/"/g, '""')}"`).join(','))
    .join('\n');

  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `export-${new Date().toISOString().split('T')[0]}.csv`;
  a.click();
  URL.revokeObjectURL(url);  // clean up immediately
}
```

Export the `visible` (filtered + sorted) array, not `walkers`. This way the export respects whatever filter the user has applied. The file name always includes today's date for traceability.

**Rule:** Client-side CSV from already-loaded data is simpler and faster than a server endpoint. Only add a server export endpoint when data is paginated or too large to load all at once.

---

## Detecting Outliers: Deviation From Mean

When a metric comes from multiple sources (different drivers rating the same walker), the *variance* tells you whether to trust the mean. A walker with a 3.5 avg from ten drivers who all gave 3–4 is very different from a 3.5 avg where one driver gave 5 and another gave 2.

**Pattern:** compute per-source avg, compare to the overall mean, flag sources whose deviation exceeds a threshold:

```python
# Group by source
from collections import defaultdict
buckets = defaultdict(list)
for row in rows:
    buckets[row.driver_id].append(row.stars)

overall_avg = sum(all_stars) / len(all_stars)
FLAG_THRESHOLD = 1.0

for driver_id, stars in buckets.items():
    avg = sum(stars) / len(stars)
    deviation = avg - overall_avg
    flagged = abs(deviation) >= FLAG_THRESHOLD
```

**Threshold choice:** On a 1–5 scale, 1.0 star = 20% of the full range. It's large enough to filter noise while still catching meaningful divergence. Return the threshold value in the API response so the frontend can display it without hardcoding it.

**Rule:** Don't just surface the aggregate — surface its reliability. Flag sources that deviate significantly, and explain in the UI that this may indicate bias rather than actual quality variation.

---

## Security: Never Trust Client-Supplied Identity

Any field in a request body or query param that identifies "who is doing this" is a forgery vector. The pattern to eliminate it:

```python
# WRONG — client supplies their own identity
@router.post("/incidents/")
def submit_incident(payload: IncidentCreate, db=Depends(get_db)):
    reporter = db.query(Employee).filter(Employee.id == payload.reporter_id).first()

# RIGHT — server resolves identity from the JWT
@router.post("/incidents/")
def submit_incident(payload: IncidentCreate, reporter: Employee = Depends(get_caller_employee)):
    # reporter is the authenticated caller — not forgeable
```

Same pattern applies to query params:

```python
# WRONG — any caller can read any employee's data
@router.get("/incidents/my")
def get_my_incidents(reporter_id: UUID = Query(...), ...):
    q = q.filter(Incident.reporter_id == reporter_id)

# RIGHT — caller can only see their own
@router.get("/incidents/my")
def get_my_incidents(caller: Employee = Depends(get_caller_employee), ...):
    q = q.filter(Incident.reporter_id == caller.id)
```

**Rule:** If you find yourself accepting an ID that identifies the caller, replace it with `get_caller_employee`. The only IDs a request body should supply are IDs of *other* records (e.g., which truck, which walker) — never the caller's own identity.

---

## Security: Validate at the Schema Boundary

File upload size caps, format checks, and enum validation belong in Pydantic validators — not in route handlers, not in models. They run before the DB is touched and produce clean 422 responses.

```python
from pydantic import field_validator

_MAX_PHOTO_BYTES = 5 * 1024 * 1024  # 5 MB

class IncidentCreate(BaseModel):
    photo_url: Optional[str] = None

    @field_validator("photo_url")
    @classmethod
    def check_photo_size(cls, v):
        if v is not None and len(v.encode("utf-8")) > _MAX_PHOTO_BYTES:
            raise ValueError("photo_url exceeds the 5 MB size limit.")
        return v
```

**Rule:** Any constraint on input data that can be expressed as a Pydantic validator should be. Schema-layer validation is automatic, self-documenting, and returns structured errors without touching the DB.

---

## Security: Use `get_caller_employee` for All Reviewer/Auditor Attribution

Whenever an endpoint needs to record *who performed an action* (approved, rejected, resolved), use `get_caller_employee` rather than looking up the employee manually:

```python
# WRONG — fragile; only works for Discord-linked accounts
reviewer = db.query(Employee).filter(
    Employee.discord_id == current_user.get("username", "")
).first()
req.reviewed_by = reviewer.id if reviewer else None  # None when lookup fails

# RIGHT — handles all account types, always non-None or raises 403
@router.patch("/{id}/approve")
def approve(reviewer: Employee = Depends(get_caller_employee), ...):
    req.reviewed_by = reviewer.id  # always set correctly
```

`get_caller_employee` implements a four-step lookup chain (cognito_sub → discord_id → email → UUID) and permanently stamps `cognito_sub` for future fast-path lookups. Never replicate this logic manually.

---

## Security: JWKS Cache — Handle Key Rotation with a Single Retry

AWS Cognito signing keys rotate periodically. A cache that never refreshes will fail on new tokens after a rotation until the service restarts. The correct pattern: refresh once on a `kid` miss.

```python
_jwks_cache: dict[str, dict] = {}  # kid → key mapping

def verify_token(token):
    kid = jwt.get_unverified_header(token)["kid"]
    jwks = get_jwks()
    key = jwks.get(kid)
    if not key:
        # Possible key rotation — re-fetch once
        _jwks_cache.update(_fetch_jwks())
        key = _jwks_cache.get(kid)
    if not key:
        raise HTTPException(401, "Public key not found.")
    # ... decode with key
```

One retry distinguishes rotation (new kid appears after re-fetch) from forgery (kid still absent). Two retries could mask forgery; zero retries means rotation requires a restart.

---

## 2026-04-16 Bot Architecture: One Process, Multiple Cogs

### Build one bot with a Cog structure, not multiple bots

Discord's operational model is one bot per server. Multiple bots mean multiple identities, multiple permission sets, and employees needing to know which bot handles which command. The correct pattern is one bot process with feature areas split into Cogs — self-contained modules each responsible for one domain.

```
bot/
├── main.py              # bot init, loads cogs, webhook server
├── cogs/
│   ├── dispatch.py      # Phase 1 — publish, DMs, confirmations
│   ├── schedule.py      # Phase 2 — /schedule command
│   └── eta.py           # Phase 2 — ETA posting
└── services/
    └── api_client.py    # shared HTTP client, used by all cogs
```

**Rule:** Start with the Cog structure from day one, even if you only have one Cog. Adding a second feature to a flat `bot.py` requires a refactor. Adding a second Cog to a Cog-structured bot requires adding one file.

### Use Redis for ephemeral operational state, not PostgreSQL

Confirmation state (pending/confirmed/declined per employee per day) has three properties that make Redis the right choice over PostgreSQL:

1. **It's ephemeral** — today's confirmations are irrelevant tomorrow
2. **It doesn't need to be joined** — no SQL queries reference it
3. **It needs automatic expiry** — a 48-hour TTL handles cleanup without a scheduled job

```python
# Key pattern: dispatch:confirmations:{YYYY-MM-DD}
# Value: hash of { employee_id: "pending" | "confirmed" | "declined" }
await r.hset(key, employee_id, status)
await r.expire(key, 48 * 60 * 60)
```

**Rule:** Before adding a new DB table, ask: is this data relational? Does it need to be queried with joins or aggregated in reports? If the answers are no, and the data has a natural expiry, Redis is the right store.

### Secure internal service-to-service calls with a shared secret

The backend calls the bot's internal webhook to trigger publishes. This is an internal Docker network call — but it should still be authenticated so the endpoint can't be triggered by anything that reaches port 8001.

The minimal pattern: both services read `INTERNAL_SECRET` from the environment. The caller adds it as a header; the receiver rejects requests without it.

```python
# Sender (backend)
headers={"X-Internal-Secret": os.environ.get("INTERNAL_SECRET", "")}

# Receiver (bot)
secret = request.headers.get("X-Internal-Secret", "")
if secret != os.environ.get("INTERNAL_SECRET", ""):
    return web.Response(status=401)
```

**Rule:** Internal service calls on a private network are not inherently safe — a misconfigured proxy or compromised container could reach them. Always add a shared secret. The cost is two env var reads; the protection is significant.

### `timeout=None` on Discord button views for operational reliability

By default, `discord.ui.View` times out after 180 seconds and buttons stop responding. For operational buttons (confirm/decline an assignment) this is unacceptable — an employee might not see their DM for 10 minutes.

```python
class ConfirmationView(discord.ui.View):
    def __init__(self, ...):
        super().__init__(timeout=None)  # persists across bot restarts
```

Disable buttons after the first response so the employee can't change their answer. The view state is ephemeral — on bot restart, old views become non-functional, but the confirmation is already recorded in Redis.

**Rule:** Any Discord button that records a one-time operational response should use `timeout=None` and disable all buttons after the first interaction.

---

## 2026-04-16 Duplicate Entry Points Signal a Missing Consolidation Decision

### When two routes show the same content to the same role, one of them is wrong

Management had access to both `/schedule` and `/schedule-changes`. Both surfaced a schedule change request approval queue. `/schedule` did it better — it included a heatmap, age badges, PTO approvals alongside schedule change approvals, and type filtering. `/schedule-changes` for management was a subset with no additional value.

The root cause: the approval queue was built first on `/schedule-changes`, then the `/schedule` management view was built later and replicated it with improvements. The old entry point was never removed.

**Rule:** When a role has access to two routes that partially overlap, that is a signal that a consolidation decision was deferred, not made. Ask: does this role have a distinct purpose on each route, or are they doing the same thing in two places? If the same thing, remove the inferior entry point entirely — don't just make them equivalent.

### Absence from an allowlist is not always intentional

`dispatch` was missing from `/schedule-changes` `allowedRoles`. The route comment said "dispatch excluded — not their job." But dispatch employees are dispatched workers with a weekly schedule. They have exactly the same need to submit add/drop/rework requests as any driver or walker.

The exclusion was carried over from an earlier version of the route when dispatch's role was less clearly defined. By the time the role architecture was finalized, the exclusion was never revisited.

**Rule:** When adding or removing a role from a route, check every other route in the same domain for consistency. An exclusion that made sense at one phase of the project may be wrong after a later role architecture decision. Route access is not "set and forget."

---

## 2026-04-16 Complete the Loop: Submission Without Review is Half a Feature

### A data collection endpoint without a review surface is an incomplete feature

The feedback system had a modal for submitting feedback and a backend endpoint to store it. But there was no admin UI to read, triage, or act on submissions. Feedback went into the database and stayed there — invisible to anyone unless they queried the DB directly.

This is a pattern that appears in many systems: the submission path is built first (it's visible to users, it feels like progress), and the review surface is deferred as a "future task." But a feature that collects data with no one consuming it isn't a feature — it's a data sink.

**Rule:** Whenever a form submits data that a privileged user needs to act on, build the review surface in the same session. The submission endpoint and the inbox are one feature, not two. If you ship the form without the inbox, you have half a feature.

### Role scope should follow who has operational stake, not who has elevated access

`GET /feedback/` was gated to `management` + `admin`. Management was included by default, likely because they're an elevated role. But management's operational concern is scheduling, approvals, and crew oversight — not triaging bug reports or feature requests. They have no meaningful action to take on a piece of feedback.

The correct question is not "which roles are elevated?" but "which roles have operational stake in this data?" For feedback, the answer is admin (the developer/system owner) only.

**Rule:** When deciding which roles can access an endpoint, ask: which roles have a *reason* to act on this data? Elevated access level is not a sufficient reason on its own. Include only the roles with actual operational stake.

---

## 2026-04-16 Read From State, Not Hardcoded Fallbacks

### Event handlers should derive API payloads from loaded state, not constants

`handleDropToTruck` in `DispatchDashboard.tsx` sent `role: "walker"` hardcoded to the backend whenever an employee was dragged from the unassigned panel to a truck. The `availablePool` state map — which contains the full employee record including `role` — was already loaded and available in the same component. The data was there; the handler just didn't use it.

The consequence: any trainer, driver, or trainee dragged manually was stored in the DB with `role = "walker"`, creating a silent mismatch between the displayed role (sourced from `employees[id].role` in the UI) and the stored assignment role.

**Rule:** When a component renders data from a state map, that map is the correct source for values in event handlers that need to send data to an API. Never hardcode a value that could be read from already-loaded state. The only safe fallback is for genuine missing-data cases, not as a shortcut for data that's already available.

```typescript
// Wrong — hardcodes role regardless of who was dragged
role: "walker"

// Right — reads from the state map that drives the UI
const emp = availablePool[employeeId] || employees[employeeId];
const role = emp?.role || 'walker';
```

The `|| 'walker'` fallback is still present for defensive completeness (if neither map has the record, something else is already broken), but it should never fire in normal operation.

---

## 2026-04-16 Inverse Function Consistency

### Inverse functions share a contract — gaps in one are bugs by definition

`get_available_pool` and `get_unavailable_staff` are inverses: every employee in the available pool should be absent from the unavailable list, and every excluded employee should appear in the unavailable list with a reason. They implement the same exclusion logic from opposite directions.

The bug: `get_available_pool` excluded employees with approved recurring off-days but not employees with approved PTO requests. `get_unavailable_staff` excluded both. An employee with approved PTO for a given date appeared in the dispatch pool and could be assigned to a truck on their day off.

The functions were written at different points in time. Their exclusion logic was never cross-checked. The PTO filter was added to `get_unavailable_staff` correctly and simply never backported to `get_available_pool`.

**Rule:** When two functions are inverses of each other, treat their exclusion logic as a shared contract. Any exclusion criterion in one must exist in the other. Review both functions together whenever either is modified.

### The `~or_(...)` pattern for multi-condition SQLAlchemy exclusions

When a query must exclude rows matching any of several independent conditions, the cleanest SQLAlchemy pattern is:

```python
~or_(condition_a, condition_b)
```

Each condition is a separate EXISTS subquery (or scalar expression). SQLAlchemy compiles both into the same SQL query — one round-trip, no Python-level filtering needed. This is preferable to:
- Chaining multiple `~condition` filters (which produces `NOT A AND NOT B` — correct but less readable than `NOT (A OR B)`)
- Fetching the exclusion set in Python and filtering in memory (an extra round-trip)
- Using a LEFT JOIN with NULL filter (equivalent but harder to read for exclusion patterns)

---

## Security: Remove Hardcoded Credentials From Source Code

Config defaults that contain credentials get committed to source control and used silently in production if the env var is missing:

```python
# WRONG — credential in source code, silently used if DATABASE_URL not set
database_url: str = "postgresql://user:password@host/db"

# RIGHT — no default; missing env var causes loud startup failure
database_url: str  # required; set in .env
```

The credential belongs in `.env` (gitignored), not in `config.py` (tracked). A loud `ValidationError` at startup is always preferable to silently connecting to the wrong database.

---

## Testing: Add New Tables to DISPATCH_TABLES When Services Need Them

`conftest.py` uses a targeted `MetaData` (not `Base.metadata.create_all`) so SQLite doesn't try to compile PostgreSQL-specific columns. Every time a service is updated to query a new table, that table must be added to `DISPATCH_TABLES`:

```python
from app.models.time_off_request import TimeOffRequest

DISPATCH_TABLES = [
    ...
    TimeOffRequest.__table__,  # required when available_pool.py queries time_off_requests
]
```

Failing to do this causes `OperationalError: no such table: <name>` across the entire test suite. The error message is clear — the fix is always "import the model and add its `__table__` to the list."

---

## Testing: Use autouse=True for File-Wide Side Effect Patches

When every test in a file needs the same mock (e.g., patching a bot webhook call), use `autouse=True` on the fixture instead of patching per-test:

```python
@pytest.fixture(autouse=True)
def _no_dm(monkeypatch):
    monkeypatch.setattr(
        "app.services.graduate_trainees._send_graduation_dm",
        lambda *args, **kwargs: None,
    )
```

This prevents: (1) tests that forget the patch from making real HTTP calls, (2) test failures in CI where the bot isn't running, (3) accidental Discord noise during local runs. The `autouse=True` approach is preferable to per-test `@patch` when the side effect is always unwanted in the file.

---

## Testing: Use Get-or-Create for Unique-Constrained Rows

When multiple test helper calls might produce the same `(truck_id, date)` pair — and a `UNIQUE constraint` exists on that pair — the second INSERT fails. Use get-or-create:

```python
def make_past_assignment(db, truck, days_ago):
    target = date.today() - timedelta(days=days_ago)
    existing = db.query(TruckAssignment).filter_by(truck_id=truck.id, date=target).first()
    if existing:
        return existing
    ta = TruckAssignment(id=uuid.uuid4(), truck_id=truck.id, date=target)
    db.add(ta)
    db.commit()
    db.refresh(ta)
    return ta
```

This mirrors real-world semantics (multiple employees can ride the same truck on the same day) and keeps test helpers composable.

---

## Testing: Parameterize Time Delta Assertions With Helper Arguments

Analytics that compute median or percentile over time deltas need exact, predictable values. Instead of inserting raw timestamps and doing mental math:

```python
def make_confirmation(db, employee, status="confirmed", response_minutes=10):
    now = datetime.utcnow()
    c = DispatchConfirmation(
        ...
        created_at=now - timedelta(minutes=response_minutes),
        confirmed_at=now if status == "confirmed" else None,
    )
```

Then assertions read as: "median of [5, 10, 15] minutes is 10" — directly matching the `response_minutes` values passed in. No timestamp arithmetic needed in the test body.

---

## Backend: Use `assert_owns_or_privileged` for All Ownership Checks

The pattern "caller must own the resource or hold a privileged role" is very common. Do not inline it:

```python
# BAD — repeated 9 times with minor wording variations
privileged = {"dispatch", "management", "admin"}
if caller.id != employee_id and caller.role not in privileged:
    raise HTTPException(status_code=403, detail="You can only view your own schedule.")
```

Instead, call the helper from `app.api.deps`:

```python
from app.api.deps import assert_owns_or_privileged

assert_owns_or_privileged(caller, employee_id, "schedule")
```

The privileged role set (`_PRIVILEGED_ROLES`) lives only in `deps.py`. Adding a new role is a one-line change there, not a grep-and-replace across every router. The `resource` argument is the human-readable noun used in the 403 message.

---

## Backend: Extract Shared Lookup Logic Into a Private Helper

When two dependency functions share identical multi-step logic (the cognito_sub → discord_id → email → UUID employee lookup chain), extract it into a private `_function_name` in the same module. The two callers then handle only their own post-lookup behavior.

This prevents the two copies from silently diverging when a new lookup step is added (e.g., adding an `email` fallback to one but forgetting the other).

---

## Frontend: Centralize Date and File Utilities

Inline helpers like `getLocalYMD()`, `fileToDataUrl()`, `isoWeekStart()` accumulate duplicates fast. When a third file needs the same helper, extract it to `frontend/src/utils/date.ts` or `frontend/src/utils/file.ts` rather than copying again.

Key utilities:
- `getLocalYMD()` → local YYYY-MM-DD for today (not UTC — avoids off-by-one near midnight)
- `fmtDate(d: Date)` → format any Date as YYYY-MM-DD
- `fileToDataUrl(file)` → FileReader Promise wrapper

Always import from these modules in new pages. Never use `new Date().toISOString().split('T')[0]` — it returns UTC time, which is wrong for users west of UTC.

---

## Frontend: Verify Nullability Before Accepting Shared Types

Before removing an inline interface in favor of a shared type from `api/types.ts`, verify that the shared definition accurately reflects the API shape — especially nullability. Two inaccuracies found during the consolidation pass:

- `WalkerSummary.presence_rate` was typed as `number` in `types.ts` but the API returns `null` when an employee has no route days. The correct type is `number | null`.
- `WalkerSummary.grade` was `string | null` but is a computed enum; the correct type is `'A' | 'B' | 'C' | 'D' | 'F' | null`.

Accepting an overly-wide shared type silently removes compile-time checks that were present in the (more accurate) local definition. Check the SQL query or Pydantic schema, not just the existing TypeScript, before trusting `types.ts`.

---

## Frontend: Always Use `import type` for Interface/Type-Only Imports

The project's `tsconfig.json` enables `verbatimModuleSyntax`. Under this flag, any import that only brings in types (interfaces, type aliases) **must** use `import type { ... }` — the regular `import { ... }` form is a build error.

```typescript
// WRONG — build fails with verbatimModuleSyntax
import { CrewMember } from '../api/types';

// CORRECT
import type { CrewMember } from '../api/types';
```

The Vite dev server (esbuild) is lenient and lets regular imports through at runtime, so the error only surfaces during `npm run build` (`tsc -b` is strict). This means the dev server can appear green while the production build is broken.

**Rule:** Any import from `api/types.ts` (or any file that only exports interfaces/types) must use `import type`. When adding a new import from a types file, always use `import type` from the start.

---

## Frontend: `title` Is Not a Valid Prop on Lucide Icons

Lucide's `LucideProps` type does not include `title`. Passing it causes a TypeScript error at build time:

```
Type '{ className: string; title: string; }' is not assignable to type
'IntrinsicAttributes & Omit<LucideProps, "ref"> & RefAttributes<SVGSVGElement>'.
Property 'title' does not exist on type ...
```

Use `aria-label` instead — it is valid on SVG elements and serves the same accessibility purpose:

```tsx
// WRONG
<CheckCircle2 className="w-4 h-4 text-success" title="Confirmed" />

// CORRECT
<CheckCircle2 className="w-4 h-4 text-success" aria-label="Confirmed" />
```

---

## Frontend: Production Build (`npm run build`) Is the Source of Truth

The Vite dev server uses esbuild, which skips some TypeScript checks. `npm run build` runs `tsc -b` first and is stricter. A page can work perfectly in dev and fail to build in production for reasons the dev server never surfaces:

- `verbatimModuleSyntax` enforcement (`import type` requirement)
- Invalid props on third-party components (`title` on Lucide icons)
- Strict generic inference that esbuild approximates

**Always run `npm run build` after any refactor that touches imports or type definitions** — don't rely on the dev server being error-free as a signal that the build is clean.

---

## 2026-05-02 Auth: Fix the Identity Gap, Don't Route Around the Auth Check

When an endpoint 403'd because `get_caller_employee` couldn't find an `Employee` row for the admin account, the tempting fix was a new endpoint that bypassed employee resolution entirely. That was reverted.

**The lesson:** when you're blocked on auth, the right question is "why can't the auth chain resolve this user?" not "how do I avoid the auth chain?" The existing `record_confirmation` endpoint already had a privileged-role bypass — it just never ran because the caller resolved to `None` first. A five-second DB insert fixed it cleanly. The bulk endpoint traded away audit trail and authorization scope for no real reason.

Before adding a new endpoint to work around a permission error, ask:
1. Does the existing endpoint already have the right logic for this role?
2. Is the problem the endpoint's logic, or is the identity not resolving?
3. What does the new endpoint give up (audit trail, ownership check, scope) compared to fixing the identity?

---

## 2026-05-02 React: Multiple `useConfirm` Instances Per File

When a file has multiple independent sub-components (each with its own `return`), each one needs its own `useConfirm` instance and its own `<ConfirmDialog>` in that return. You cannot share one instance across sub-components because the dialog's `open` state is local to the hook.

The pattern is mechanical — three things must happen together or TypeScript will warn "declared but never read":

```tsx
// 1. Declare the hook at the top of the sub-component function
const { confirmState, confirm, cancelConfirm } = useConfirm();

// 2. Put ConfirmDialog in the sub-component's return
return (
  <div>
    <ConfirmDialog {...confirmState} onCancel={cancelConfirm} />
    {/* rest of UI */}
  </div>
);

// 3. Replace window.confirm with await confirm({...})
const ok = await confirm({ title: '...', message: '...', variant: 'danger' });
if (!ok) return;
```

If any one of the three is missing, TypeScript hints surface immediately. Use them as a checklist.

---

## 2026-05-02 Data Modelling: Use a Dedicated Boolean Over a Sequence Filter for "First of Day"

When querying for the first anchor point of the day for history suggestions, `WHERE sequence = 1` seems equivalent to `WHERE is_initial = true`. It isn't.

`sequence = 1` is a derived property — it's only correct as long as no row with that sequence has been deleted or the sequence hasn't been renumbered. `is_initial` is stamped at insert time and never changes. It survives edge cases cleanly and makes the intent explicit in queries.

**General rule:** if a fact about a row is true at the moment it's created and never changes, stamp it as a boolean at insert time rather than deriving it from relative position in a sequence.

---

## 2026-05-02 API Design: Fetch Only What the UI Can Act On

When a list endpoint returns all records regardless of status, and the UI renders action buttons (Approve, Reject, Resolve) on every row, you will eventually send a state-transition request against a record that is already in a terminal state. The backend correctly rejects it with 404 or 409, but from the user's perspective it looks like a broken button.

The fix is always on the fetch, not the render:

```ts
// Wrong — loads all, shows approve buttons on already-approved items
axiosClient.get('/schedule-change-requests/')

// Right — only actionable items in the pending queue
axiosClient.get('/schedule-change-requests/?status=pending')
```

Keep analytics fetches (for counts, charts) separate and unfiltered. The pending action queue and the analytics dataset serve different purposes — they should be different requests even if they hit the same endpoint.

---

## 2026-05-03 Docker Compose: Use `:?` Not `:-` for Secret Variables

Shell-style variable expansion in docker-compose environment values has two forms:

- `${VAR:-fallback}` — substitutes `fallback` when `VAR` is unset or empty. **Silently.**
- `${VAR:?error message}` — causes the compose process to exit with an error when `VAR` is unset or empty. **Loudly.**

For secrets (`SECRET_KEY`, `INTERNAL_SECRET`, `POSTGRES_PASSWORD`) always use `:?`. A misconfigured environment should fail at startup with a clear message, not silently run with dev-grade credentials that look correct in logs.

Non-sensitive defaults (`POSTGRES_USER`, `POSTGRES_DB`, port numbers) can still use `:-` — the cost of a wrong default is low and the convenience of skipping `.env` setup in a local environment is real.

```yaml
# Wrong — will start with "dev-secret-key-change-in-production" if .env is missing
SECRET_KEY: ${SECRET_KEY:-dev-secret-key-change-in-production}

# Right — hard-fails at startup with a clear message
SECRET_KEY: ${SECRET_KEY:?SECRET_KEY must be set in .env}
```

Pair this with a `.env.example` at the project root that documents every required variable and includes generation instructions (e.g. `python -c "import secrets; print(secrets.token_hex(32))"`). The example file should be committed; `.env` should be gitignored.

---

## 2026-05-03 React: `useRef` for Counters, `useState` for Render-Triggering Flags

When tracking a counter that only matters when it crosses a threshold, use `useRef` instead of `useState`.

```tsx
// Wrong — triggers a re-render on every increment, even when nothing visible changes
const [failCount, setFailCount] = useState(0);

// Right — no re-render until the threshold flag flips
const failCount = useRef(0);
const [isStale, setIsStale] = useState(false);

// In the catch block:
failCount.current += 1;
if (failCount.current >= 3) setIsStale(true);
```

The rule: if a value is only used to compute another value that drives rendering, the intermediate value can be a `useRef`. The flag that actually triggers the render is the `useState`. This avoids N unnecessary re-renders during normal operation (where the counter increments but the threshold is never crossed).

---

## 2026-05-03 Backend: Validate External Input Before Passing to UUID()

`UUID(str(x))` will raise `ValueError` if `x` is not a valid UUID string. This turns a client input error (bad data from Redis, a malformed request body) into an unhandled 500.

Always wrap `UUID()` calls on externally sourced values in a try/except at the point of entry, and return a 422 with a descriptive message:

```python
try:
    employee_uuid = UUID(str(employee_id))
except (ValueError, AttributeError):
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=f"employee_id is not a valid UUID: {employee_id!r}",
    )
# Use employee_uuid everywhere below — never UUID(str(employee_id)) again in this function
```

Store the validated value in a new variable and replace all downstream call sites with it. This also makes it obvious in code review that the value has been validated — `employee_uuid` signals "already checked", `employee_id` signals "raw input".

---

## 2026-05-03 Backend: Role Constants as a Single Source of Truth

Scattering `"driver"`, `"admin"`, `"dispatch"` as bare string literals across 23 files means a typo silently passes — Python won't catch `"dispach"`. A future role rename requires a full-codebase grep with no compiler help.

The fix is a constants module:

```python
# backend/app/services/constants.py
ROLE_DRIVER    = "driver"
ROLE_TRAINER   = "trainer"
ROLE_TRAINEE   = "trainee"
ROLE_WALKER    = "walker"
ROLE_DISPATCH  = "dispatch"
ROLE_MANAGEMENT = "management"
ROLE_ADMIN     = "admin"

OVERSIGHT_ROLES: tuple[str, ...] = ("management", "admin", "dispatch")
```

Import and use these for all ORM-level comparisons (`emp.role == ROLE_TRAINER`, `Employee.role.in_(list(OVERSIGHT_ROLES))`). Leave dict-level comparisons on external JSON data (bot responses, API payloads) as literals — those operate on data you don't control and substituting constants there doesn't prevent bugs at the source.

---

## 2026-05-05 Alembic: Always Run `alembic current` Before Writing `down_revision`

Copying `down_revision` from another migration file (or from a stale branch) creates a hidden multi-head divergence. Alembic will not error on `alembic upgrade head` if the new migration points to a revision the DB has already passed — it just becomes an unreachable head. Symptom: `alembic heads` shows two hashes instead of one.

**Rule:** Before writing a new migration, run `alembic current` (or `docker exec <container> alembic current`) and set `down_revision` to exactly that output. If the DB is at multiple heads, resolve the merge first.

---

## 2026-05-05 Mobile: Step-Gated Lifecycle Screens

For a long ordered workflow (e.g. 19-step driver shift), a single screen with step-gated rendering beats a multi-screen navigator:

- One `useEffect` on mount fetches all shift state and derives a `currentStep: number`.
- Each step component is only rendered when `currentStep >= stepNum`.
- Completed steps collapse to a summary chip (not unmounted — just swapped to a summary view so state is preserved).
- Future steps are hidden entirely, not disabled — drivers should never see UI they can't interact with.

This avoids navigation complexity, back-button confusion, and partial-state bugs across screens. All state lives in one place and refreshes together.

---

## 2026-05-05 Mobile: AsyncStorage for Multi-Entry Drafts

When a user must fill out the same form for N items (e.g. walker ratings, one per crew member) and may not finish in one session:

- Key pattern: `{feature}:{userId}:{date}:{itemId}` — scoped so old drafts never bleed into a new day.
- Draft state is loaded on mount and merged with the live item list.
- On final submit (end-of-day), all drafts are flushed atomically: submit each, then clear keys.
- If a rating was already submitted server-side, skip it silently — idempotent submit is safer than checking first.

Avoid storing drafts in component state alone — a single app kill loses everything. AsyncStorage is the right persistence layer for anything the user hasn't formally submitted.

---

## 2026-05-05 Backend: Nullable Staging Fields Pattern

When adding context-dependent columns (fields that only apply in some cases), make them nullable and enforce the context at the API layer, not the DB layer:

```python
# schema
was_staged: Optional[bool] = None
missing_items: Optional[List[str]] = None

# router — strip fields that don't apply
if data.arrival_type != "loading":
    data.was_staged = None
    data.missing_items = None
```

This keeps the DB schema simple (one table, no polymorphic split) while preventing nonsensical data (a "return" arrival with a staging check).

Migrate incrementally: start with the files that have the most role comparisons (dispatch router, deps) and let others follow over time.

## 2026-05-07 Config: Shell Environment Variables Override `.env`

`pydantic-settings` loads configuration in priority order: shell env vars beat `.env`, which beats class defaults. A `.env` update that appears correct will be silently ignored if the same variable is exported in `~/.zshrc` or `~/.bash_profile`.

**Symptom:** you update `.env`, restart nothing, run a quick Python check, and see the old value.

**Diagnosis:**
```bash
echo $VARIABLE_NAME   # if this returns the old value, the shell wins
```

**Fix:** update the `export` line in the shell config file, not just `.env`. Both must agree.

This caught us during the Cognito pool migration — `AWS_COGNITO_USER_POOL_ID` was exported in `~/.zshrc` with the old pool ID, so every Python import of `settings` returned the stale value despite the correct `.env`.

## 2026-05-07 AWS: PyJWT Access Tokens Have No `aud` Claim

AWS Cognito issues two JWT types with different claim shapes:

| Token type | `aud` claim | Client identity |
|---|---|---|
| ID token | set to app client ID | `aud` |
| Access token | **absent** | `client_id` in payload |

When you call `jwt.decode(token, key, audience=client_id)` on an access token, PyJWT raises `MissingRequiredClaimError("aud")` — **not** `InvalidAudienceError`. A fallback that only catches `InvalidAudienceError` will silently 401 all access tokens.

```python
# Correct — catch both so the fallback fires for either token type
except (jwt.InvalidAudienceError, jwt.MissingRequiredClaimError):
    # access token path: no 'aud', validate 'client_id' manually
    payload = jwt.decode(token, key, algorithms=["RS256"],
                         issuer=COGNITO_ISSUER, options={"verify_aud": False})
    if payload.get("client_id") != settings.aws_cognito_app_client_id:
        raise HTTPException(401, "Wrong client")
```

## 2026-05-07 Architecture: Pass `company_id` Into Services, Don't Read It From State

Service functions that write rows should receive `company_id` as an explicit parameter from the router, not derive it by querying the first related row in the DB.

**Why:** If the query returns an unexpected row (wrong scope, stale session, or the service is called from a test with no rows at all), the derived `company_id` will be wrong and you'll silently write to the wrong tenant's data. An explicit parameter makes the data flow visible and testable.

```python
# Bad — reads from DB state; breaks in tests and in edge cases
def create_assignment(db, truck_id):
    truck = db.query(Truck).filter(Truck.id == truck_id).first()
    row = TruckAssignment(company_id=truck.company_id, ...)  # fragile

# Good — caller passes it in; test can supply SEED_COMPANY_ID
def create_assignment(db, truck_id, company_id: UUID):
    row = TruckAssignment(company_id=company_id, ...)
```

## 2026-05-09 Discord: One Bot Token, Many Guilds

A Discord bot can be a member of multiple guilds simultaneously using a single token. There is no `DISCORD_GUILD_ID` environment variable needed at startup — the bot joins guilds via OAuth invite and then receives events from all of them.

The pattern for multi-tenant Discord:

1. Store guild/channel/role IDs per company in the DB (not in `.env`)
2. On each webhook call from the backend, receive `company_id`, fetch config from DB with a short TTL cache
3. Maintain a `guild_id → company_id` reverse map so `on_member_join` events can identify which tenant a guild belongs to without an extra API call
4. Make every operation a graceful no-op if the company has no Discord config — don't raise, just log and return

```python
cfg = await get_guild_config(company_id)
if not cfg or not cfg.is_configured:
    return  # company has no Discord server yet — skip silently
guild = bot.get_guild(cfg.guild_id)
```

## 2026-05-09 Pydantic Settings: `extra = "ignore"` for Env File Transitions

When removing env vars from a Pydantic `BaseSettings` model while the `.env` file still has those variables (e.g. during a migration to DB-backed config), the default `extra = "forbid"` causes a startup crash: `Extra inputs are not permitted`.

Fix: add `extra = "ignore"` to the inner `Config` class. This silently drops any `.env` key not declared in the model.

```python
class Settings(BaseSettings):
    bot_token: str
    # ... only what the bot still needs

    class Config:
        env_file = ".env"
        extra = "ignore"  # stale DISCORD_* vars are silently dropped
```

## 2026-05-09 React Router: `AnimatePresence mode="wait"` Blocks Navigation

`AnimatePresence mode="wait"` in framer-motion holds the incoming page's render until the outgoing page's exit animation fully completes. In a layout where the incoming route needs to start fetching data immediately, this causes a visible freeze.

- Use `mode="wait"` only when sequential cross-page animations are intentional UX
- Use `mode="popLayout"` or no mode when speed matters and animations are decorative
- In an admin shell layout (sidebar + `<Outlet />`), page transitions add no value — `<Outlet />` alone is correct

Symptom of this bug: clicking a nav link appears to do nothing for 300-500ms before the new page starts rendering.

## 2026-05-09 Debugging: Grep Call Sites When Removing Imports

When removing an import from a file, always check that no call site remains in the component body. An unused import is caught at compile/lint time; a `ReferenceError` on a stale call site only surfaces at runtime when that branch executes.

```bash
# Before saving after removing `useLocation` from imports:
grep -n "useLocation" SuperAdminLayout.tsx
```

If any line other than the import line appears, remove it. This applies to any named import: hooks, utilities, component refs.

## 2026-05-09 Multi-Tenant: `RoleChecker` vs `get_caller_employee`

These two FastAPI dependencies serve different purposes and are NOT interchangeable in a multi-tenant system:

| Dependency | What it validates | Provides `company_id`? |
|---|---|---|
| `RoleChecker(["admin", "management"])` | JWT contains the right Cognito group claim | No |
| `get_caller_employee` | JWT is valid + DB employee row exists | Yes (`caller.company_id`) |

Use `RoleChecker` alone only for endpoints that are intentionally company-agnostic (super admin routes, public lookups). Use `get_caller_employee` for any endpoint that returns or writes company-owned data.

A route that uses `RoleChecker` but queries company-owned data will silently return all companies' data:

```python
# Bug — looks correct but has no company scope
def get_all_employees(
    current_user: dict = Depends(RoleChecker(["admin"])),
    db: Session = Depends(get_db),
):
    return db.query(Employee).all()  # no company_id filter → all tenants

# Fix
def get_all_employees(
    caller: Employee = Depends(get_caller_employee),
    db: Session = Depends(get_db),
):
    return db.query(Employee).filter(Employee.company_id == caller.company_id).all()
```

**Audit rule:** After a multi-tenant migration, grep for `RoleChecker` in routers. Every hit that also queries company-owned tables needs a `company_id` filter added.

## 2026-05-09 Multi-Tenant: End-to-End Isolation Testing Pattern

Unit tests on individual endpoints don't catch cross-tenant leaks — the route code looks correct in isolation. The only reliable check is a live login as a user from each tenant, then asserting that list endpoints return only that tenant's data.

Minimal isolation test script pattern:

```python
# 1. Get a token for tenant B's admin
resp = cognito.initiate_auth(AuthFlow='USER_PASSWORD_AUTH',
    AuthParameters={'USERNAME': username, 'PASSWORD': password}, ...)
token = resp['AuthenticationResult']['AccessToken']
headers = {'Authorization': f'Bearer {token}'}

# 2. Assert list endpoints are scoped
r = requests.get(f'{base}/employees', headers=headers)
assert len(r.json()) == 1  # only tenant B's admin

# 3. Assert cross-tenant reads are blocked
r = requests.get(f'{base}/employees/{tenant_a_employee_id}', headers=headers)
assert r.status_code in (403, 404)

# 4. Assert creates are scoped
r = requests.post(f'{base}/trucks', headers=headers, json={...})
assert r.status_code == 201
# Then verify from a tenant A token that this truck is NOT visible
```

For a fresh company in testing, you may need to:
- Set `is_configured = True` (or seed required config fields) so `require_configured` doesn't block all requests
- Use `admin_set_user_password(Permanent=True)` to set a known password for the test user without triggering a challenge flow

The router always has `caller.company_id` (from `get_caller_employee`) and should forward it explicitly to every service call that writes rows.

## 2026-05-09 Multi-Tenant: Audit Every Query in a Delete-Then-Search Pattern

When a code path deletes a row and then searches for an alternative (the "bump" pattern), both the delete and the search must be company-scoped. It's easy to catch the delete — it's explicit. The search is easy to miss because it looks like a harmless read.

```python
# Bump pattern — both parts must be scoped:
db.delete(existing_member)          # ← scoped via FK from the original query
db.flush()

candidates = db.query(TruckAssignment).filter(
    TruckAssignment.date == date,
    TruckAssignment.company_id == caller.company_id,  # ← must be here too
).all()
```

If the search is unscoped, the system considers other companies' resources as valid fallbacks — a cross-tenant allocation. The affected employee ends up on another tenant's truck with no indication that anything went wrong.

## 2026-05-09 Debugging: "Data Loss" vs "Unavoidable Edge Case with Poor Visibility"

Not all missing rows are bugs. Before calling something data loss, ask:
1. **Was the deletion intentional?** If yes, is there a path that should recreate the row?
2. **Is the no-recovery case genuinely impossible to handle?** If a trainee is bumped and every truck is full, there is no valid slot — deleting the row is the only option.
3. **Is the edge case communicated?** Notifications to oversight staff + the affected employee = correct. A silent 200 with no indication a trainee was lost = bug.

The fix for "unavoidable data loss" is usually better visibility and correct scoping of the decision, not preventing the deletion itself.

## 2026-05-10 SEC-8: CORS Wildcard Hardening — allow_methods and allow_headers (main.py, config.py)

**The finding:** `allow_methods=["*"]` and `allow_headers=["*"]` in `main.py` accepted any HTTP method and any request header from any allowed origin. Acceptable in dev, a misconfiguration in production (OWASP A05:2021 / A02:2025 Security Misconfiguration).

**The fix:** Added `get_cors_methods()` and `get_cors_headers()` to `Settings`, backed by `cors_allow_methods` and `cors_allow_headers` fields. In development they return `["*"]`; in all other environments they return explicit allow-lists:
- Methods: `GET, POST, PATCH, DELETE`
- Headers: `Authorization, Content-Type`

**Critical mistakes made and why they matter:**

*`APP_ENV = "production"` is a class attribute, not a Pydantic field.*
A plain class-level assignment in a Pydantic model is never read from the environment — it's a hardcoded Python value. The correct form is a typed annotation: `app_env: str = "development"`. Pydantic then reads `APP_ENV` from the environment (case-insensitive), and `"development"` is the safe default.

*`cors_allow_methods: str = ["GET","POST","PATCH","DELETE"]` — list assigned to a str field.*
Type annotation and default must match. If the field is `str` (comma-separated), the default must be a `str`: `"GET,POST,PATCH,DELETE"`. Pydantic v2 may coerce or raise at startup if they conflict.

*`allow_credentials=True` with `allow_origins=["*"]` is rejected by browsers.*
CORS spec forbids credentials (cookies, Authorization headers) with a wildcard origin. If you return `["*"]` from `get_cors_origins()` in dev while `allow_credentials=True`, browsers will block all credentialed requests. The origins helper must always return explicit origins, never a wildcard.

**The environment pattern:** All conditional behavior based on environment should flow through `self.app_env` — one Pydantic field, one source of truth, overridable via `APP_ENV` environment variable, testable in CI with `APP_ENV: test`.

## 2026-05-10 SEC-7: EmailStr for Email Format Validation (employee.py)

**The finding:** `email` fields on `EmployeeCreate`, `EmployeeUpdate`, `EmployeeResponse`, and `BulkImportRow` were typed as plain `str`. A caller could send `"not-an-email"` and Pydantic would accept it, pass it through the dependency chain, and eventually fail with an opaque Cognito 400 or store a malformed address in the database.

**The fix:**
```python
# Before
from pydantic import BaseModel, field_validator
email: str

# After
from pydantic import BaseModel, field_validator, EmailStr
email: EmailStr           # required field
email: Optional[EmailStr] # optional field (EmployeeUpdate)
```

`pydantic[email]` is already in `requirements.txt` — `EmailStr` is available with no new dependency.

**Why it matters:** Format errors should be caught at the schema boundary and returned as HTTP 422 with a clear message (`"value is not a valid email address"`), not discovered later as a Cognito 400 or a malformed row in the database. The earlier the rejection, the less code has to handle the bad state.

**Response schemas too:** `EmployeeResponse.email` and `BulkImportResult.email` were also updated. Even data coming *out* of the database gets validated against RFC 5322 before serialization — if somehow a malformed address got into the DB, the response would surface it as a validation error rather than silently returning garbage.

**`Optional[EmailStr]` on update schemas:** Works correctly — `None` (field omitted) is valid, but a provided value must be a properly formatted email. This is the correct pattern for any optional field with format constraints.

## 2026-05-10 SEC-6: Adding Length Constraints to Free-Text Fields (truck.py)

**The finding:** `TruckCreate.name` and `TruckUpdate.name` had no length constraints — any string length was accepted. Every other free-text field in the codebase used `Field()` with `min_length` and `max_length`. An unbounded string field in Postgres is stored as `TEXT` or `VARCHAR` without enforcement — a 10MB truck name would be accepted, stored, and potentially crash rendering downstream.

**The fix:**
```python
# TruckCreate — required field
name: str = Field(..., min_length=1, max_length=100)

# TruckUpdate — optional field (PATCH semantics)
name: Optional[str] = Field(None, min_length=1, max_length=100)
```

**Critical distinction — `...` vs `None` as the Field default:**
- `Field(...)` — Ellipsis means required. The field must be present in the payload.
- `Field(None)` — None means optional. The field may be omitted entirely.

`Optional[str]` and `Field(...)` contradict each other. `Optional` declares that `None` is a valid value; `...` declares that a value is required. Pydantic resolves this by making the field required — which breaks PATCH semantics. An update schema where every field is optional must use `Field(None, ...)` not `Field(..., ...)`.

**How to spot this in future:** Every Create schema field that is required uses `...`. Every Update schema field uses `None`. They are never mixed on the same field.

## 2026-05-10 SEC-5: Replacing Unconstrained `str` Fields with `Literal` Allow Lists (feedback.py)

**The finding:** `FeedbackBase.type`, `FeedbackResponse.status`, and `FeedbackStatusUpdate.status` were all typed as plain `str`. Pydantic accepted any string — `"<script>alert(1)</script>"`, `"'; DROP TABLE--"`, anything — without complaint. The router was doing manual validation with `if payload.status not in _VALID_STATUSES` after the fact, which is the wrong layer.

**OWASP mapping:** A03:2021 Injection / A05:2021 Security Misconfiguration. Input that should be rejected at the boundary is instead accepted and passed into business logic.

**The fix — `Literal` as a server-side allow list:**

```python
# Before — accepts any string silently
type: str = Field(..., description="Type of feedback: bug, feature_request, general")
status: str

# After — Pydantic rejects anything not in the set at deserialization time
from typing import Literal

type: Literal["bug", "feature_request", "general"] = Field(...)
status: Literal["new", "in_progress", "resolved"]
```

**Common mistake — one string vs. multiple arguments:**
`Literal["bug, feature_request, general"]` is wrong — that's one valid value: the literal string `"bug, feature_request, general"` including commas and spaces. `Literal` is variadic; each valid value is a separate quoted argument separated by commas *outside* the quotes.

**Why the fix works:** `Literal` turns Pydantic into a server-side allow-list enforcer. The moment JSON is deserialized, any value not in the set raises `ValidationError` and returns HTTP 422 — before the route handler, before the database, before any business logic runs. The router's manual `if payload.status not in _VALID_STATUSES` check becomes redundant (but harmless).

**How to spot this in future:** Any `str` field whose docstring or description names a finite set of valid values is a candidate for `Literal`. The description is the allow-list — it just hasn't been enforced yet. Also: when applying `Literal` to a field that appears across a class hierarchy (`FeedbackBase`, `FeedbackResponse`, `FeedbackStatusUpdate` all had `status` or `type`), check every class — each needs its own correct value set, not a copy/paste of another class's values.

## 2026-05-10 Secure App Development: OWASP Top 10 and What Changed in 2025

The OWASP Top 10 is a ranked list of the most common web application security risks, updated every few years. Two editions matter right now:

**2021 edition** (what most textbooks teach):
1. Broken Access Control, 2. Cryptographic Failures, 3. Injection, 4. Insecure Design, 5. Security Misconfiguration, 6. Vulnerable & Outdated Components, 7. Identification & Auth Failures, 8. Software & Data Integrity Failures, 9. Logging & Monitoring Failures, 10. SSRF

**2025 edition** (current):
1. Broken Access Control (+ SSRF folded in), 2. Security Misconfiguration (↑3), 3. Software Supply Chain Failures (NEW), 4. Cryptographic Failures, 5. Injection, 6. Insecure Design, 7. Authentication Failures, 8. Software or Data Integrity Failures, 9. Security Logging & Alerting Failures, 10. Mishandling of Exceptional Conditions (NEW)

Key shifts: supply-chain risk (npm packages, pip packages with CVEs) is now A03. SSRF is no longer standalone — it's considered an access control failure. Injection dropped because modern frameworks (SQLAlchemy ORM, Pydantic) make it much harder to accidentally introduce.

## 2026-05-10 Secure App Development: Input Validation — Allow Lists vs. Block Lists

**Block list (deny list):** reject known bad values, allow everything else. Default-allow.
**Allow list (white list):** only accept known good values, reject everything else. Default-deny.

Prefer allow lists. Block lists fail open — the moment an attacker uses a value you didn't think to block, it gets through. You cannot enumerate all bad values, but you can enumerate all good ones.

In Pydantic v2, an allow list on a string field is expressed with `Literal`:

```python
# Block list thinking (bad — misses infinite variants):
type: str  # "hope" the caller sends "bug", "feature_request", or "general"

# Allow list thinking (correct — rejects everything not on the list):
from typing import Literal
type: Literal["bug", "feature_request", "general"]
```

When `type` is `Literal`, Pydantic raises `ValidationError` on any value not in the set — before the value ever reaches the router, the database, or any business logic.

**Server-side vs. client-side validation:**
- Client-side (JavaScript, HTML5 attributes): runs in the browser before the request is sent. Good for UX speed. Useless as a security boundary — anyone can disable JS or send a raw HTTP request with `curl`.
- Server-side (Pydantic schemas, FastAPI): runs on the server after the request arrives. The only validation that counts for security. Always validate on the server. Anything the client sends is untrusted.

## 2026-05-10 Secure App Development: What Tests Are and How to Build on Them

A test suite has two layers:

**Unit tests** — test one function in isolation. Control all inputs, assert on the output of that one function only. Fast, deterministic, no database required.

**Integration tests** — test that multiple components wire together correctly. In this project, `test_run_dispatch.py` verifies that the full dispatch pipeline produces valid DB rows, not just in-memory output.

**The pattern every test follows:**
```
ARRANGE — set up the minimum data the test needs
ACT     — call the one thing you're testing
ASSERT  — check exactly the one behavior that should have changed
```

**Testing for rejection, not just acceptance:**
The dangerous bugs are silent acceptances — inputs that should be rejected but aren't. A test that catches a missing allow-list guard does the opposite of a happy-path test:

```python
import pytest
from pydantic import ValidationError
from app.schemas.feedback import FeedbackCreate

def test_invalid_feedback_type_is_rejected():
    # Before fix: this succeeds silently — the bug
    # After fix: this raises ValidationError — the correct behavior
    with pytest.raises(ValidationError):
        FeedbackCreate(type="<script>alert(1)</script>", message="hello")
```

The `with pytest.raises(ValidationError):` block asserts that the exception *must* be raised. If it isn't — if Pydantic accepts the value — the test fails, catching the bug.

**What the current test suite covers and what it doesn't:**
- Covered: all dispatch service logic (weights, assignment, graduation, warnings, persistence)
- Not covered: the API layer — HTTP status codes, role guards, tenant isolation, input validation on endpoints

All of the OWASP security findings from the rectification plan live in the API layer and require `TestClient` tests to verify.

## 2026-05-10 Secure App Development: GitHub Actions CI — What It Is and Why It Matters

CI (Continuous Integration) means automatically running your test suite every time code is pushed. Without it, broken code can sit in `master` silently. With it, every push gets verified within ~60 seconds.

**The workflow file** lives at `.github/workflows/ci.yml`. GitHub reads it automatically — no setup beyond the file existing. Structure:

```yaml
on: [push, pull_request]   # when to trigger
jobs:
  test:
    runs-on: ubuntu-latest  # what machine GitHub provides
    steps:                  # commands to run in order
      - uses: actions/checkout@v4       # download the repo
      - uses: actions/setup-python@v5   # install Python
      - run: pip install -r requirements.txt
      - run: python -m pytest tests/ -v --tb=short
```

**Why SQLite in CI instead of Postgres:** The test `conftest.py` uses `sqlite:///:memory:` — a database that lives only in RAM and disappears after the test run. SQLite is built into Python, so no external service container is needed. This makes CI faster and simpler. The trade-off: SQLite doesn't support PostgreSQL-specific types (JSONB), so models that use those can't be tested this way.

**Secrets vs. hardcoded values:** Never put real credentials in `ci.yml` — the file is committed to the repo and visible to anyone with read access, permanently including git history. GitHub provides an encrypted secrets store (Settings → Secrets and variables → Actions). Reference them as `${{ secrets.MY_SECRET }}`. GitHub injects the value at runtime and redacts it from logs.

**Fake env vars in CI:** The `Settings` class reads environment variables at import time. Tests need those variables to exist or `Settings()` raises a validation error before any test runs. Fake values like `us-east-1_TESTPOOL` satisfy the type check without granting real AWS access.

**Failure notification:** GitHub emails you automatically when a workflow you triggered fails. No configuration needed. The push that broke the build gets a red ✗ on GitHub; you get an email. Future pushes that fix it get a green ✓.

## 2026-05-10 Secure App Development: Environments and Why They Matter

Secure development uses four environments in sequence: Dev → Test → Stage → Prod.

- **Dev:** where you write and debug code. Risks here don't touch users.
- **Test:** automated tests run here. Verifies the app against its spec.
- **Stage:** mirrors production exactly. Final dry-run before release. Migration scripts, config changes, and install procedures are validated here first.
- **Prod:** live. Real users. Changes only arrive here after passing all prior stages.

This project currently collapses all four into one `docker-compose.yml`. A developer running `docker-compose up` locally uses the same topology as production would. The risk: a misconfigured env var in dev could silently point at a prod database if the stages aren't isolated by separate config files and network boundaries.

**Provisioning vs. deprovisioning:**
- Provisioning: moving an app to a production environment and configuring it — creating users, setting permissions, adjusting appearance.
- Deprovisioning: removing access. Also applies to employees — when someone leaves, their Cognito account must be disabled and tokens revoked (`AdminDisableUser` + `AdminUserGlobalSignOut`). This project does this correctly in `employees.py` via `_cognito_revoke_access`.

**Horizontal vs. vertical scaling:**
- Vertical: add more CPU/RAM to one server. Simple, but hits a hardware ceiling.
- Horizontal: add more server instances behind a load balancer. No ceiling, but each instance must be stateless. This project's in-process JWKS cache (`security.py`) is a stateful component that breaks horizontal scaling — one fix is moving it to Redis, which is already a dependency.

## 2026-05-10 Secure App Development: Code Review — Static vs. Dynamic Analysis

**Static analysis:** examines source code without running it. Catches style issues, deprecated APIs, dead code, common bug patterns. Tools: Ruff (linter), Mypy/Pyright (type checker), Bandit (security patterns). Runs fast — no server needed.

**Dynamic analysis:** examines code while it runs, with test inputs. Catches runtime bugs — crashes, memory issues, unexpected behavior under real conditions. Tools: pytest, profilers, fuzzers.

**Fuzzing:** feeds random and invalid data into the system to find edge cases developers never imagined. A fuzzer for a web API sends long strings, special characters, negative numbers, and malformed payloads to every input field. The goal: make the server return a 5xx instead of a clean 4xx, revealing that the input wasn't handled gracefully.

## 2026-05-10 Secure App Development: SEC-1 — Multi-Tenant Isolation in Routers

### The problem: `RoleChecker` is not a tenant guard

FastAPI routes are protected in two separate layers:

1. **Authentication + Role** — handled by `RoleChecker(["admin"])`, which verifies the JWT and confirms the caller is an admin. It returns a `dict` (the decoded JWT claims). It has no `company_id`.
2. **Tenant scope** — handled by `get_caller_employee`, which looks up the caller's row in the `employees` table and returns an `Employee` object containing `company_id`.

The critical mistake in `feedback.py` was that `GET /feedback/` and `PATCH /feedback/{id}/status` used `RoleChecker` for access control but did not add `get_caller_employee` as a dependency. The result: an admin at Company A could read and modify feedback records from Company B — the query had no `WHERE company_id = ?` clause.

```python
# BEFORE — admin check, no tenant scope
_: dict = Depends(allow_admin),
db: Session = Depends(get_db),

# AFTER — admin check + tenant scope
_: dict = Depends(allow_admin),
caller: Employee = Depends(get_caller_employee),
db: Session = Depends(get_db),
```

### The fix: filter every query by caller.company_id

Three queries needed the filter added:

```python
# Feedback list
db.query(Feedback)
    .order_by(Feedback.created_at.desc())
    .filter(Feedback.company_id == caller.company_id)

# Employee name lookup (secondary query within the same endpoint)
db.query(Employee.id, Employee.name).filter(
    Employee.id.in_(emp_ids),
    Employee.company_id == caller.company_id,
)

# Status update — find the record before mutating it
db.query(Feedback).filter(
    Feedback.id == feedback_id,
    Feedback.company_id == caller.company_id,
).first()
```

If the record doesn't exist *for this tenant*, the query returns `None` and the route raises 404. This is the correct behavior — it prevents an admin from patching a record in another tenant's space, and gives no information about whether that record even exists.

### How to think about this going forward

Every query in a multi-tenant system must ask: "Does this query scope to the caller's company?" A query that omits `company_id` is almost always a bug. The right checklist when writing a new endpoint:

1. What authentication does this need? (JWT — `get_current_user`)
2. What roles are allowed? (`RoleChecker`)
3. Do I need the caller's `company_id`? (if yes, add `get_caller_employee`)
4. Does every query filter on `company_id`?
5. For mutations: does the "find the record" query include `company_id`? If not, you can mutate another tenant's data.

OWASP 2021 A01 — Broken Access Control: "Access control enforces policy such that users cannot act outside of their intended permissions." Querying across tenant boundaries is a broken access control finding even if the caller is authenticated and even if they have the correct role — role is orthogonal to tenant scope.

## 2026-05-10 Secure App Development: SEC-2 — Missing Role Guard on a Read Endpoint

### The problem: authenticated ≠ authorized

`GET /dispatch/unavailable-staff/{date}` had `get_caller_employee` in its signature (tenant scope — correct) but was missing `allow_dispatch_mgmt` (role enforcement). Any employee with a valid JWT — including trainees and walkers — could call it and receive contact information (name, Discord ID, phone number) for every colleague who had time off on a given date.

Authentication (you have a valid token) is not the same as authorization (you are allowed to do this). The endpoint was authenticated but not authorized.

### The fix: add the role dependency

```python
# BEFORE
def get_unavailable_staff_for_date(
    dispatch_date: date,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    roles: List[str] = Query(...),
):

# AFTER
def get_unavailable_staff_for_date(
    dispatch_date: date,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_dispatch_mgmt),
    roles: List[str] = Query(...),
):
```

`allow_dispatch_mgmt = RoleChecker([ROLE_DISPATCH, ROLE_ADMIN])` was already defined at the top of the file — it just wasn't wired into this endpoint. The `_` variable name is the FastAPI convention for a dependency used only for its side effect (raising 403 if unauthorized) when you don't need the return value.

### The bonus fix: missing company_id on a mutation query

During this pass, a second issue was found and corrected in the same file: the "does dispatch already exist today?" check inside `run_dispatch` was querying `TruckAssignment` without a `company_id` filter. An admin at Company A could have accidentally blocked Company B's dispatch run if both tried to dispatch on the same date. The fix is the same pattern applied throughout — add `TruckAssignment.company_id == caller.company_id` to the filter.

### How to think about read endpoints

Read endpoints are just as dangerous as write endpoints when the data is sensitive. Contact information, schedules, time-off records, and availability data are all PII-adjacent. The threat model for a read endpoint: "who should NOT be able to see this, and what happens if they can?" For `unavailable-staff`, a disgruntled employee could use the endpoint to target colleagues who are out, or to probe organizational structure. Role guards on reads are not optional.

## 2026-05-10 Secure App Development: SEC-3 — Dual Source of Truth for Roles

### The design risk

This system checks roles in two different places using two different sources:

**`RoleChecker`** ([deps.py:243](backend/app/api/deps.py#L243)) reads from the **JWT**:
```python
user_groups = user.get("cognito_groups", [])
```
Cognito embeds group membership into the token at login time. The token is valid for its full TTL (typically 1 hour) regardless of what happens in Cognito afterward.

**`assert_owns_or_privileged`** ([deps.py:304](backend/app/api/deps.py#L304)) reads from the **database**:
```python
caller.role not in _PRIVILEGED_ROLES
```
`caller` is an `Employee` ORM object fetched fresh on every request. It reflects the current state of the `Employee.role` column.

### What happens on a demotion

An admin is removed from the `admin` Cognito group and their `Employee.role` is updated to `driver`:

| Dependency | Source | Sees after demotion |
|---|---|---|
| `RoleChecker` | JWT (minted at login) | `admin` — until the token expires |
| `assert_owns_or_privileged` | `Employee.role` in DB | `driver` — immediately |

For up to one hour after demotion, `RoleChecker`-guarded endpoints still accept the former admin. Endpoints guarded by `assert_owns_or_privileged` block them immediately.

### What happens on a promotion

A driver is added to the `admin` Cognito group but their `Employee.role` column is not updated:

| Dependency | Source | Sees after promotion |
|---|---|---|
| `RoleChecker` | JWT (next login) | `admin` |
| `assert_owns_or_privileged` | `Employee.role` in DB | `driver` |

Less dangerous — the employee gets blocked on ownership checks — but confusing and a sign the two sources are drifting.

### Why this is not fixed today

The JWT TTL window (≤1 hour) is an accepted trade-off in token-based auth systems. The alternative — revocation lists or very short-lived tokens — adds significant infrastructure complexity. The risk is documented so that:
1. Role changes must update **both** Cognito groups and `Employee.role` in the same operation.
2. Emergency demotions (e.g., a terminated employee) must also call `AdminUserGlobalSignOut` in Cognito to invalidate existing tokens immediately — the project already has `_cognito_revoke_access` in `employees.py` for exactly this reason.
3. Future developers adding new role checks must consciously choose which source to read from and document why.

### The general principle

When the same concept (role, permission, status) is stored in two places, they will eventually diverge. The system must either: (a) have one authoritative source and derive the other, or (b) document the window of inconsistency and have a procedure for emergency sync.

### The fix: make RoleChecker DB-authoritative

Rather than refactoring 17 call sites to pass the JWT dict into `assert_owns_or_privileged`, we made `RoleChecker` consistent with it — both now read `Employee.role` from the database as the authoritative source.

The updated `RoleChecker.__call__` in [deps.py:243](backend/app/api/deps.py#L243):

```python
def __call__(self, user: dict = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    from app.models.employee import Employee

    sub   = user.get("id", "")
    email = user.get("email", "")

    employee = None
    if sub:
        employee = db.query(Employee).filter(Employee.cognito_sub == sub).first()
    if not employee and email:
        employee = db.query(Employee).filter(Employee.email == email).first()

    if employee:
        # DB role is authoritative — JWT claim may be stale after a role change
        if employee.role not in self.allowed_roles:
            raise HTTPException(status_code=403, detail="Operation not permitted.")
    else:
        # No employee row (super admin or platform account) — fall back to JWT groups
        if not any(role in user.get("cognito_groups", []) for role in self.allowed_roles):
            raise HTTPException(status_code=403, detail="Operation not permitted.")

    return user
```

**Why this approach over the alternative:** Making `assert_owns_or_privileged` read from the JWT instead would have required passing a second parameter to all 17 call sites and made more of the system JWT-dependent — the weaker source. Making `RoleChecker` DB-authoritative achieves consistency in one place with zero changes at call sites.

**Super admin fallback:** Platform-level accounts have no `Employee` row. The `else` branch preserves the original JWT-group check for those callers. No super admin functionality is broken.

**Performance:** `RoleChecker`-guarded endpoints that also use `get_caller_employee` already pay one DB query. `RoleChecker` now adds one more (sub lookup). The fast path (`cognito_sub` is indexed) makes this negligible. At enterprise scale this is one indexed read per request on admin-only endpoints — acceptable.

**What this closes:** A demoted admin whose JWT still carries the old `cognito_groups` claim is now blocked immediately by `RoleChecker` — the DB says `driver`, the check fails. The JWT TTL window is eliminated for all role-guarded endpoints. `AdminUserGlobalSignOut` is still best practice for terminations (forces re-authentication entirely) but is no longer the only line of defense.

## 2026-05-11 Secure App Development: SEC-4 — SSRF via Unvalidated Internal URL

### The vulnerability

SSRF (Server-Side Request Forgery) — OWASP 2021 A10 — occurs when a server makes an outbound HTTP request to a URL that an attacker can influence. In `_send_discord_invite`, the URL was read directly from the environment:

```python
bot_url = os.environ.get("BOT_INTERNAL_URL", "http://bot:8001")
```

If `BOT_INTERNAL_URL` is misconfigured or injected (e.g., via a compromised `.env` file, a misconfigured deployment, or a supply-chain attack), the server would make a POST request to any URL — including `http://169.254.169.254/latest/meta-data/`, the AWS Instance Metadata Service. That endpoint returns temporary IAM credentials, which an attacker can use to take over the entire AWS account.

### Three problems with `os.environ.get` in application code

1. **Hidden contract:** A developer cloning the repo has no idea `BOT_INTERNAL_URL` is required until the code hits that line at runtime and fails mid-request.
2. **Untestable:** Unit tests must mock the global environment (`os.environ`) rather than passing a config object.
3. **No type safety:** `os.environ` always returns a string or `None`. Pydantic can't validate, cast, or fail-fast on a value it doesn't know about.

### The fix: move to Settings with a field_validator

**[config.py](backend/app/core/config.py)** — added field and validator:

```python
_ALLOWED_BOT_HOSTS = {"bot", "localhost", "127.0.0.1"}

class Settings(BaseSettings):
    bot_internal_url: str = "http://bot:8001"

    @field_validator("bot_internal_url")
    @classmethod
    def validate_bot_url(cls, v: str) -> str:
        parsed = urlparse(v)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError(f"BOT_INTERNAL_URL scheme must be http or https, got: {parsed.scheme!r}")
        if parsed.hostname not in _ALLOWED_BOT_HOSTS:
            raise ValueError(f"BOT_INTERNAL_URL hostname {parsed.hostname!r} is not in the allowed list")
        return v
```

**[deps.py](backend/app/api/deps.py)** — replaced `os.environ.get` with settings:

```python
bot_url = settings.bot_internal_url
secret  = settings.internal_secret
```

### Why hostname whitelisting over IP filtering

IP filtering (block `169.254.0.0/16`, `10.0.0.0/8`, etc.) is fragile — an attacker can use DNS rebinding to resolve a whitelisted hostname to a blocked IP after the check passes. Hostname whitelisting rejects anything not in the allow-list outright. At startup, before any request is ever served.

`_ALLOWED_BOT_HOSTS = {"bot", "localhost", "127.0.0.1"}` — `"bot"` is the Docker Compose service name; `"localhost"` and `"127.0.0.1"` cover local development. Any other hostname causes a `ValidationError` at startup — the app never boots.

### The general rule

Every outbound URL a server makes a request to must be: (1) defined in `Settings` so it's validated at startup, (2) restricted to a known-good allow-list of hosts, and (3) scheme-checked to prevent `file://` or `gopher://` abuse. Never read URLs from `os.environ` directly in application code.

**Dead code** is code that never runs or whose result is never used. It wastes memory, can hide bugs, and is a target for attackers (dead code paths often skip validation because "nobody reaches them").

## 2026-05-11 Secure App Development: SEC-9 — Dead Code Removal

Seven one-shot dev scripts were committed to `backend/` and never removed:

- `add_trainees.py`, `add_one_more_trainee.py` — seed trainee records directly into the DB
- `add_trainee_fields.py`, `alter_db.py` — run raw `ALTER TABLE` SQL against the live engine
- `create_dispatch.py`, `create_fake_dispatch.py` — manually create dispatch records
- `seed.py` — hardcoded test user data with real-looking UUIDs

**Why these are a security risk, not just clutter:**

1. **No auth, no audit trail.** Every script calls `SessionLocal()` directly and writes to the database as a superuser. There is no JWT check, no role check, no company_id scope, and no audit log entry. Anyone who can run Python in the container can manipulate production data with zero trace.

2. **Hardcoded identifiers.** `seed.py` contained hardcoded UUIDs and Discord IDs that map to real test accounts. Committed identifiers are permanent in git history — even after deletion, they're recoverable. (The deletion removes the attack surface going forward; the history is a separate concern for a secret-scanning tool like `git-secrets` or `trufflehog`.)

3. **Schema migration bypass.** `alter_db.py` and `add_trainee_fields.py` run raw DDL directly against the engine, bypassing Alembic entirely. If run against production they would modify the schema with no migration record, no rollback path, and no review.

**The rule:** one-shot scripts belong in a `scripts/` directory (already present in this repo) with a clear README, or they get deleted after use. Never leave them in the package root where they look like application code. Alembic handles schema changes; fixtures or management commands handle seed data.

## 2026-05-11 Secure App Development: ENV-1 — Multi-Environment Docker Compose Separation

### What Docker Compose is and why one file is a problem

Docker runs your application in **containers** — isolated processes that each have their own filesystem and network. `docker-compose.yml` is a recipe that tells Docker what containers to create, how to build them, and how they communicate.

The original file had dev-only settings baked in at the top level:
- `./backend:/app` — a **volume mount** that replaces the container's `/app` directory with your local source code on disk. This enables hot reload in dev. In production it's dangerous: anyone who can write to that directory on the server changes what the container runs, bypassing the entire build/review/deploy pipeline.
- `--reload` on uvicorn — watches the filesystem and restarts on changes. In production: wastes CPU, makes the server non-deterministic, signals dev mode to attackers.
- `celery worker --beat` — runs the Celery scheduler inside the same process as the worker. If the worker crashes and restarts, the scheduler restarts too, potentially double-firing scheduled jobs.

### The three-file structure

Docker Compose has a built-in merge system. When you run `docker-compose up` it automatically loads two files in order:
1. `docker-compose.yml` — the base (environment-neutral service definitions)
2. `docker-compose.override.yml` — dev patches, auto-loaded with no flags needed

For production you name the files explicitly:
```bash
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

The override files only specify keys that change — everything else is inherited from the base. Docker Compose merges them.

### `docker-compose.yml` (base)

Defines all services, their images, ports, environment variables, and health-check dependencies. No volume mounts. No `--reload`. No `--beat`. Environment-neutral — safe to run anywhere.

### `docker-compose.override.yml` (dev, auto-loaded)

Patches three things on top of the base:
- `./backend:/app` and `~/.aws` volume mounts on `backend` and `celery_worker` — enables hot reload
- `--reload` on uvicorn — restarts on file save
- `--beat` back on celery — scheduler bundled with worker (acceptable in dev)

A developer runs `docker-compose up` with no flags and gets all of this automatically.

### `docker-compose.prod.yml` (production, explicit)

Patches for production:
- `APP_ENV=production` on every Python service — triggers the `INTERNAL_SECRET` and `cors_origins` startup guards in `config.py`
- `--workers 4` on uvicorn — multiple processes for concurrent requests (`--reload` and `--workers` are mutually exclusive)
- No volume mounts — the image contains the code built at deploy time
- **Splits celery into two separate services** (ENV-5):
  - `celery_worker`: runs `celery worker` — processes tasks
  - `celery_beat`: runs `celery beat` — fires scheduled jobs
  - If the worker crashes, the beat schedule is unaffected. If beat crashes, workers keep processing — nothing is lost.

### ENV-5: Why split celery beat from the worker

`celery worker --beat` in one process means one crash affects both. In production with horizontal scaling (multiple worker containers), running `--beat` on every worker causes every worker to fire the same scheduled jobs simultaneously — N workers = N copies of every scheduled job running at once. Beat must run in exactly one container. Separating it into `celery_beat` makes that explicit and enforced.

### YAML indentation rules

YAML indentation is structural — wrong indentation means wrong meaning, not a syntax error you can see. Every property of a service must be indented exactly two spaces inside the service name. A property at the wrong level either becomes a top-level key (parse error) or is silently ignored. Always validate compose files with `docker-compose config` before deploying.

## 2026-05-11 Secure App Development: CI-4 — Structured Log Shipping to CloudWatch

### Why plain text logs are insufficient in production

When a container restarts, its stdout is gone. With `docker-compose up`, uvicorn writes plain text to the terminal. In production with multiple workers and container restarts, there is no durable record of what happened. A 500 error that occurred at 2am on a Tuesday is unrecoverable.

**CloudWatch Logs** is AWS's managed log aggregation service. Logs are shipped there continuously, stored durably (with a configurable retention policy), and queryable via CloudWatch Insights. Even if a container crashes and is replaced, the logs are already in CloudWatch.

### Two changes required

**1. Structured JSON logging in the application (`main.py`)**

Plain text logs (`INFO: 127.0.0.1 - GET /health 200`) can be stored in CloudWatch but can't be queried efficiently. Structured JSON logs (`{"level":"INFO","message":"...","time":"..."}`) allow CloudWatch Insights to run queries like:

```sql
fields @timestamp, message
| filter level = "ERROR"
| sort @timestamp desc
| limit 20
```

Added `_JsonFormatter` to `main.py` that emits one JSON object per log record:

```python
class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps({
            "level":   record.levelname,
            "logger":  record.name,
            "message": record.getMessage(),
            "time":    self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
        })
```

`_configure_logging()` installs this formatter on the root logger at startup — every `logging.getLogger(__name__)` call in the codebase automatically uses it.

**2. CloudWatch log driver in `docker-compose.prod.yml`**

Docker's `awslogs` log driver ships container stdout directly to CloudWatch without any additional agent. Added as a YAML anchor (`x-cloudwatch-logging`) shared across all three Python services (`backend`, `celery_worker`, `celery_beat`):

```yaml
x-cloudwatch-logging: &cloudwatch-logging
  driver: awslogs
  options:
    awslogs-group: ${CLOUDWATCH_LOG_GROUP:-/asheflow/production}
    awslogs-region: ${AWS_REGION:-us-east-1}
    awslogs-stream-prefix: asheflow
```

Each service references it with `logging: *cloudwatch-logging`. The `*` is YAML anchor syntax — it pastes the full `&cloudwatch-logging` block in place, avoiding duplication.

### Cost

CloudWatch charges $0.50/GB ingested and $0.03/GB/month stored. At this project's scale the free tier (5 GB ingested, 5 GB stored per month) covers everything. Set a log retention policy (e.g. 30 days) in the AWS console to prevent unbounded storage growth.

### Prerequisites for production

- The EC2 instance or ECS task needs an IAM role with `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents` permissions
- `CLOUDWATCH_LOG_GROUP` set in `.env` (e.g. `/asheflow/production`)
- `AWS_REGION` set to the region where the log group should live

## 2026-05-11 Secure App Development: CI-5 — Audit Log Coverage for Sensitive Endpoints

### What the audit log is and why gaps matter

`write_audit()` in `app/services/audit.py` appends an immutable `AuditLog` row to the database inside the same transaction as the state change it records. It captures: who did it (`actor_id`), what company (`company_id`), what action (`action_type`), which record (`target_table` + `target_id`), and what changed (`before`/`after` snapshots).

Without an audit row, there is no record of the action ever happening. If an admin demotes a trainer and that trainer later disputes it, there is no evidence. If an account is deactivated and the employee claims it was unauthorized, there is nothing to investigate.

### The gaps found

`grep write_audit backend/app/routers/` revealed that only five endpoints called `write_audit` out of dozens of mutating endpoints. The highest-severity gaps were all in `employees.py`:

| Endpoint | Action | Gap |
|---|---|---|
| `POST /{id}/promote` | Walker → Trainer role change | No audit row |
| `POST /{id}/demote` | Trainer → Walker role change | No audit row |
| `PUT /{id}/deactivate` | Account deactivation + Cognito revocation | No audit row |
| `PUT /{id}/reactivate` | Account reactivation + Cognito re-enable | No audit row |

Role changes are the most critical missing entries — directly connected to SEC-3 (the dual-source-of-truth finding). `RoleChecker` now reads `Employee.role` from the DB as authoritative. A role change with no audit row means there is no record of when the role changed, who changed it, or what it was before.

### The fix

Added `write_audit()` to all four endpoints, placed just before `db.commit()` so the audit row is part of the same transaction as the state change:

```python
write_audit(
    db,
    actor_id=str(caller.id),
    company_id=str(caller.company_id),
    action_type="employee.promoted",   # or demoted / deactivated / reactivated
    target_table="employees",
    target_id=str(employee_id),
    before={"role": old_role},
    after={"role": "trainer"},
)
db.commit()
```

The `before`/`after` snapshots record the specific fields that changed — not the entire row. For role changes, that's `{"role": "walker"}` → `{"role": "trainer"}`. For activation changes, that's `{"is_active": True}` → `{"is_active": False}`.

### The transactional guarantee

`write_audit()` does **not** commit — it only calls `db.add()`. The caller commits. This means: if the commit fails for any reason, the audit row is also rolled back. You never get a state change without an audit row, and you never get an audit row without the state change. They're atomic.

### How to audit for coverage going forward

```bash
grep -rn "db.commit()" backend/app/routers/ | grep -v "write_audit"
```

Any `db.commit()` in a mutating endpoint that is not preceded by `write_audit()` on a sensitive operation is a gap. Not every commit needs an audit row (read-only helpers, background tasks) — but every action that changes role, access, or account status does.

## 2026-05-11 Secure App Development: CI-3 — Property-Based Fuzz Testing with Hypothesis

### What property-based testing is and why it's different

A normal unit test says: "given this specific input, expect this specific output." You write the examples you thought of. The problem: you only test inputs you imagined. Real attackers send inputs you didn't imagine — empty strings, 10,000-character strings, null bytes, Unicode right-to-left override characters, inputs that look almost valid.

**Property-based testing** inverts this. Instead of writing examples, you write a *property* — a statement that must always be true — and let Hypothesis generate hundreds of random inputs to try to violate it.

Example property: "any string that is not `bug`, `feature_request`, or `general` must raise a `ValidationError`."

Hypothesis generates 200 random strings (by default), including edge cases it has learned from past failures: empty string, single space, string with null byte, very long string, Unicode. If any of them passes through without raising `ValidationError`, the test fails and reports the exact input that broke it.

### What was added

`tests/test_fuzz_schemas.py` — 9 property-based tests across four schemas:

**`FeedbackCreate`:**
- Any string outside `{"bug", "feature_request", "general"}` → `ValidationError` (200 examples)
- Every member of the allow-list → accepted
- Any message over 2000 characters → `ValidationError`

**`FeedbackStatusUpdate`:**
- Any string outside `{"new", "in_progress", "resolved"}` → `ValidationError` (200 examples)
- Every valid status → accepted

**`TruckCreate`:**
- Name over 100 characters → `ValidationError`
- Empty name → `ValidationError`
- Any string 1–100 characters → accepted

**`EmployeeCreate`:**
- Strings without a valid email structure → `ValidationError` (200 examples)

### How Hypothesis strategies work

```python
@given(st.text().filter(lambda s: s not in VALID_FEEDBACK_TYPES))
def test_invalid_type_always_rejected(self, invalid_type: str):
    with pytest.raises(ValidationError):
        FeedbackCreate(type=invalid_type, message="hello")
```

- `st.text()` — generates arbitrary Unicode strings
- `.filter(...)` — excludes the three valid values so we only test invalid ones
- `@given(...)` — tells Hypothesis to call this test function repeatedly with generated values
- `@h_settings(max_examples=200)` — run 200 examples instead of the default 100

Hypothesis also maintains a database of past failures. If a test ever fails on input `"admin'; DROP TABLE"`, that exact input is replayed on every future run to prevent regressions.

### The connection to SEC-5

The `Literal` allow-lists we added in SEC-5 are what make these tests pass. Before SEC-5, `FeedbackCreate.type` was `str` — any of the 200 generated strings would have been accepted, and every one of these tests would have failed. The fuzz tests are the verification layer that proves the SEC-5 fix holds under adversarial input.

## 2026-05-11 Secure App Development: CI-2 — Dependency CVE Scanning with pip-audit

### Why dependency scanning matters (OWASP 2021 A06 — Vulnerable and Outdated Components)

Your application's attack surface is not just your code — it includes every library you depend on. `requirements.txt` pins specific versions. When a CVE is published against one of those versions, your app is vulnerable until you update. Without automated scanning, you may never know.

`aiohttp==3.9.3` was pinned in this project. The 3.9.4 release patched a known vulnerability. The version sat there unnoticed because there was no automated check — a human would have to manually read release notes for every dependency on every push.

### The fix: pip-audit in CI

`pip-audit` checks every package in `requirements.txt` against the Python Packaging Advisory Database (PyPA). If any installed package has a known CVE, the step fails — the commit gets a red ✗ before tests even run.

Added to `.github/workflows/ci.yml` as a step between install and test:

```yaml
- name: Audit dependencies for CVEs
  working-directory: backend
  run: pip-audit -r requirements.txt
```

`pip-audit` is installed alongside the project dependencies in the same `pip install` step — no separate install needed.

### The aiohttp bump

`aiohttp==3.9.3` was bumped to `3.13.5` (current stable). The 3.9.x series is end-of-life — any new CVEs discovered in it will not receive backport patches. Staying on a supported minor version means security patches are available when needed.

**Why `aiohttp` specifically:** it's used in `dispatch.py` to make outbound HTTP calls. An SSRF or request-smuggling CVE in `aiohttp` would directly affect the bot communication path — the same attack surface we hardened in SEC-4.

### The general rule

Every dependency pin in `requirements.txt` is a commitment to that version's security posture at the moment you pinned it. CVEs are discovered continuously. Automated scanning on every push means the gap between "CVE published" and "you know about it" is measured in hours, not months.

### The problem: per-replica in-process state

`security.py` previously stored Cognito's public signing keys in a module-level Python dict:

```python
_jwks_cache: dict[str, dict] = {}
```

This dict lives in the memory of one specific server process. With `--workers 4` in production (four separate uvicorn processes), each worker has its own isolated copy. They never share state.

Consequences:
- Every worker fetches JWKS from Cognito independently on startup — 4 network calls instead of 1
- When AWS rotates a signing key, each worker detects the miss and re-fetches at a different time — during that window, some workers have the old key, some have the new one, causing intermittent 401 errors depending on which worker handles a given request
- The cache lives forever in memory — stale keys sit there until the process restarts

### The fix: Redis as a shared cache

Redis is already running as a shared service all workers connect to. Moving the JWKS cache there means all workers read from and write to the same place. Worker 1 populates the cache; workers 2, 3, and 4 immediately get a hit.

```python
JWKS_REDIS_KEY = "jwks_cache"
JWKS_TTL_SECONDS = 3600  # auto-expires after 1 hour

def get_jwks() -> dict[str, dict]:
    r = _get_redis()
    cached = r.get(JWKS_REDIS_KEY)
    if cached:
        return json.loads(cached)
    jwks = _fetch_jwks()
    r.set(JWKS_REDIS_KEY, json.dumps(jwks), ex=JWKS_TTL_SECONDS)
    return jwks
```

The TTL is the key addition. The old dict cached forever. Redis automatically expires the key after 1 hour — the next request fetches fresh keys from Cognito. AWS key rotation is handled gracefully: on a `kid` miss, the code force-fetches from Cognito and writes back to Redis, immediately fixing the cache for all workers simultaneously.

### Why sync Redis instead of async

The `redis` package ships two clients: `redis.Redis` (sync) and `redis.asyncio.Redis` (async). The existing Redis usage in `redis.py` uses async because it serves async route handlers. `security.py` is different — `verify_cognito_token` is a sync function called inside a sync FastAPI dependency.

| | Sync Redis | Async Redis |
|---|---|---|
| Event loop | Blocks for ~1-10ms per call | Never blocks |
| Refactoring cost | Zero — function stays sync | Must make `verify_cognito_token` and `get_current_user` async, cascading through `deps.py` |
| Correct at scale | No — blocks under high concurrency | Yes |
| Correct at this project's scale | Yes — 1ms is immeasurable | Yes (but unnecessary complexity) |

**Decision:** sync Redis now. The scaling note is preserved in the code:

> IF this system ever scales to high concurrency (hundreds of simultaneous requests), migrate to `redis.asyncio` and make `get_current_user` + `verify_cognito_token` async. The Redis logic stays identical — only the client import and `await` keywords change.

### The general rule

In-process caches (module-level dicts, class variables, `functools.lru_cache`) break as soon as you run more than one process. Any state that must be consistent across workers belongs in a shared external store — Redis, a database, or a distributed cache. The question to ask when adding any cache: "what happens when two processes have different values here?"

## 2026-05-11 Secure App Development: ENV-2 and ENV-3 — Startup Guards for Non-Dev Environments

### ENV-2: The "production only" trap

The original `INTERNAL_SECRET` guard in `Settings.__init__` was:

```python
if self.app_env == "production" and self.internal_secret == "change-me-in-production":
    raise RuntimeError(...)
```

This only fires when `app_env` is exactly the string `"production"`. A staging deployment running `APP_ENV=staging` with the default secret passes silently — the guard never triggers. Staging environments are the most common source of credential leaks because they're treated as "not production" but often have access to real data or real infrastructure.

**Fix:** invert the condition — block any environment that is not explicitly development:

```python
if self.app_env != "development" and self.internal_secret == "change-me-in-production":
    raise RuntimeError(...)
```

Now `staging`, `test`, `production`, or any unrecognized value all require a real secret. Only `"development"` is exempt.

**The general principle:** security guards should allowlist the safe case (`== "development"`) rather than blocklist the dangerous case (`== "production"`). New environment names you haven't thought of yet are automatically blocked.

### ENV-3: Localhost CORS origins in non-dev environments

`Settings.cors_origins` defaults to seven localhost ports. A misconfigured staging deploy would boot successfully with those defaults and accept cross-origin requests from any localhost tab — including a developer's local attacker page.

**Fix:** startup check in the same `__init__`:

```python
if "localhost" in self.cors_origins and self.app_env != "development":
    raise RuntimeError(
        "CORS_ORIGINS contains 'localhost' in a non-development environment. "
        "Set CORS_ORIGINS to your actual production/staging domain(s) before deploying."
    )
```

The app refuses to start if `CORS_ORIGINS` wasn't overridden for the environment. This is the correct pattern for any config value that has a safe dev default but a dangerous production default — fail loudly at startup, not silently at runtime.

### The mistake made during implementation

The first attempt wrote `"local_host"` (with an underscore) instead of `"localhost"`. The check compiled and ran without error — Python string containment doesn't care whether the substring exists. The guard was silently broken: it would never match, and no localhost origin would ever be caught. This is a class of bug that has no runtime signal — tests pass, the app starts, and you only discover it when a staging deploy with localhost origins causes a security incident.

### Post-rectification fix: CI environment was blocked

After completing the rectification, ENV-3 introduced a blocker: the GitHub Actions CI pipeline runs with `APP_ENV=test`, and `cors_origins` defaults to seven localhost ports when `CORS_ORIGINS` is not set in the CI env block. The guard condition `app_env != "development"` matched `"test"`, causing `RuntimeError` at `Settings()` import time — every test in CI would fail before any test code ran.

**Fix:** extended the exemption to include `"test"`:

```python
if "localhost" in self.cors_origins and self.app_env not in {"development", "test"}:
```

**Why a set instead of adding `== "test"` as a second condition:** A set makes the intent explicit — these are the environments where localhost CORS is acceptable by design. If a new environment like `"local_docker"` is ever added, the set is the natural place to extend it. A chain of `or` conditions is harder to scan and easier to mis-extend.

**Why not fix it by adding `CORS_ORIGINS` to the CI env block:** That would work, but it introduces a value that needs to be maintained alongside the guard — two places to update when policy changes. The guard exempting `"test"` is self-documenting: CI is explicitly not a deployment environment, so the localhost restriction doesn't apply.

**The key lesson:** When writing a startup guard that allowlists environments, always enumerate every environment where the guard should not fire: `{"development", "test"}`. Anything not in the set is protected. If you write `!= "development"`, you are implicitly claiming that every other name you will ever use is a production-like environment — a claim that breaks the first time you add a test or CI environment.

**Lesson:** string-match guards should be tested explicitly. A test that sets `app_env="staging"` and `cors_origins="http://localhost:3000"` and asserts `RuntimeError` is raised would have caught the typo immediately.

## 2026-05-14 Production Deployment: EC2, Docker, and Environment Config

### EC2 instance sizing

A t3.micro (1 GB RAM) is not enough for a full multi-service Docker Compose stack. The AsheFlow stack — FastAPI (4 workers) + PostgreSQL + Redis + Celery worker + Celery beat + Discord bot + Docker/OS overhead — consumes 800 MB–1.2 GB at rest. t3.micro has no headroom for traffic spikes and will hit swap constantly. t3.small (2 GB RAM, ~$15/mo) is the minimum viable size for this stack.

General rule: add up the idle RSS of every process you plan to run, multiply by 1.5 for headroom, and pick the next instance size above that.

### Security groups are the EC2 firewall

A security group is a stateful firewall that controls which ports are reachable from the internet. The correct rules for a web backend are:

- Port 22 (SSH) — your IP only. Never `0.0.0.0/0` — open SSH to the world invites brute-force attacks within minutes.
- Port 80 (HTTP) — anywhere. Nginx listens here and redirects to HTTPS.
- Port 443 (HTTPS) — anywhere. Nginx terminates SSL here and proxies to the app.
- Port 8000 (FastAPI) — **do not open**. Nginx reaches it on `127.0.0.1:8000` internally. There is no reason for the public internet to reach the app server directly.

The principle: open the minimum set of ports required for the service to function. Every open port is an attack surface.

### IAM roles grant EC2 permission to call other AWS services

By default an EC2 instance has zero AWS permissions — it cannot call SES, CloudWatch, S3, or anything else. An IAM role is a permission slip attached to the instance at launch time. The instance automatically receives temporary credentials that rotate every hour.

For AsheFlow the role needs:
- `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents` — for the Docker `awslogs` driver to ship container logs to CloudWatch
- `ses:SendEmail` — for the backend to send invite and registration emails

Without the CloudWatch permissions, Docker fails to start any container that has `logging: driver: awslogs` in its Compose config — the entire stack refuses to come up.

### Two .env files serve different purposes

Docker Compose reads the root `.env` file automatically to substitute variables in `docker-compose.yml`. The backend's pydantic `Settings` class reads `backend/.env` directly via `env_file = ".env"` in its Config. They are not the same file and serve different masters:

- Root `.env` — variables Docker Compose needs to configure the infrastructure layer: `POSTGRES_PASSWORD`, `POSTGRES_USER`, `POSTGRES_DB`, `REDIS_URL`, `DISCORD_BOT_TOKEN`
- `backend/.env` — variables the FastAPI application needs at runtime: `APP_ENV`, `AWS_COGNITO_USER_POOL_ID`, `CORS_ORIGINS`, `INTERNAL_SECRET`, `BOT_INTERNAL_URL`

A missing variable in root `.env` causes `docker compose up` to fail with a substitution error. A missing variable in `backend/.env` causes `Settings()` to raise a `ValidationError` at import time, crashing the container immediately after it starts.

### INTERNAL_SECRET must match in every service that uses it

`INTERNAL_SECRET` is the shared secret used to authenticate bot → backend webhook calls. The backend checks the `X-Internal-Secret` header on internal endpoints. If `backend/.env` and `bot/.env` have different values, every bot call returns 403. This is easy to get wrong when copying values between files — always verify both files have the same value before starting services.

### GitHub fine-grained tokens for server deployments

A server that only needs to clone a repo should use a fine-grained Personal Access Token scoped to that one repository with **Contents: Read-only** permission. This is the least-privilege approach:

- Classic tokens grant access to all repos the account can see
- Fine-grained tokens scope to specific repos and specific permissions
- If the token is compromised, the blast radius is limited to one repo, read-only

Tokens should have a 90-day expiry. When they expire, generate a new one and update the server. This is preferable to a non-expiring token that can be forgotten and abused indefinitely.

### Cognito service accounts for bots

The Discord bot authenticates to the backend API using a dedicated Cognito account (`asheflow.bot`). This is a service account — a non-human identity used exclusively by automated processes. Key points:

- Use `admin-set-user-password` with `--permanent` to skip the forced-change-on-first-login flow. Without `--permanent`, the account is in `FORCE_CHANGE_PASSWORD` state and any login attempt returns an auth challenge the bot doesn't know how to handle.
- Use `--message-action SUPPRESS` on `admin-create-user` to prevent Cognito from sending a welcome email to a non-existent address.
- The bot's Cognito account should have the minimum role needed — dispatch role is sufficient; it does not need admin.
- Store the bot's credentials in `bot/.env`, never in code or git history.

### Alembic revision IDs must be 32 characters or fewer

The `alembic_version` table stores the current migration version in a `VARCHAR(32)` column. Alembic does not enforce a length limit when you write a revision ID — it only fails at runtime when it tries to write the ID to the database.

The failure mode is subtle: the schema change in the migration applies successfully, but the version write fails, leaving the database in an inconsistent state where the schema is ahead of what `alembic_version` records.

**Rule:** keep revision IDs short and descriptive. `add_expired_tor` is better than `20260409_add_expired_status_to_time_off_requests`. Date prefixes add length without adding information that isn't already in the migration's `Create Date` field.

When you change a revision ID, you must update it in every migration file that references it as a `down_revision` — not just the file where it's defined. Always `grep -r` for the old ID before committing.

### Always push before deploying

A server `git pull` that says "Already up to date" when you expect new code means the commits exist locally but were never pushed to the remote. The server clones from GitHub, not from your local machine.

The correct deploy sequence is always:
1. Commit locally
2. `git push origin master`
3. `git pull origin master` on the server

Skipping step 2 means the server runs stale code with no error — it just silently runs whatever was there before.

### Docker awslogs driver: use `awslogs-stream` not `awslogs-stream-prefix`

`awslogs-stream-prefix` is not supported by all builds of the Docker awslogs driver, including the build on Ubuntu 26.04. The error `unknown log opt 'awslogs-stream-prefix'` appears at container start time and prevents the container from starting.

Use `awslogs-stream` instead:

```yaml
logging:
  driver: awslogs
  options:
    awslogs-group: /asheflow/production
    awslogs-region: us-east-2
    awslogs-stream: asheflow   # not awslogs-stream-prefix
```

The CloudWatch log group must also exist before containers start — create it with:

```bash
aws logs create-log-group --log-group-name /asheflow/production --region us-east-2
```

### Use one AWS region everywhere

Mixing regions across config files, IAM policies, log groups, and env vars causes silent failures. A request hitting the wrong region finds no resources and returns a generic error that doesn't mention the region mismatch.

For AsheFlow everything lives in `us-east-2`:
- Cognito user pool: `us-east-2`
- SES: `us-east-2`
- CloudWatch log group: `us-east-2`
- EC2 instance: `us-east-2`

The `docker-compose.prod.yml` YAML anchor originally defaulted to `us-east-1`. The default was wrong from day one — it only became visible when CloudWatch logging was actually exercised. Always set explicit values rather than relying on defaults for region configuration.

### Nginx as a reverse proxy with SSL

The FastAPI app listens on port 8000 internally. Nginx sits in front of it and handles the public-facing concerns: HTTP→HTTPS redirect, SSL termination, and forwarding requests to the app. Port 8000 is never opened in the security group — only ports 80 and 443.

The minimal Nginx config for a FastAPI backend:

```nginx
server {
    listen 80;
    server_name api.asheflow.com;
    location / { return 301 https://$host$request_uri; }
}

server {
    listen 443 ssl;
    server_name api.asheflow.com;
    # ssl_certificate lines added automatically by certbot

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

`proxy_set_header X-Forwarded-Proto $scheme` is important — FastAPI uses it to know whether the original request was HTTP or HTTPS. Without it, redirect logic and security checks that inspect the protocol see `http` even when the client connected over HTTPS.

Certbot with the `--nginx` flag auto-discovers the `server_name`, issues the certificate, and rewrites the Nginx config to add the SSL blocks. Running `sudo certbot --nginx -d api.asheflow.com` is all that's needed.

Let's Encrypt certificates expire after 90 days. Certbot installs a systemd timer that auto-renews them — no manual action required.

### Services missing from docker-compose.yml cause orphan containers

If a container was started in a previous session but its service definition was removed from (or never added to) `docker-compose.yml`, Docker Compose shows a warning: `Found orphan containers`. The container keeps running but is no longer managed by Compose — `docker compose down` won't stop it, and `docker compose ps` won't show it.

The fix is to add the service to `docker-compose.yml` properly. Once defined, Compose manages its full lifecycle.

The bot had a `Dockerfile` but was never added to `docker-compose.yml`. It ran as an orphan from a previous manual `docker run`. Adding it as a proper service with `restart: unless-stopped` means it will restart automatically if it crashes or if the server reboots.

### EC2 IAM role credentials are available inside containers automatically

When an EC2 instance has an IAM role attached, any process running on that instance — including processes inside Docker containers — can call `http://169.254.169.254/latest/meta-data/iam/security-credentials/` to get temporary AWS credentials. The AWS SDK (boto3, etc.) does this automatically.

This is why `botocore.credentials: Found credentials from IAM Role: asheflow-ec2-role` appears in the bot logs without any explicit credential configuration. No `AWS_ACCESS_KEY_ID` or `AWS_SECRET_ACCESS_KEY` env vars are needed inside the containers — the role provides them transparently.

## 2026-05-14 Frontend Design System: Chart Accessibility

### Color alone is not enough to differentiate chart series

The AsheFlow design system uses three extended colors for multi-series charts:

- **Gold** (35 80% 38%) — Drivers / series #1
- **Teal** (172 50% 38%) — Walkers / series #2
- **Slate Blue** (215 40% 50%) — Trainers / series #3

These are perceptually distinct for most users, but Teal and Slate Blue can be difficult to distinguish for users with **deuteranopia** (green-blue color vision deficiency), which affects approximately 1% of people.

**WCAG 1.4.1 (Use of Color, Level A)** requires that color is not the *only* visual means of conveying information. For charts, this means each series must have a secondary differentiator in addition to color.

**Required when implementing chart components:**

- Use different **line dash patterns** (solid, dashed, dotted) per series, OR
- Use different **marker shapes** at data points (circle, square, triangle) per series, OR
- Both

The legend must also reflect whichever secondary differentiator is used — not just a color swatch.

This does not affect the color token definitions themselves. The colors are approved. The enforcement happens at the chart component level.

### Dark theme surfaces: always use a border, not just background contrast

The dark surface system uses four layered tokens, each separated by ~3 lightness points:

| Token | HSL | Role |
|---|---|---|
| Background | 224 24% 6% | Page wash |
| Surface | 224 22% 9% | Card |
| Surface Muted | 224 20% 12% | Subtle fill / input background |
| Accent | 224 22% 16% | Hover state / active nav |

On standard displays the card lift (6% → 9% lightness) is visible. On **OLED displays**, the contrast between these near-black values can collapse entirely, making card boundaries disappear.

**Required when implementing dark theme card components:**

- Always include a **1px border** on cards using white at 10–20% opacity (e.g. `rgba(255,255,255,0.12)`) as a boundary fallback
- Never rely solely on background lightness difference to define card edges in dark theme
- This applies to: cards, modals, dropdowns, input fields — any surface that sits above the page background

### Light theme: Surface Muted is a receding surface, not a card background

The light surface layering order by lightness is:

| Token | HSL | Lightness | Role |
|---|---|---|---|
| Surface | 0 0% 100% | 100% | Card — highest layer |
| Background | 220 25% 98% | 98% | Page wash |
| Surface Muted | 220 20% 96% | 96% | Subtle fill — lowest layer |
| Accent | 243 100% 97% | 97% | Hover / active nav |

Surface Muted sits *below* Background in perceived depth. It is intended for things that should visually recede: input backgrounds, table row alternates, disabled areas.

**Never use Surface Muted as a card background.** A card on Surface Muted will appear to sit below the page, which is the opposite of the intended card-lift effect. Cards must always use the Surface (white) token.

### Light theme: Accent surface hue shift is intentional

The Accent surface (243 100% 97%) uses hue 243 — a more violet-blue — while all other light surfaces use hue 220. This shift is deliberate: it gives hover states and active nav highlights a distinct interactive character that cannot be confused with a plain lighter surface. Do not "fix" this hue discrepancy when implementing — it is load-bearing.

### Shadows are light-theme only — dark theme uses surface layering instead

The three shadow tokens (Soft / Medium / Large) are defined for light theme only:

| Token | Role |
|---|---|
| Soft | Card default |
| Medium | Card hover |
| Large | Modal / popover |

On dark backgrounds, drop shadows are nearly invisible — there is no light surface beneath the element to cast against. **Do not apply these shadow tokens on dark theme.**

On dark theme, elevation is communicated via two mechanisms already defined in the system:
1. **Surface lightness layering** — Background (6%) → Surface (9%) → Surface Muted (12%) → Accent (16%)
2. **1px border** at `rgba(255,255,255,0.12)` on all elevated surfaces

When implementing components that use shadows on light theme, wrap the shadow token in a theme conditional so it is zeroed out (`box-shadow: none`) on dark theme, and the border provides the boundary instead.

### Glow shadows: dark theme intensity inverts — tune per theme

The four glow tokens (primary, gold, success, danger) are colored halos used for emphasis — focused inputs, selected cards, critical alerts, destructive confirmations.

On light theme, glows are soft and subtle against the near-white background. On dark theme, the same spread and opacity values produce a much more aggressive halo because the colored glow has high contrast against the near-black surface. **Do not use the same glow values across both themes.** Dark theme glows need reduced spread or opacity to avoid feeling alarming.

Implement glow tokens with theme conditionals, e.g.:
- Light: `box-shadow: 0 0 0 4px rgba(var(--color-primary), 0.25)`
- Dark: `box-shadow: 0 0 0 3px rgba(var(--color-primary), 0.40)` (tighter spread, slightly higher opacity for definition without bleed)

### Glow shadows cannot replace focus rings (WCAG 2.4.11)

Glow shadows may supplement a focus indicator but cannot be the only one. **WCAG 2.4.11 (Focus Appearance, Level AA)** requires:
- Focus indicator has at least **3:1 contrast** against adjacent colors
- Focus indicator encloses the component with a minimum area

A colored glow alone does not reliably meet the minimum area or contrast requirements across all backgrounds. Always pair a glow with a solid `outline` (e.g. `outline: 2px solid currentColor; outline-offset: 2px`) on focusable elements. The glow is decorative; the outline is the accessible focus indicator.

### Iconography: test 12px Lucide icons on 1x (non-retina) displays

The icon system uses Lucide React at 1.5 stroke weight across three sizes: 16px / 14px / 12px. At 16px and 14px the 1.5 stroke is clean and modern. At **12px on a non-retina (1x) display**, 1.5px strokes can render thin and fragile — sub-pixel rendering at small sizes on standard screens may cause icons to look lighter or less defined than intended.

**Required before finalizing the 12px size:** Test on a 1x display (not just a MacBook retina screen). If strokes look too thin, either bump the small size to 14px or increase stroke weight to 2.0 for the 12px variant only.

### Iconography: verify RefreshCw vs RefreshCcw

Lucide has two refresh icons: `RefreshCw` (clockwise) and `RefreshCcw` (counter-clockwise). The design uses `RefreshCw`. Clockwise is the standard convention for "reload/refresh" so this is likely correct — but confirm the imported icon name matches exactly when implementing. Importing the wrong variant produces a subtly mirrored icon that most users won't notice but that will diverge from the design spec.

### Motion: spring easing must only be applied to transform and opacity

The spring easing curve is cubic-bezier(.34, 1.56, .64, 1). The Y value of 1.56 means the animation **overshoots** past its target value before settling — this produces the tactile bounce/spring effect intended for button press and interactive feedback.

Two constraints that must be enforced at implementation time:

1. **Never use spring on elements inside an `overflow: hidden` parent.** The overshoot portion of the animation will be clipped, making the motion look abrupt rather than springy — the opposite of the intended effect.

2. **Only apply spring to `transform` and `opacity`.** Animating layout-affecting properties (`width`, `height`, `margin`, `padding`) with an overshooting curve causes reflow on every frame, which is expensive and can cause layout thrashing. `transform` and `opacity` are composited by the GPU and do not trigger reflow.

The other two curves (out-soft, linear) have no overshoot and can be applied to any animatable property.

### StatCard: use fixed min-height to equalize cards, never adjust font size

The three stat cards (Assigned, Confirmed, Pending) have the same anatomy except Pending has a hint text line ("Confirmations open"). This makes Pending naturally taller than the other two.

**Do not shrink the font size on Pending to force equal height.** Font size is semantic — the value and label must be the same scale across all three cards. Shrinking Pending makes it look subordinate, which is wrong since Pending is the most actionable state.

**Correct fix:** Set a `min-height` on all stat cards equal to the natural height of the Pending card (which includes the hint line). Assigned and Confirmed cards get extra bottom padding to fill the space. All cards are the same height, all text stays the same size.

```css
.stat-card {
  min-height: /* Pending card's natural height */;
  display: flex;
  align-items: center;
}
```

The hint text slot should always be present in the DOM on all cards — empty on Assigned/Confirmed, populated on Pending — so the layout doesn't shift when data changes.

### Role badge color mapping (approved)

All role badges use font-weight 500 — no semantic bold. Negative states (Declined, Deactivated) communicate severity through color alone, not weight.

Approved role color assignments:

| Role | Color token | Rationale |
|---|---|---|
| driver | Slate Blue | Primary operational role |
| walker | Teal | Secondary operational role |
| trainer | Gold | Training accent — performance/coaching context |
| trainee | Orange/peach tint | In-training state, distinct from active roles |
| admin | Neutral | Access level, not an operational role — must not share a color with any crew role |

Admin uses Neutral specifically because it is an access level (permissions), not a job function. Giving it a crew color (Gold, Teal, Slate Blue) would imply it belongs in the operational hierarchy, which it does not.

### Typography: load only the Sora weights actually used

The display typeface is **Sora** (Google Fonts). Only load the weights used in the type scale — loading all weights (100–800) adds unnecessary page weight.

Required weights based on the approved type system:
- **700** — display headings (confirmed)
- **600** — if used for subheadings or UI labels (confirm when full type scale is approved)

In the `<link>` preconnect or `@import`:
```
https://fonts.googleapis.com/css2?family=Sora:wght@600;700&display=swap
```

Use `display=swap` to prevent invisible text during font load (FOIT). This shows system font fallback until Sora loads, which is better than a blank page.

### Top Nav: needs responsive overflow strategy for 8 items

The approved top nav has 8 items: Home / Dispatch / Schedule / Roster / Fleet / Field Ops / Incidents / Analytics. At viewport widths below ~1024px these will overflow horizontally or wrap.

Required at implementation: define a breakpoint strategy — either collapse all nav items behind a hamburger/drawer at a set breakpoint, or keep primary items visible (Home, Dispatch, Schedule) and move lower-priority items (Incidents, Analytics) into a "More" overflow menu. Do not let items wrap to a second nav row.

### Typography: load only JetBrains Mono weight 400

The mono typeface is **JetBrains Mono** used for dates, truck IDs, and timestamps (e.g. `2026-05-14 · TRK-04 · 06:32`). Load only weight 400 (regular). Bold and italic mono variants are not in the approved type system — do not load them.

The full approved font stack — load all three families in a single request:
```
https://fonts.googleapis.com/css2?family=Sora:wght@600;700&family=Inter:wght@400;600&family=JetBrains+Mono:wght@400&display=swap
```

**Inter** is the body and section typeface (400 for body/subtle, 600 for section headings). It pairs with Sora because both are geometric sans-serifs, but Inter is optimized for screen readability at small sizes (14px body text). Load only 400 and 600 — bold Inter (700+) is not in the approved type scale.

JetBrains Mono was chosen specifically because it clearly distinguishes 0/O and 1/l/I — critical for truck IDs and timestamps where a misread character (TRK-04 vs TRK-D4) has operational consequences.

### Typography: test 10px role labels on 1x displays

The role label style (10px / 700 / 0.14em tracking) is at the border of WCAG AA minimum readable size. The weight and tracking compensate, but **test on a non-retina (1x) display** before finalizing. If the text renders too thin or small, bump to 11px to match the eyebrow style. Do not go below 10px for any text in the system.

---

## 2026-05-14 Frontend Design System: Implementation

### Design system token update (v3 → v4)

The existing `frontend/src/index.css` design system was replaced with the values approved during the Claude Design session. Key changes:

**Color tokens corrected:**
- Primary: `243 75% 59%` (violet-indigo) → `225 70% 55%` (blue-indigo, AA 4.9:1)
- Gold: `41 78% 55%` (old amber) → `35 80% 38%` (warm amber, AA 4.7:1)
- `--neutral` and `--slate` added for admin role and driver role badges
- `--violet` removed — replaced by `--slate` in the extended palette

**Font import optimised:**

Before (loading all weights):
```
Inter:wght@300;400;500;600;700;800 + Sora:wght@500;600;700;800
```
After (only weights used in the type scale):
```
Inter:wght@400;600 + Sora:wght@600;700 + JetBrains+Mono:wght@400
```

**Accessibility fixes applied from learning guide flags:**
- Focus ring: replaced glow-only with `outline: 2px solid hsl(var(--ring))` (WCAG 2.4.11 compliant). Glow is supplementary only.
- Dark theme cards: `box-shadow: none` + `border-color: rgba(255,255,255,0.12)` — prevents OLED contrast collapse
- Spring easing removed from layout/color transitions — only applied to `transform` properties
- Skeleton shimmer changed from `ease-out-soft` to `linear` — prevents jarring loop
- `stat-card` class with `min-height: 88px` equalizes cards with and without hint text
- Glow tokens have dark-theme variants with reduced spread to prevent overpower
- All buttons given `min-height: 44px` for WCAG 2.5.5 touch target compliance

**Tailwind config updated:**
- `fontFamily.mono` now leads with `JetBrains Mono`
- `slate` and `neutral` color tokens registered
- `violet` color token removed

### Design system components

New file: `frontend/src/components/design-system/primitives.tsx`

Typed React components implementing the approved design system:

| Component | Purpose |
|---|---|
| `Avatar` | Initials avatar with role-based color (driver=slate, walker=teal, trainer=gold, trainee=warning) |
| `Badge` | Toned pill badge — 8 tone variants |
| `StatusBadge` | Assignment status (confirmed/pending/declined/assigned) |
| `RoleBadge` | Employee role — uses approved color mapping, admin=neutral |
| `StatCard` | KPI card with icon chip, label, value, hint — min-height equalized |
| `SectionHeader` | Page header with eyebrow, title, description, actions |
| `Card` | Surface card with correct border for OLED fallback |
| `Kbd` | Keyboard chip — platform-aware: renders ⌘ on Mac, Ctrl on Windows/Linux |
| `Eyebrow` | Section eyebrow label |
| `IconButton` | Icon-only button with optional notification badge |

### Logo assets

Copied from Claude Design handoff bundle into `frontend/src/assets/`:
- `logo-full.svg` / `logo-full-light.svg` — full lockup (mark + wordmark)
- `logo-mark.svg` / `logo-mark-light.svg` — mark only
- `logo-wordmark.svg` — wordmark only
- `favicon.svg` — browser tab icon

### Build errors fixed

Two TypeScript errors blocked the production build:

**1. `signIn_failure` not in Amplify's typed Hub event union**
`AuthContext.tsx` used a `switch (payload.event)` where `'signIn_failure'` is not in Amplify v6's typed union, causing `TS2678`. Fix: cast `payload.event as string` before the switch so TypeScript does not narrow the union, then access payload data via `(payload as any)`.

**2. `ErrorBanner` missing `className` prop**
`ErrorBanner.tsx` did not accept a `className` prop but `Companies.tsx` passed one, causing `TS2322`. Fix: added `className?: string` to the Props interface and applied it conditionally to the wrapper div.

## 2026-05-14 Frontend Deployment: S3 + CloudFront

### Architecture

```
User → CloudFront (HTTPS) → S3 bucket (static files)
         asheflow.com
         www.asheflow.com
```

CloudFront handles SSL termination, compression, and global CDN edge caching. S3 hosts the static files. The two layers are never exposed to users separately.

### S3 bucket setup

Bucket name: `asheflow-frontend` (us-east-2)

- Static website hosting enabled with `IndexDocument: index.html` and `ErrorDocument: index.html`
- The error document pointing to `index.html` is the SPA fallback — any unknown path (e.g. `/dispatch/today`) returns the app, which handles routing client-side
- Public read bucket policy applied — required for CloudFront to fetch files as an anonymous origin

**Cache-control strategy:**
- `index.html` — `no-cache,no-store,must-revalidate` — browser always revalidates. This ensures users get the new `index.html` immediately after a deploy, which references the new hashed asset filenames.
- All other files (`assets/*.js`, `assets/*.css`, etc.) — `public,max-age=31536000,immutable` — cached for 1 year. Vite appends a content hash to filenames (`index-DqGqjQI5.js`) so new deploys produce new filenames. The old cached files are never stale because the new `index.html` points to new filenames.

This two-tier cache strategy means: zero stale app delivery, near-zero origin requests for repeat visitors.

### ACM certificate

CloudFront requires an SSL certificate in **us-east-1** regardless of where the S3 bucket lives. This is a hard AWS requirement — CloudFront's certificate lookup is always global/us-east-1.

Certificate ARN: `arn:aws:acm:us-east-1:[account-id]:certificate/[redacted]`

Validated via DNS: two CNAME records added to Route 53 hosted zone `Z05950531EYSU1BYQZRAG`. ACM checks for these records and issues the certificate automatically. Validation took ~2 minutes.

Covers: `asheflow.com` + `www.asheflow.com` (SAN).

### CloudFront distribution

Distribution ID: `E22NJCS9JDU8FG`
CloudFront domain: `d1ezk0tgu5lkoi.cloudfront.net`

Key settings:
- `ViewerProtocolPolicy: redirect-to-https` — HTTP requests are automatically redirected to HTTPS
- `CachePolicyId: 658327ea-f89d-4fab-a63d-7e88639e58f6` — AWS Managed CachingOptimized policy. Respects the `cache-control` headers set during upload.
- `Compress: true` — CloudFront serves gzip/brotli automatically
- `PriceClass_100` — US, Canada, Europe edge locations only (lowest cost tier)
- Custom error response: 404 → `/index.html` with HTTP 200 — required for SPA client-side routing. Without this, deep-linking to any route other than `/` would return a real 404 from S3.
- `DefaultRootObject: index.html` — requests to `/` serve `index.html`

### DNS wiring

Two Route 53 A records updated to CloudFront Alias records:
- `asheflow.com` → `d1ezk0tgu5lkoi.cloudfront.net` (Alias)
- `www.asheflow.com` → `d1ezk0tgu5lkoi.cloudfront.net` (Alias)

CloudFront's hosted zone ID for Alias records is always `Z2FDTNDATAQYW2` — this is a fixed AWS constant, not specific to this distribution.

### How to redeploy the frontend

Every time the frontend code changes:

```bash
# 1. Build
cd frontend
npm run build

# 2. Upload — assets first (immutable cache), then index.html (no-cache)
aws s3 sync dist/ s3://asheflow-frontend/ \
  --region us-east-2 --delete \
  --cache-control "public,max-age=31536000,immutable" \
  --exclude "index.html"

aws s3 cp dist/index.html s3://asheflow-frontend/index.html \
  --region us-east-2 \
  --cache-control "no-cache,no-store,must-revalidate"

# 3. Invalidate CloudFront cache for index.html
aws cloudfront create-invalidation \
  --distribution-id E22NJCS9JDU8FG \
  --paths "/index.html"
```

Step 3 (invalidation) is only needed for `index.html` because it is the only file with a non-immutable cache. Asset files have content-hashed names — new deploys produce new names, so old cached copies are automatically abandoned.

### Final production state

| Service | URL | Stack |
|---|---|---|
| Frontend | `https://asheflow.com` | CloudFront + S3 |
| API | `https://api.asheflow.com` | EC2 + Nginx + FastAPI |
| Bot | — | Discord Gateway (Docker) |
| Celery worker | — | Docker on EC2 |
| Celery beat | — | Docker on EC2 |
| PostgreSQL | — | Docker on EC2 |
| Redis | — | Docker on EC2 |

---

## 2026-05-16 — Test Suite Overhaul, Production Bug Fix, CI Pipeline

### Tests catch bugs that code review misses

Writing `test_training_injection.py` immediately found a production bug that had been present since the multi-tenant migration: `inject_curriculum` never set `company_id` on `TrainingRecord` or `TrainingTask` rows. PostgreSQL enforces NOT NULL — this would have crashed every dispatch with trainees with a `500` error. SQLite in tests is more lenient, which is why it went undetected. The fix was to thread `company_id` through the function signature and pass it to every model constructor.

**Lesson:** When you add a NOT NULL column to a table, grep every service that inserts into that table and verify it sets the new column. A migration alone is not enough.

### conftest helpers must mirror the model's constraints

`make_off_day` and `make_time_off_request` were missing `company_id=employee.company_id`. This caused `IntegrityError` on every test that used them, making tests fail for reasons unrelated to what they were testing. Helper functions in `conftest.py` must always set every NOT NULL column — treat them like production insert code.

### pip-audit as a CI gate

`pip-audit` runs before the test job. If a dependency has a known CVE, the pipeline stops before wasting time on tests. Three packages had accumulated 8 CVEs since they were first pinned: `pyjwt`, `cryptography`, `requests`. Always pin to a specific version AND audit regularly — a package that was safe when you pinned it may have CVEs published later.

```bash
pip install pip-audit
pip-audit -r requirements.txt
```

### GitHub Actions: FORCE_JAVASCRIPT_ACTIONS_TO_NODE24

GitHub deprecated Node.js 20 on Actions runners. The fix is one environment variable at the job level — no need to wait for updated action versions:

```yaml
env:
  FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: true
```

### CI pipeline structure: audit → test → deploy

Jobs with `needs:` run sequentially and block on failure. The right order is:

1. `audit` — fail fast on CVEs before spending any compute
2. `test` — run the suite only if deps are clean
3. `deploy-prod` — deploy only if tests pass, only on `master` push

Use `if: github.ref == 'refs/heads/master' && github.event_name == 'push'` to prevent deploy from firing on PRs or other branches.

### GitHub Environments and secrets

Sensitive values (server IPs, SSH keys) are stored as GitHub Environment secrets, not hardcoded in the workflow. The workflow reads them via `${{ secrets.NAME }}`. Create environments under repo Settings → Environments, add secrets there, and reference the environment name in the job with `environment: prod`.

### Dev → Staging → Prod promotion model

| Stage | Where | How to progress |
|---|---|---|
| Dev | localhost | push branch, run tests locally |
| Prod (current) | EC2 | merge PR to master — CI auto-deploys |
| Staging (planned) | second EC2 | PR from master → staging branch |

Until a staging server is provisioned, code goes from localhost directly to prod via master. This is a known gap — staging is planned for 2026-05-19.

### Stale frontend builds cause silent mixed content bugs

A `.env.production` fix does nothing unless you rebuild and redeploy. Vite bakes env vars into the JS bundle at build time — there is no runtime resolution. If you change `VITE_API_URL` or any other env var, you must:

```bash
npm run build                          # rebuilds with current .env.production
aws s3 sync dist/ s3://your-bucket/ …  # uploads new assets
aws cloudfront create-invalidation …   # busts index.html cache
```

Skipping any step leaves the old bundle on S3/CloudFront. Users get the stale version until their browser cache expires (up to 1 year for immutable assets).

**Symptom to watch for:** Mixed content errors that only affect one role or one page — this usually means one view uses an endpoint that was baked in with the wrong protocol before a `.env.production` correction was deployed.

---

## 2026-05-25 — Location Intelligence: Two-Tier Data Architecture

### The problem with tenant-scoped location data

`LocationProfile` (ADR-093) stores building intelligence per company — building type, workload class, operational notes for each block. The problem: Amazon rotates DSP companies across delivery zones every few years. When a new company enters an area, all the location knowledge gathered by the previous company is gone. Every building is unknown again. The new company starts cold, walker distribution defaults to raw package count, and the system operates at low confidence until enough field reports accumulate.

This creates a perverse situation: the platform grows richer with data over time, but that data is siloed inside each tenant and disappears when a company leaves a zone.

### The two-tier solution

Instead of only tenant-scoped records, the system uses two layers:

**Tier B — `location_profiles`** (company-scoped, unchanged from ADR-093)
Each company builds their own records through the walker submission → captain verification → lock flow. These records are authoritative for that company's current operations.

**Tier A — `location_profile_library`** (platform-wide, AsheFlow-owned)
A global database of verified building intelligence. No `company_id` — not tenant-scoped. Records are promoted here from company records once independently verified across multiple companies or approved by a super admin. Any tenant can read from it. Only AsheFlow super admins can write to it.

### Shadowing — company records take priority

When routing queries location intelligence for a block:
1. Check `location_profiles` for the company's own locked record → use it if found
2. Fall back to `location_profile_library` if no company record exists
3. Fall back to package count proxy if neither exists (flag low confidence)

The company record **shadows** the global record. This handles reality: buildings change. A company reporting different characteristics than the global library triggers a conflict review, not a silent override.

### Why two tables instead of nullable `company_id`

An alternative would be one `location_profiles` table where global records have `company_id = NULL`. This was rejected because the entire multi-tenant codebase treats `company_id` as a mandatory, non-nullable isolation guard. Introducing a `NULL` exception creates a category of records every query must handle specially — a missed filter could leak global records into tenant queries or silently exclude them. The two-table approach keeps the tenant isolation invariant intact and makes the global/company distinction explicit in the schema itself.

### Promotion — how company data becomes global data

**Automatic**: when the same `(block_key, building_type)` is locked in records from 2+ independent companies, the system promotes automatically. Two separate DSPs independently verifying the same building is treated as high-confidence signal.

**Manual**: a super admin reviews and approves a nominated company record. This handles blocks where only one company has ever operated — the automatic threshold can never trigger, but the data quality may still warrant global sharing.

A `nomination_status` field on `LocationProfile` tracks the pipeline:
- `null` — not yet in the promotion pipeline
- `"nominated"` — auto-nominated when the record is verified; queued for super admin review
- `"promoted"` — a copy exists in `location_profile_library`
- `"rejected"` — super admin declined; record stays locked and serves the company normally

### The commercial angle

The global library is a potential differentiator: companies entering a new zone get cold-start data that would otherwise take months to build. This creates an incentive structure where companies are motivated to verify their own records carefully (Amazon measures delivery accuracy) and that verified data feeds back into the platform's intelligence layer — benefiting everyone.

### Key design principle reinforced

This decision reinforces a pattern that appears throughout AsheFlow: **separate models for separate lifecycles**. `LocationProfile` and `LocationProfileLibrary` serve different purposes, have different access rules, and have different write lifecycles. Keeping them as separate models makes those distinctions enforced by the schema rather than just by convention.

---

## 2026-05-25 — Library Cold-Start Query and Mixed Block Key Handling

### How the library is queried during sort

A company in cold start has no records in `location_profiles`. During sort, `assign_clusters` needs workload scores for each cluster. The block_keys for each cluster are derived from package addresses on the fly — the same ephemeral derivation used everywhere in the sort pipeline.

The library lookup is a **single bulk query per sort run**, not per cluster:

```sql
SELECT block_key, building_type, workload_class, operational_note
FROM location_profile_library
WHERE block_key = ANY(:block_keys)
  AND library_status = 'active'
```

All block_keys across all clusters go in at once. The result is loaded into a Python dict keyed by `block_key` before scoring begins. This means zero per-cluster DB hits — the entire location intelligence lookup is one round trip regardless of how many clusters there are.

The unique constraint on `(block_key, building_type)` already creates a composite index with `block_key` as the leading column. The `ANY(:block_keys)` query uses that index — no separate index needed.

### Why a block_key can have multiple building_type entries

A block_key spans a 10-number range on one side of the street — typically 3–5 addresses. Large buildings (mailrooms, freight docks) usually occupy the entire range. But smaller blocks can have mixed use: a ground-floor business and upper-floor apartments sharing the same 10-number range produce two distinct `building_type` entries for the same `block_key`.

### Two separate resolutions for the same ambiguity

The mixed block_key problem is resolved differently depending on who is asking:

**For routing (assign_clusters):** collapse to a single workload weight using the highest `workload_class` across all entries. Conservative — a block with any `high_touch` entry is weighted as `high_touch`. It is better to over-staff an easy block than under-staff a demanding one.

Priority order (highest to lowest):
```
high_touch > high_wait > standard > bulk_drop
```

**For the walker UI:** surface all tags and let the walker resolve at the door. The system does not collapse the ambiguity — it presents it:

```
W_36_St_410s_odd
[mailroom]  [biz_security]
→ Check your address. Follow the protocol for your specific building.
```

Protocol reminders per tag are derived from `building_type` at render time — never stored.

### Provenance flag

Library records surfaced in the walker UI are marked "from AsheFlow library" so walkers know the data may predate their company's presence in the zone. Once the company builds their own locked record for the block, it shadows the library entry and the provenance flag disappears automatically.

### Why block_key travels through the pipeline with each package

`assign_clusters` needs to score each cluster by workload using `LocationProfile` data. The lookup key is `block_key`. But by the time packages reach `assign_clusters`, only `lat`, `lng`, and package identifiers (TBA, tote ID) are present — the street address has been discarded.

Reverse geocoding `(lat, lng) → address` was considered but rejected: it requires an external API call per package, introduces latency and cost at sort time (which runs before the day starts), and creates a failure mode if the API is unavailable.

The correct solution: derive `block_key` from the address string **before clustering**, in the sort orchestrator, using pure string parsing. The block_key is then attached to the package dict as a routing identifier. The street address is discarded after derivation. The block_key — which is not an address, just a derived key — travels with the package through clustering and scoring.

```
manifest arrives   → {tba, lat, lng, address}
derive_block_key() → {tba, lat, lng, block_key}   ← address dropped here
cluster_packages() → clusters, each package still carries block_key
assign_clusters()  → scores clusters using block_key lookups
```

This keeps the address ephemeral while giving the pipeline the routing identifier it needs downstream. It also means `derive_block_key()` is a new service to build — a pure string parser that converts a structured NYC address into the `W_36_St_410s_odd` format.

---

## 2026-05-25 — Address Parsing: Deriving block_key from a Street Address

### The two address patterns

Real delivery addresses arrive in two structural forms:

**Pattern A — Street (direction present):**
```
340 W 28TH ST APT 2J
349 W 37th St Attn Lalpe Hair Extensions
205 West 38th St Ground Floor
40 West 39th Street Host
```

**Pattern B — Avenue (no direction):**
```
480 9th Avenue Host
555 10th Avenue, Unit C
```

The distinguishing rule: if the token after the house number is a direction word (`W|West|E|East|N|North|S|South`), it is a street address. Otherwise it is an avenue address.

### Normalization

Every variant of the same concept maps to one canonical form:

| Concept | Raw variants | Normalized |
|---|---|---|
| Direction | `W`, `West` | `W` |
| Street type | `St`, `Street`, `ST` | `St` |
| Street type | `Ave`, `Avenue`, `AV` | `Ave` |
| Ordinal | `28TH`, `28th`, `1ST` | `28`, `1` |

### House number → range and side

```python
range_base = (house_number // 10) * 10   # floor to nearest 10
side = "odd" if house_number % 2 == 1 else "even"
```

`40` → `40s, even` (not `0s` — you floor to the number itself, not below it)
`349` → `340s, odd`
`480` → `480s, even`

### Noise suffix stripping

Everything after the street type token is irrelevant and discarded:
`Attn`, `APT`, `Apt`, `Unit`, `Ground Floor`, `Host`, `Suite`, `#`, etc.

A comma immediately after the street type is also stripped before noise detection.

### Unparseable addresses — flagged to dispatch, never silently dropped

A package whose address cannot be matched returns `None` for block_key. It still enters `cluster_packages` via lat/lng and clusters normally — DBSCAN uses coordinates, not block_keys. It is excluded from workload scoring only.

Crucially, it is **never silently dropped**. The sort orchestrator collects all unparseable packages and surfaces them as a dispatch warning before the day starts: TBA numbers, tote IDs, and the raw address so dispatch can investigate. A missing house number is flagged at higher severity than an unrecognized street type — a package with no house number is potentially undeliverable.

---

## 2026-05-26 — Why Regex Alone Cannot Parse All NYC Addresses

### The problem with pure regex for NYC

A regex parser works well for a narrow, structured delivery zone (Manhattan west side, numbered streets and avenues). But as a multi-tenant system serving all of NYC, the address formats are too varied:

- **Queens hyphenated numbers**: `104-24 114th St` — `int("104-24")` raises `ValueError`
- **Named streets**: `500 Broadway`, `1 Madison Ave` — no numbered street component
- **Brooklyn avenues**: `1230 Avenue U` — "Avenue" is not a type suffix, it's part of the name
- **West End Ave**: `100 West End Ave` — "West" here is part of the street name, not a direction
- **Fractional/alphanumeric**: `132 1/2 E 62nd St`, `20-F Greenpoint Ave`

A regex that handles all of these without false positives would be extremely complex and fragile to maintain.

### The solution: GeoClient at ingestion time, not sort time

NYC's GeoClient API (NYC Department of City Planning) is a free official service that normalizes any NYC address string into a canonical form — handling all five boroughs, all edge cases, all historical variants.

The concern with external APIs at sort time was latency and failure risk. The solution: move enrichment to **manifest ingestion time**:

1. Dispatch uploads the manifest (1–1.5 hrs before sort, 3–4 hrs before walkers start)
2. A Celery task runs GeoClient enrichment in the background immediately
3. Dispatch gets an immediate "in progress" confirmation and continues other work
4. When enrichment completes, dispatch gets a notification: sort-ready or packages flagged
5. Sort time: all packages already have normalized addresses and block_keys — no API calls

### The regex parser as fallback

`derive_block_key.py` stays in place as a fallback for packages where GeoClient failed but the address is simple enough to parse. Best-effort derivation with a lower-confidence flag. No packages are silently lost.

### Why Celery, not FastAPI background tasks

FastAPI background tasks die if the server process restarts mid-enrichment. Celery tasks survive restarts, have built-in retry logic for transient failures, and use Redis (already in the infrastructure) as the broker. For a critical pre-sort operation, Celery is the right choice.

**Long-term fix:** Add the frontend build + S3 sync to CI so it runs automatically on every master merge, same as the backend deploy.

---

## 2026-05-27 — ADP Integration: Employee ID Storage and Verification Lifecycle

### Why we need to store ADP's associateOID on each employee

ADP's timecard write API (`Time Cards API`) requires the `associateOID` — ADP's internal UUID for a worker — to target the correct record. It does not accept names or emails. Without storing this ID in our system at import time, we have no way to push shift timestamps to the right ADP worker record during timecard sync.

### The hr_system_id_* naming pattern

External HR system IDs are stored as `hr_system_id_<source>` columns on the `employees` table — one column per HR platform. This is intentional:

- A single `hr_system_id` + `hr_system_source` pair would only allow one HR system per employee
- Separate columns (`hr_system_id_adp`, `hr_system_id_workday`, etc.) allow one employee to exist in multiple systems simultaneously — useful during platform migrations or if a company uses more than one HR tool
- Each column is independently nullable/verifiable without affecting the others

### Why NOT NULL — and what the backfill means

`hr_system_id_adp` is `NOT NULL`. This forces the question of "does this employee have an ADP ID?" at import time, not at the moment a timecard sync is attempted. Discovering a gap when timecards need to be pushed is the worst possible time.

Employees who existed before ADP integration was built are backfilled with generated UUIDs (placeholder values). These are not real ADP IDs — they are distinguishable from verified ADP IDs via the `hr_system_id_adp_verified` flag.

### The verification flag and its lifecycle

`hr_system_id_adp_verified` starts as `false` for all employees — including those whose ID was populated from an ADP CSV export. A populated ID is not the same as a confirmed working ID.

The flag flips to `true` only after a live ADP Workers API round-trip (`GET /hr/v2/workers`) confirms that the stored `associateOID` resolves to an active ADP worker record. This is **eager verification** — it runs as a background Celery batch job when the company completes the ADP OAuth connection, before the first shift day. Dispatch sees a "X of Y employees ADP-verified" count and can resolve gaps before they matter.

Timecard sync (`sync_adp_timecards.py`) skips employees where `hr_system_id_adp_verified = false` and surfaces them in a management warning. This is a management concern — ADP configuration and employee ID reconciliation is not dispatch's responsibility.

### What changed in BulkImportModal for ADP CSV exports

ADP exports are not formatted like a generic employee list. Three specific problems required handling:

1. **Split name columns.** ADP exports `First Name` and `Last Name` as separate columns. `parseObjects()` now detects these and combines them into `name` when a pre-combined `name` column is absent.

2. **ADP column aliases.** ADP uses column headers like `File #`, `Associate ID`, `Work Email`, `Business Phone`. These are added to the `ALIASES` map alongside our existing aliases.

3. **Role translation.** ADP job titles (`Delivery Associate`, `Dispatcher`, `DSP Owner`) don't match our role values (`walker`, `dispatch`, `management`). A `ADP_ROLE_MAP` lookup table translates them. Unrecognized titles fall back to `walker` and are highlighted in the preview step for manual correction — they are never silently dropped.

---

## 2026-05-27 — The Sort Pipeline: Orchestrator Design and Zone Persistence

### Why the sort pipeline is split into four pure functions

The sort pipeline (`cluster_packages → assign_clusters → tier1_verify → persist_zones`) is built as four separate pure functions instead of one monolithic function. Each stage:

- Takes explicit inputs, produces explicit outputs
- Has no side effects except `persist_zones` (which writes to DB)
- Can be tested independently with mock data
- Can be replaced without touching the others

This is especially important for `tier1_verify` — it runs a geometry check and produces a `VerificationResult`. The caller (the orchestrator) decides what to do with the result. Embedding that decision inside a single function would make it impossible to support the `force=True` override without deeply entangling business logic with geometry code.

### Why enriched packages live in Redis, not re-derived at sort time

Address enrichment (GeoClient API calls) takes 30–120 seconds for a full manifest. The sort pipeline needs to run fast — dispatch is waiting. The solution is to pre-compute enrichment during manifest upload (Celery task, async) and cache the result in Redis.

When the sort runs, it reads the cached `manifest:{company_id}:{date}` key in milliseconds. The sort itself is pure in-memory computation: DBSCAN, centroid math, polygon containment checks. No external API calls.

**Consequence:** sort requires enrichment to have completed first. If the Redis key is missing or expired (24h TTL), `run_sort` raises `SortError("no_manifest")` with a clear message. The frontend shows "enrich the manifest first."

### Why tier-1 failure blocks zone persistence by default

If any totes are flagged as misaligned, zones are not written. The `force=True` parameter lets dispatch explicitly override after reviewing.

This might seem overly strict. The reason: if a misaligned tote is physically corrected (packages moved to the right truck), the package distribution changes, and the zone polygons may shift. Writing zones before the correction means routing runs on an incorrect zone layout. The 409 Conflict + review flow ensures dispatch has seen the flags before zones are committed.

Forcing dispatch to actively choose `force=True` is a deliberate friction point. It creates an audit trail ("dispatch saw these flags and proceeded anyway") instead of silent acceptance.

### Why zone_date is a required column, not inferred from created_at

`TruckZone` originally had no date column. Re-sorts for the same day would stack up — you could not distinguish "today's zones" from "yesterday's zones" without looking at `created_at`, which is unreliable if sorts run near midnight or the server clock drifts.

`zone_date DATE NOT NULL` makes the intent explicit. `persist_zones()` receives it as a parameter from the sort orchestrator. `GET /sort/{date}` uses it directly. Re-sorts are idempotent per date: the old zones are soft-deactivated, new ones are written.

### Why old zones are deactivated, not deleted, on re-sort

Deleting old zones destroys the audit trail. If a sort runs at 7am with flagged totes and is forced through, then re-runs at 8am after corrections, dispatch may want to see what changed — which totes moved, which zones shifted. Soft deactivation (`is_active = False`) preserves the history without serving stale zones to the routing algorithm.

---

## 2026-05-27 — Location Profile System: Crowdsourcing, Verification, and the Global Library

### Why a two-tier system instead of one table with nullable company_id

The simplest design would be one `location_profiles` table with `company_id NULL` for global records. We rejected this for a fundamental reason: the codebase has a hardened invariant that every company-scoped query filters by `company_id`. A nullable `company_id` breaks that invariant — queries that filter `company_id = X` silently miss the global records, and queries that try to include global records have to write special-case logic.

Two tables keeps isolation intact: `location_profiles` (always has `company_id`), `location_profile_library` (never has `company_id`). The routing algorithm queries both explicitly and merges the results in the orchestrator. No invariant violations, no special-case query logic.

### The locking flow: crowdsourced consensus, not authority

A single captain cannot lock a profile. Building type status advances by accumulating agreements from multiple people: `pending → verified → locked`. The threshold (default 3 agreements) is company-tunable.

This models operational reality. A captain bulk-entering building types before day 1 might be wrong — they haven't made the deliveries yet. A walker who delivers to the building five times a week and has verified the type three times is more reliable. The crowdsourced threshold captures confidence level rather than relying on role hierarchy.

### Why editing an operational note un-verifies it

The `note_verified` flag means "a captain has reviewed this note and attests it's accurate." If the note text changes, that attestation is no longer valid — the captain hasn't reviewed the new text. Un-verifying on edit prevents a verified flag from surviving changes it was never applied to. Re-verification is a quick action (one POST call) that restores the audit trail after review.

### The nomination pipeline: why it's automatic on lock

Once a profile is locked, it's automatically set to `nomination_status = "nominated"`. Super admins see it in the nominations queue.

Why not require a captain to manually nominate? Because it would never happen. Captains are focused on daily operations. A profile that reaches locked status has already cleared the trust bar — nomination is a bureaucratic step, not a judgment call. Automating it ensures no valid profile sits idle in a company's database when it could be helping other DSPs entering the same delivery area.

### How company records shadow the global library

The routing algorithm (in `run_sort.py → _get_location_profiles()`) loads global library records first, then company records. When `assign_clusters` builds its `profiles_by_block` lookup, company records overwrite library records for the same `block_key`.

This is the shadow: if the company has a locked record for `W_36_St_410s_odd` saying `biz_security` (high_touch), but the library says `elevator` (standard), the company's experience wins. Their field data is more recent and specific to their operation.

If no company record exists, the library provides cold-start data. If neither exists, the routing algorithm falls back to raw package count and flags low confidence to dispatch.

---

## 2026-05-28 — NOT NULL migrations and constructor call audits

### The gap migrations can't close

When you add a NOT NULL column to a model via Alembic, the migration does three things:

1. Adds the column as nullable
2. Backfills existing rows with a default value
3. Alters the column to NOT NULL

This catches the DB layer. It does not catch Python-side omissions. Every
`db.add(ModelName(...))` call that doesn't pass the new field will compile and
run fine — until it hits the database at runtime and raises an IntegrityError.

The error is non-obvious in local dev because FastAPI drops CORS headers on
unhandled 500s. The browser reports a CORS error before you can see the real
IntegrityError in the backend logs.

### The audit pattern

After adding a NOT NULL column, run:

```python
import re
text = open('backend/app/routers/your_router.py').read()
blocks = list(re.finditer(r'db\.add\(YourModel\(', text))
for m in blocks:
    chunk = text[m.start():m.start()+400]
    if 'new_column' not in chunk.split('))')[0]:
        line = text[:m.start()].count('\n') + 1
        print(f'MISSING at line ~{line}')
```

Or grep across all routers:

```bash
grep -rn "db.add(ModelName(" backend/app/routers/ | grep -v "new_column"
```

Note: the grep only catches single-line matches. Use the Python regex approach
for multi-line constructor calls where `new_column` appears on a later line.

### The publish gate pattern

A boolean action gate should be derived from whether the action itself succeeded,
not from downstream side effects. In `DispatchDashboard`, "Post Final Crews" was
gated on `confirmations.length > 0` — but confirmations are populated by a
page-load fetch that returns data from any prior date's publish. The gate was
effectively measuring "did a publish ever succeed for this date" rather than
"did the current publish succeed".

The fix is a dedicated `isPublished` state flag set only inside the `try` block
of the publish call. Side effects (populating confirmations, starting polling)
follow on success. The gate never fires on failure.

### The protocol_reminder pattern: derived, not stored

The `BUILDING_TYPE_PROTOCOL` dict in `schemas/location_profile.py` maps `building_type → reminder string`. The reminder is appended to API responses by `from_orm_with_protocol()` at serialization time.

**Why not store it?** Protocol reminders are fixed operational guidance. "Photo at front door" does not change based on company data. Storing it would require a migration every time the text is updated, and creates a risk that stored text diverges from the canonical definition. Deriving at serialization always serves the current guidance.

**Why in the schema file, not the model?** Models represent database rows. Protocol reminders are not database concepts — they're presentation layer guidance. Putting the lookup table and derivation logic in the schema file keeps the model clean and the schema self-contained for response building.

---

### Black-box import pattern for proprietary code

When part of a codebase is gitignored for competitive reasons, the public repo
should expose as little information as possible about what's hidden. The naive
approach — individual `try/except ImportError` blocks in `main.py` — leaks all
proprietary module names into a public file.

The black-box pattern solves this with a single entry point in the private repo:

```python
# main.py (public) — reveals nothing about what's inside
try:
    from asheflow_private.register import register_proprietary_routers as _register
except ImportError:
    _register = None

if _register:
    _register(router, dependencies)
```

```python
# asheflow_private/register.py (private) — module names stay confidential
def register_proprietary_routers(router, configured):
    from app.routers import dispatch, training, field_ops, walker_routes
    router.include_router(dispatch.router, dependencies=configured)
    ...
```

If the private package isn't present the backend starts cleanly — proprietary
routes are simply absent. Adding new proprietary routers only requires editing
`register.py`; `main.py` never changes.

---

### Why FastAPI 500s appear as CORS errors

FastAPI applies CORS middleware to responses it controls. When an unhandled
exception bubbles past all middleware (a 500 that isn't caught by the route
handler), FastAPI emits the 500 response before the CORS middleware gets a
chance to add `Access-Control-Allow-Origin` headers.

The browser receives a response with no CORS headers and reports a CORS error
— even though the real problem is a 500. The actual error is in the backend
logs, not in the browser console.

**Consequence:** A `company_id=None` IntegrityError in a route handler will
show as "CORS error" in the browser. Always check backend logs first before
investigating CORS configuration.

**Prevention:** Handle exceptions in route handlers with `try/except` and
return a proper `HTTPException`. Never let IntegrityErrors, ValueError, or
similar reach the unhandled exception boundary.

---

### Reverse proxy and TLS on EC2 (Caddy pattern)

A FastAPI backend running in Docker on an EC2 listens on an internal port
(8000). To be reachable via HTTPS, a TLS-terminating reverse proxy must sit
in front of it and listen on ports 80 and 443.

Caddy is the simplest option for this setup:
- Auto-provisions and auto-renews Let's Encrypt certificates
- HTTP-01 ACME challenge requires port 80 to be open and DNS to point to the server
- Two-line `Caddyfile`: domain + `reverse_proxy backend:8000`
- Certificate state is persisted in a named Docker volume — loss of the volume
  means re-provisioning, which works but hits Let's Encrypt rate limits if done
  repeatedly

The backend port should **not** be exposed externally (remove it from the base
`docker-compose.yml`). Only Caddy should accept inbound traffic on 443. Re-expose
the backend port in `docker-compose.override.yml` for local dev only.

An `API_DOMAIN` environment variable makes the same `Caddyfile` work for both
staging and prod — only the value in `.env` differs.

---

### Cognito OAuth federation: how it connects to existing accounts

Cognito supports identity federation (Discord, Google, etc.) alongside
username/password auth on the same user pool. For AsheFlow, federation is
a convenience feature — it doesn't create new accounts, it lets existing
employees sign in with a social identity whose email matches their record.

**How the linking works:**
1. Employee signs in via Discord/Google through the Cognito hosted UI
2. Cognito calls the identity provider, receives an email claim
3. Cognito creates or finds a user pool entry for that email
4. The backend receives an ID token; `_resolve_employee_from_cognito` looks up
   `Employee.email == token.email`
5. On first match, `cognito_sub` is stamped on the employee row for future
   fast-path lookups

**What Cognito requires for federation to work:**
- Identity providers configured on the user pool (Discord as OIDC, Google as Google)
- Hosted UI domain provisioned (`<prefix>.auth.<region>.amazoncognito.com`)
- App client with `AllowedOAuthFlowsUserPoolClient: true`, `code` flow,
  `openid email profile` scopes, and callback URLs registered for each environment
- `VITE_AWS_DOMAIN` must be set to the hosted UI domain so Amplify knows where
  to redirect

**Why Amplify's `oauth` config causes 400 on page load without the above:**
Amplify checks for an authorization code in the URL on every page load (to
handle the redirect back from the identity provider). This check hits the
Cognito token endpoint. If the app client doesn't have OAuth flows enabled,
Cognito returns 400 on that check — every page load, whether or not the user
clicked a social login button.

---

## 2026-05-29 — Proxy headers, schema drift, and workflow state machines

### Why mixed-content errors come from the server, not the bundle

When a React SPA sends API requests to an `https://` URL, "mixed content" means
the browser received an `http://` URL somewhere in the response and refused to
follow it. The instinct is to check the frontend bundle — is the `VITE_API_URL`
set correctly?

But Vite hashes bundle content. If the hash is unchanged across builds, the
content is unchanged, which means the secret was already correct. The error is
coming from somewhere else.

The real source: FastAPI (via Starlette) uses the **request scheme** when
building redirect URLs. When Caddy proxies over plain HTTP inside Docker, FastAPI
sees `scheme=http`. Any `307 Temporary Redirect` — including the trailing-slash
redirect from `GET /trucks` to `GET /trucks/` — produces a
`Location: http://...` header. The browser blocks it as mixed content.

**Fix:** `ProxyHeadersMiddleware` from Uvicorn reads the `X-Forwarded-Proto`
header Caddy adds and patches `request.scope["scheme"]` before any handler runs.

```python
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")
```

`trusted_hosts="*"` is safe because the backend port is not publicly accessible —
only the reverse proxy can reach it. If the backend were exposed directly to the
internet, this would allow header spoofing and you'd need to list trusted IPs.

**Debugging rule:** If you see mixed-content errors against an `https://` API,
check the Network tab for 3xx responses with `http://` Location headers before
touching the frontend or CI configuration.

---

### Why Vite bundle hashes don't change when secrets are "wrong"

A Vite production build hashes the content of each bundle file and embeds that
hash in the filename (`index-Cra3Qo3t.js`). The same content always produces the
same hash.

If you change a `VITE_*` environment variable but the hash doesn't change, the
secret value was already the same as before the change. This means either:
1. The secret was already correct and something else is causing the error, or
2. The variable isn't being read at build time (wrong name, missing `VITE_` prefix)

In our case: `VITE_API_URL` was already `https://` from a prior CI run. Multiple
re-deploys produced the same hash. The bundle was never the problem.

---

### Out-of-band schema drift: the migration gap that direct ALTER creates

Alembic migrations record every schema change in version-controlled files. When
staging runs `alembic upgrade head`, it applies every migration in order and ends
up with exactly the schema described by the migration chain.

If you run `ALTER TABLE` directly on the dev database without writing a migration,
staging (and any fresh database) will be missing that change. Everything works on
dev because the change is already there. Staging fails with a constraint violation
or missing column, and the error message points at the application code — not at
the schema drift.

**Signs of schema drift:**
- `CheckViolation` errors that can't be reproduced locally
- `IntegrityError` for a constraint that "doesn't exist in the model"
- `column does not exist` errors on a column that was added by `ALTER TABLE` on dev

**Protocol:** Never run `ALTER TABLE` on a dev database without immediately writing
an Alembic migration. Even for "temporary" changes or "I'll do it properly later"
fixes.

**Note on CheckViolation → CORS error:** A `CheckViolation` from SQLAlchemy
reaches FastAPI as an unhandled exception, which produces a 500. FastAPI strips
CORS headers from 500 responses. The browser reports it as a CORS error. Always
check backend logs when you see CORS failures — they may be masking database errors.

---

### How `aws` CLI is unavailable in SSM RunShellScript

AWS Systems Manager's `Run Command` (SSM RunShellScript) executes scripts inside
the ssm-agent process on the EC2 instance. The agent runs with a minimal
environment — it does not source the user's shell profile, so the `aws` CLI is
not in PATH even if it's installed and available to the `ec2-user` interactively.

**Workaround:** Use `curl` with a presigned S3 URL instead of `aws s3 cp`.
Generate the presigned URL locally:

```bash
aws s3 presign s3://bucket/key --expires-in 3600
```

Then pass the URL to `curl` in the SSM command:

```bash
curl -s "https://bucket.s3.region.amazonaws.com/key?X-Amz-..." -o /tmp/file
```

The same issue applies to any CLI tool not in the default PATH — use absolute
paths (`/usr/local/bin/aws`) or use HTTP-based alternatives.

---

### Workflow state machines: deriving step from durable DB state

Multi-step workflows (Run → Publish → Finalize) need answers to two questions:
1. What step is the workflow on right now?
2. Which operations are valid from this step?

A common frontend mistake is tracking this in React state (`const [isPublished, setIsPublished] = useState(false)`). This is fragile:
- State is lost on page reload
- Two browser tabs can drift out of sync
- State derived from a count of related rows (e.g., "published if confirmations > 0")
  can be wrong if those rows exist for other reasons

**The right approach:** persist the workflow step in the database and derive
frontend state from what the backend returns.

For the dispatch workflow, `TruckAssignment.status` (`planned` / `active` /
`completed`) was the right place — it already had the correct semantics in its
check constraint but was never updated. Now:
- `planned` → dispatch ran, not yet published
- `active` → published to Discord, confirmation window open
- `completed` → final crews posted, workflow done

The GET endpoint derives a single `workflow_status` field from the aggregate of
truck statuses. The frontend reads this field and computes a `workflowStep`
constant — not a state variable, because it doesn't need to change independently
of the data it's derived from.

```typescript
const workflowStep: WorkflowStep = !dispatchData
  ? 'none'
  : dispatchData.workflow_status === 'finalized' ? 'finalized'
  : dispatchData.workflow_status === 'published' ? 'published'
  : 'dispatched';
```

Each button is then gated on exactly one step:
```typescript
disabled={isLoading || workflowStep !== 'none'}        // Run Dispatch
disabled={isPublishing || workflowStep !== 'dispatched'} // Publish
disabled={isFinalizing || workflowStep !== 'published'}  // Post Final Crews
```

The backend gates mirror this: each endpoint checks the current status set and
rejects with 409 if the operation is out of sequence or already completed.

---

### The `allow_*` dep type trap: RoleChecker returns dict, not Employee

FastAPI dependencies have a return type. `RoleChecker(["management", "admin"])` is a
callable that validates the Cognito JWT and returns the decoded token — a plain `dict`.
It does **not** return an `Employee`.

The trap: a function parameter typed as `caller: Employee = Depends(allow_management)`
compiles fine and passes type checking because FastAPI doesn't enforce return types on
dependencies at startup — it only resolves them at request time. The endpoint will
appear to work until it reaches a line that accesses any attribute like `caller.company_id`
or `caller.id`, at which point Python raises `AttributeError: 'dict' object has no
attribute 'company_id'`.

This is a **silent runtime bomb**: the error only fires when a management-role user
hits that specific endpoint. Any test that doesn't exercise the attribute access (e.g., a
test that stubs out the dep) will pass cleanly.

**Correct pattern when you need both role enforcement and an Employee:**
```python
def my_endpoint(
    db: Session = Depends(get_db),
    _: dict = Depends(allow_management),        # role gate — returns dict, discard it
    caller: Employee = Depends(get_caller_employee),  # Employee row with company_id
):
```

The `_: dict` convention makes the intent explicit: we want the side effect (reject if
wrong role) but don't need the return value. `get_caller_employee` runs a second dep in
parallel and provides the typed Employee object.

**When `get_caller_employee` alone is sufficient:** if the endpoint only needs
`driver`/`trainer`/`management` or higher and you just want to restrict by role, you can
pass the roles to `get_caller_employee` via a role-aware dep variant, or keep the role
checker separate. But never assign the `RoleChecker` result to a typed `Employee` parameter.

---

### The `model_dump()` company_id gap in INSERT operations

Pydantic request schemas intentionally exclude `company_id` — it must come from the
authenticated caller, never from client input. This is correct security design: a client
that can inject `company_id` into a request body could write rows belonging to other tenants.

The gap arises when the INSERT is written as:
```python
row = SomeModel(**payload.model_dump())
db.add(row)
```

If `SomeModel` has `company_id NOT NULL` but the payload schema excludes it, SQLAlchemy
sets the column to `None` and the INSERT raises an `IntegrityError` at the database level.
Locally this surfaces as a 500. In a browser, FastAPI drops CORS headers on unhandled 500s,
so it can look like a CORS error — check backend logs first.

**The fix:** append `company_id` as a keyword argument after the spread:
```python
row = SomeModel(**payload.model_dump(), company_id=caller.company_id)
db.add(row)
```

Python's `**` unpacking allows additional keyword arguments after a dict spread, provided
they don't collide with keys already in the dict (they won't, since `company_id` is
excluded from the schema by design).

**Scanner script (from CLAUDE.md):** After writing any new INSERT, run the scanner to
catch any `db.add(Model(` calls that don't include `company_id` in the block:
```python
import re
text = open('backend/app/routers/your_file.py').read()
for m in re.finditer(r'db\.add\((\w+)\(', text):
    chunk = text[m.start():m.start()+600]
    block = chunk[:chunk.find('))')] if chunk.find('))') != -1 else chunk
    if 'company_id' not in block:
        print(f'line {text[:m.start()].count(chr(10))+1}: {m.group(1)} missing company_id')
```

---

### Latent NameError: private helpers that reference outer-scope variables

A private helper function (not a FastAPI endpoint) is just a regular Python function. It
doesn't have access to the caller's request context, dependencies, or any variable from
the endpoint that calls it — only what's in its parameter list.

The latent bug pattern:
```python
# The endpoint has 'caller' in scope
def record_confirmation(caller: Employee = Depends(get_caller_employee), ...):
    reassignment = _reassign_trainee_on_trainer_decline(db, trainer_id, date)

# The helper was written as if it could access 'caller' — it cannot
def _reassign_trainee_on_trainer_decline(db, trainer_id, dispatch_date):
    n = Notification(
        company_id=caller.company_id,   # NameError: 'caller' is not defined
        ...
    )
```

Python does **not** raise this at import time or at the time the helper is defined. It only
raises `NameError` when the line is actually executed — when `record_confirmation` calls the
helper and the helper reaches that line. If the code path is exercised rarely (e.g., the
decline flow had never been triggered since the function was written), the bug sits dormant
indefinitely.

**The fix:** pass `company_id` explicitly as a parameter:
```python
def record_confirmation(caller: Employee = Depends(get_caller_employee), ...):
    reassignment = _reassign_trainee_on_trainer_decline(db, trainer_id, date, caller.company_id)

def _reassign_trainee_on_trainer_decline(db, trainer_id, dispatch_date, company_id):
    n = Notification(company_id=company_id, ...)
```

**Discipline:** every private helper that needs `company_id` must receive it as an
explicit parameter — never count on it being available from an enclosing scope. Python
closures would only work if the helper were defined *inside* the endpoint function (a nested
function), which is not how these routers are structured.

---

### Two-pipeline sort sequencing: truck sort vs. walker sort

The sort pipeline runs in two distinct phases, separated in time and in HTTP surface:

**Phase 1 — Truck sort** (morning, at the warehouse):
```
POST /sort/upload         → parse manifest, async GeoClient enrichment
GET  /sort/manifest/{date}/status  → poll until "ready"
POST /sort/run            → DBSCAN cluster → assign clusters to trucks
                            → tier-1 tote verify → persist TruckZone rows
```
Output: `TruckZone` rows, one per cluster. Each stores `package_tbas` (list of TBA strings in that cluster) and `zone_date`.

**Phase 2 — Walker sort** (later, after trucks arrive at the station):
```
POST /walker-routes/commit → load packages from Redis via TruckZone.package_tbas
                             → run route_sort → persist WalkerRoute + WalkerTrip rows
```
The trainer distributes that truck's packages among the walkers boarding it. No package addresses come from the HTTP request — they come from the Redis manifest filtered by the TBAs stored on the TruckZone.

**Why this split?** Trucks go out first. Walker assignment happens later when the trainer physically sees which walkers are boarding which truck. Trying to do both at once would require blocking the entire dispatch flow until all walkers are physically present at each truck.

**The data handoff:** `TruckZone.package_tbas` is the link between the two phases. It lets the walker sort know exactly which packages belong to this truck without re-running the clustering or re-supplying data from the client.

---

### Address ephemerality — why addresses never hit the DB or response bodies

ADR-096 established that package addresses are ephemeral: they are used for computation (GeoClient enrichment, DBSCAN clustering, block_key derivation, route sort) but never stored in PostgreSQL and never returned in API responses.

**Why?** Delivery addresses are PII. Storing them in the operational DB creates compliance obligations, increases breach impact, and requires retention policy management. Keeping them in Redis (short TTL, easy to expire) limits the exposure window.

**In practice this means:**
- `PackageInput.address` is used by the route sort algorithm, never written to any DB table
- `WalkerRoute`, `WalkerTrip`, `TruckZone` contain TBA numbers and bag IDs — not addresses
- `CommitSortResponse` contains TBA numbers — not addresses
- The `dropped_tbas` list in `CommitSortResponse` is identifiers, not addresses

**The sentinel for reviewers:** if you see `address` being added to a `db.add(...)` call in the sort or walker route routers, it is a bug. Addresses must only travel through in-memory objects during computation.

---

### Manifest upload data flow — the enriching sentinel pattern

The manifest upload flow has a subtle ordering requirement:

```
1. Parse file synchronously (validate extension, size, column structure)
2. SET manifest_enriching:{company_id}:{date} key (5-min TTL)   ← MUST come before step 3
3. Dispatch Celery task
4. Return 202
```

**Why set the sentinel before dispatching?** The status endpoint checks Redis keys in this order:
1. `manifest:{company_id}:{date}` → `"ready"`
2. `manifest_enriching:{company_id}:{date}` → `"enriching"`
3. `manifest_failed:{company_id}:{date}` → `"failed"`
4. (nothing) → `"not_found"`

Dispatch dispatches the Celery task (a Redis/queue write), then the task starts asynchronously. There is a gap between the dispatch call returning and the task actually starting. If the frontend polls the status endpoint in that gap and the sentinel is not yet set, it sees `"not_found"` — which the user interprets as "nothing was uploaded".

Setting the sentinel first eliminates this window entirely. The 5-minute TTL is long enough to survive task startup in any realistic environment; the task clears the sentinel implicitly by writing the manifest key.

**Failure signal:** if the Celery task crashes, it writes `manifest_failed:{company_id}:{date}` (24h TTL) so the status endpoint can return `"failed"` instead of silently falling through to `"not_found"`. On success, the task deletes any stale failed key so a re-upload after a failure starts clean.

---

### File upload size limiting — read once, write from buffer

When an uploaded file needs to be size-checked before writing to disk:

```python
# Read up to limit+1 bytes — if we get limit+1, the file is over the limit
contents = file.file.read(MAX_UPLOAD_BYTES + 1)
if len(contents) > MAX_UPLOAD_BYTES:
    raise HTTPException(status_code=413, detail="File too large")

# Write the buffer (not the stream — the stream is now exhausted)
with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
    tmp.write(contents)
```

The stream from `UploadFile.file` is a standard file-like object. After calling `read()`, the stream position is at the end — there is nothing left to read. If you then try to use `shutil.copyfileobj(file.file, tmp)`, it copies zero bytes.

The buffer in `contents` is what you have. Write from that.

---

### Concurrent write safety — partial unique indexes vs. application locks

**The problem:** two concurrent `POST /sort/run` requests for the same company+date will both:
1. Read existing active zones and mark them `is_active = False`
2. Insert new zone rows

Since both read the same "no active zones" state, both insert, and both try to commit — leaving double the active zone rows.

**DB-level defense:** a partial unique index catches the second insert as an `IntegrityError`:
```sql
CREATE UNIQUE INDEX uq_truck_zones_active_label
ON truck_zones (company_id, zone_label, zone_date)
WHERE is_active = true
```
Zone labels are unique per run (truck name + overflow/sequence suffix), so a duplicate run generating the same labels is caught. The second transaction gets an `IntegrityError` rather than silently committing.

**Why zone_label and not truck_id?** A truck can have multiple active zones (overflow clusters). A unique index on `(company_id, truck_id, zone_date)` would block that. Labels are unique per run across all clusters; the label-based constraint catches duplicate runs without constraining legitimate overflow.

**Application-level lock (future improvement):** a Redis SETNX lock would give a better user experience — a 409 "sort already in progress" rather than a 500 IntegrityError. The DB index is the safety net; an app-level lock would be the UX layer on top. Do not rely solely on the UX (disabling the button) because the button state is not a concurrency guarantee.

---

### Surfacing operational metadata to end users — the `dropped_tbas` pattern

When a batch operation partially fails, the right response is:
1. Proceed with the successful subset
2. Return both the results AND the identifiers of what was excluded

For walker sort, packages that failed address enrichment are dropped silently from the route distribution. A count (`packages_dropped: int`) tells the trainer something went wrong. The full list (`dropped_tbas: list[str]`) tells them *exactly* which packages to handle manually.

The principle: trainers work with physical packages labeled with TBA numbers. Abstract counts are not actionable; specific identifiers are. Design responses to give operators the level of specificity they need to take action without looking something up.

This pattern generalizes: any endpoint that processes a batch and may partially succeed should return both the successes and the identifiers of failures. `packages_dropped: int` alone is a bad design for this domain.

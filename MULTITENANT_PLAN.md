# Multi-Tenant Architecture Plan

**Last updated:** 2026-05-08  
**Status:** Complete — Phase 1 (schema), Phase 2 (router isolation), and Phase 3 Steps 1–6 (provisioning backend + super admin frontend + company config management) all done.

**All architectural decisions locked:**
- Single Cognito pool, `super_admin` group added manually in AWS console
- `get_super_admin` dependency — JWT only, no Employee row required
- Super admin UI lives at `/superadmin`, separate layout from company admin dashboard
- Company admins can edit their own config; `invite_expiry_days` locked to super admin only
- DB config overrides `constants.py` when non-null (null-fallback pattern)
- Bootstrap endpoint sends invite token — first admin registers through the existing flow
- Company UUID is immutable after creation

---

## What multi-tenancy means in this system

AsheFlow uses a **single-database, single-pool, row-level isolation** strategy. Every table has a `company_id` UUID column. Every query filters by it. There is one Cognito user pool shared across all tenants — employees are distinguished by which company their Employee row belongs to, and by which Cognito group (role) they are in.

The goal: a DSP company ("tenant") onboards, gets a UUID, and from that point forward all their data — employees, trucks, dispatch, training, field ops — is invisible to every other tenant, enforced at the query layer.

---

## What is already done

- **Schema (Phase 1):** `company_id` column on all 32 tables. `Company`, `CompanyConfig`, `CompanyZone` models exist and are well-designed.
- **Router isolation (Phase 2):** All router queries now filter by `company_id`. Notification fanouts scoped. New rows stamped. Audit calls use `caller.id` / `caller.company_id`.
- **Seed company:** One company (`a0000000-0000-0000-0000-000000000001`) was inserted directly into the DB during Phase 1. It is the only tenant right now.
- **`get_caller_employee`:** Resolves JWT → Employee row → `company_id`. This is the auth chain for all company-scoped endpoints.

---

## What is missing

Everything related to **provisioning** a new tenant:

1. No way to create a `Company` row through the API
2. No super admin identity — `admin` is the highest role and it belongs to a company
3. No first-admin bootstrap — no way to invite the first employee of a new company
4. `get_caller_employee` would 403 a super admin (requires an Employee row)

---

## The full scope — what needs to be built

### Step 1 — Super admin Cognito group

**What:** Add a `super_admin` group to the existing Cognito user pool. Manually add the platform owner's Cognito user to it.

**Why:** The existing JWT verification already extracts `cognito:groups` from the token. `RoleChecker(["super_admin"])` works today without any code changes — it's just a string match against the groups list. Adding the group in Cognito is a one-time manual action via the AWS console or CLI.

**Decision already made:** Use the existing pool, not a separate pool. The super admin is a Cognito user like any other — they just have a different group and no Employee row.

**No code changes needed for this step.** Just an AWS config action.

---

### Step 2 — `get_super_admin` dependency in `deps.py`

**What:** A new FastAPI dependency that reads the JWT groups and returns the Cognito claims dict if the caller is `super_admin`. Raises 403 otherwise. Does NOT require an Employee row.

```python
def get_super_admin(current_user: dict = Depends(get_current_user)) -> dict:
    if "super_admin" not in current_user.get("cognito_groups", []):
        raise HTTPException(status_code=403, detail="Super admin access required.")
    return current_user
```

**Why:** `get_caller_employee` cannot be used for super admin endpoints — it enforces that an Employee row exists, and the super admin has none. The super admin operates at the platform level, not the company level. They need their own dependency that stops at the JWT and never touches the employees table.

**Decision to make:** Should `get_super_admin` also be available to company-level admins in addition to `super_admin`? No — keep it exclusive. Company admins use `get_caller_employee`. Mixing them creates ambiguity about which company_id applies.

---

### Step 3 — Companies router (`POST /admin/companies`)

**What:** A new router at `/admin/companies`, protected entirely by `get_super_admin`. Three endpoints to start:

1. `POST /admin/companies` — create a new tenant
2. `GET /admin/companies` — list all companies (super admin dashboard)
3. `GET /admin/companies/{company_id}` — get one company with its config

**What `POST /admin/companies` does:**
- Accepts: `name`, `slug`, `amazon_dsp_code` (optional), `timezone`
- Creates the `Company` row (UUID auto-generated)
- Creates a default `CompanyConfig` row for the same company (all nullable fields — falls back to hardcoded defaults in `constants.py` until configured by the company admin)
- Returns the new company with its UUID

**Why create `CompanyConfig` immediately:** Every service that reads config (dispatch weights, training thresholds, etc.) will need to do a `db.query(CompanyConfig).filter(...)` eventually. Creating it empty at provisioning time means services never have to handle the "config row doesn't exist" case — they always find a row, just with nullable fields.

**Decision to make:** Should slug be validated as URL-safe (lowercase, hyphens only)? Yes — slug is used for subdomain routing in the future. Enforce `^[a-z0-9-]+$` at the Pydantic layer.

**Decision to make:** Should `POST /admin/companies` also create the first admin employee for that company, or is that a separate step? Recommendation: **separate step** (Step 4 below). The company creation is a pure data operation. Bootstrap is a distinct action with its own email flow. Combining them makes the endpoint harder to re-run if something fails mid-way.

---

### Step 4 — First admin bootstrap (`POST /admin/companies/{company_id}/bootstrap`)

**What:** A super-admin-only endpoint that provisions the first company-level `admin` employee for a newly created company. This employee becomes the tenant owner — they can then invite all other employees using the existing invite flow.

**What it does:**
- Accepts: `name`, `email`
- Creates an `Employee` row with `role="admin"`, `company_id=<the new company>`, `account_status="not_invited"`
- Generates an invite token (same mechanism as `registration.py`)
- Sends the invite email
- Returns the employee record

**Why this is separate from company creation:** The company might be created first for configuration purposes before the admin is known. Also, if the email delivery fails, the company row still exists — the super admin can re-trigger bootstrap without recreating the company.

**Why not reuse `POST /employees` + `POST /registration/invite`:** Those endpoints require a `caller: Employee` from the same company. At bootstrap time, there is no employee in the company yet. The super admin has no Employee row. A dedicated bootstrap endpoint breaks the circular dependency: to invite the first admin you need an admin, but to get an admin you need to invite them.

**Decision to make:** Should the bootstrap endpoint also create the Cognito user immediately (via `AdminCreateUser`), or send an invite link that goes through the registration flow? Recommendation: **send an invite token** — same flow as every other employee. The first admin goes through `/register?token=...` just like everyone else. This keeps one code path for Cognito account creation.

---

### Step 5 — Super admin frontend (minimal)

**What:** A simple super admin UI — not part of the main app, can be a separate route or a protected section of the existing admin dashboard. Needs:

1. A "Companies" list page showing all tenants (name, slug, status, created_at)
2. A "Create Company" form (name, slug, DSP code, timezone)
3. A "Bootstrap Admin" form per company (name, email for the first admin)
4. A "View" page per company showing its config values

**Why minimal:** This is an internal operations tool. It doesn't need polish — it needs to work reliably and be protected. The super admin is the platform owner (you), not a customer.

**Decision: separate route (`/superadmin`) with its own layout.** ✅ The super admin context is fundamentally different from the company admin context — mixing them in one dashboard creates visual confusion and risks accidentally exposing super admin actions to company admins if a role check is missed.

**How does the frontend know it's talking to a super admin?** The existing auth flow puts `cognito:groups` in the JWT. After login, the app reads the groups and routes accordingly. A `super_admin` group check in the router guard is enough — same pattern as the existing role-based routing.

---

### Step 6 — Company config management (`PATCH /admin/companies/{company_id}/config`)

**What:** Allow the super admin (or eventually the company admin themselves) to update a company's `CompanyConfig` — operational parameters like shift times, dispatch weights, training thresholds. Right now these are hardcoded constants in `constants.py`. The `CompanyConfig` model already has columns for all of them.

**Why this is Step 6 and not earlier:** The provisioning pipeline works without it — the defaults in `constants.py` are reasonable. Config management is a "nice to have" at launch, not a blocker for onboarding new tenants. It becomes important once a second tenant needs different operational rules.

**Decision: company admins can edit their own config.** ✅ Super admins can edit any company's config. A small set of platform-level fields (defined below) are locked to super admin only. The PATCH endpoint uses an OR-check: `super_admin OR (admin AND caller.company_id == target_company_id)`, with field-level enforcement for the locked set.

Each config field will have a human-readable label and explanation so non-technical company admins understand what they are changing. These descriptions live in the frontend alongside each input.

**Super-admin-only fields** (platform-level, not operational):
- `invite_expiry_days` — affects token security posture across all tenants; not an operational tuning knob
- Any future fields that affect billing, compliance, or platform limits

**Company-admin-editable fields** (all others):
- Shift timing: `shift_start`, `shift_end`, `checkin_open`, `checkin_close`
- Training rules: `graduation_assignments`, `debt_escalation_threshold`, `phase4_pass_score`, `underperforming_trainer_threshold`, `max_training_phase`
- Crew requirements: `min_trainers_per_truck`, `min_walkers_per_truck`
- Dispatch weights: all `dispatch_weight_*` and bonus/penalty fields
- Walker rating: `rating_window_hours`, `flag_threshold`
- Driver check-ins: `driver_checkin_count`

**Decision: DB overrides constant when non-null.** ✅ Services read config as `company_config.field or DEFAULT_CONSTANT`. The `CompanyConfig` row is always present (created at bootstrap) but all fields start null — the system falls back to `constants.py` values until the company admin explicitly sets them. No migration needed for the seed company.

---

## Config field reference (for Step 6 UI copy)

These descriptions appear next to each config input in the company admin settings page.

| Field | Label | Description | Default |
|-------|-------|-------------|---------|
| `shift_start` | Shift Start Time | The time drivers are expected to begin their shift at the offsite. | 07:00 |
| `shift_end` | Shift End Time | The expected end of the working shift. | 18:00 |
| `checkin_open` | Check-in Opens | Earliest time the morning check-in photo is accepted. | 06:30 |
| `checkin_close` | Check-in Closes | Latest time the morning check-in photo is accepted. Submissions after this are flagged. | 07:45 |
| `rating_window_hours` | Walker Rating Window (hours) | How many hours after the driver's departure a walker presence rating can be submitted. Submissions outside this window are rejected. | 6 |
| `invite_expiry_days` | Invite Link Expiry (days) | 🔒 Super admin only. How many days an invite link remains valid before it expires. | 7 |
| `min_trainers_per_truck` | Min Trainers per Truck | Minimum number of trainer-role employees required on a truck before dispatch considers it adequately staffed for training. | 2 |
| `min_walkers_per_truck` | Min Walkers per Truck | Minimum number of walker-role employees required on a truck. Dispatch will warn if this threshold isn't met. | 3 |
| `graduation_assignments` | Graduation Threshold (days) | Number of successfully completed training days required before a trainee is eligible for graduation to driver. | 5 |
| `debt_escalation_threshold` | Debt Escalation Threshold (days) | Number of consecutive dispatch days a mandatory training task can be carried as incomplete before the training record is flagged for manager review. | 3 |
| `phase4_pass_score` | Phase 4 Pass Score (%) | Minimum score a trainee must achieve on Phase 4 (practical observation) to pass and proceed to graduation. | 90.0 |
| `underperforming_trainer_threshold` | Underperforming Trainer Threshold | Number of below-threshold training records before a trainer is flagged for review. | 3 |
| `max_training_phase` | Max Training Phase | The highest phase number in the training curriculum. Phase 5 is remediation-only and is never injected normally. | 4 |
| `dispatch_weight_driver` | Driver Preference Weight | How heavily the dispatch algorithm weights a driver's preference history when scoring crew combinations. Higher = more loyal pairing. | 0.70 |
| `dispatch_weight_trainer` | Trainer Preference Weight | Same as above for trainer-role employees. | 0.50 |
| `dispatch_weight_walker` | Walker Preference Weight | Same as above for walker-role employees. | 0.30 |
| `dispatch_mutual_bonus` | Mutual Preference Bonus | Bonus score added when two crew members have each other on their preference lists. | 0.10 |
| `dispatch_tridirectional_bonus` | Three-Way Preference Bonus | Bonus score added when three crew members all mutually prefer each other. | 0.20 |
| `dispatch_consecutive_penalty` | Consecutive Truck Penalty | Score deduction applied when an employee is assigned to the same truck they were on the previous day. Prevents crew fatigue from repetition. | 0.05 |
| `dispatch_weight_cap` | Maximum Preference Score Cap | The highest score any crew member can receive from the preference algorithm. Prevents extreme preference lock-in. | 0.85 |
| `flag_threshold` | Walker Rating Flag Threshold | Standard deviations below a driver's average walker rating that triggers an anomaly flag. | 1.0 |
| `driver_checkin_count` | Driver Mid-Shift Check-ins | Number of structured mid-shift check-ins expected from the driver during the day. | 4 |

---

## Execution order

| Step | What | Status | Blocker for |
|------|------|--------|------------|
| 1 | Cognito `super_admin` group (AWS console) | ✅ Done — already existed at precedence 1 | Steps 2–5 |
| 2 | `get_super_admin` dependency in `deps.py` | ✅ Done | Steps 3–4 |
| 3 | Companies router (`POST /admin/companies`) | ✅ Done | Step 4 |
| 4 | Bootstrap endpoint | ✅ Done | Step 5 |
| 5 | Super admin frontend at `/superadmin` | ✅ Done | End-to-end provisioning |
| 6 | Company config management | ✅ Done | Multi-company config divergence |

Steps 1–4 are purely backend. Step 5 is frontend. Step 6 is backend + frontend.

Steps 1 and 2 can be done in the same session. Steps 3 and 4 are naturally one PR. Step 5 can be minimal at first and expanded later.

---

## What does NOT need to change

- The JWT verification in `security.py` — `cognito:groups` is already extracted
- `RoleChecker` in `deps.py` — already does string matching against groups, `super_admin` just works
- All existing router isolation work (Phase 2) — none of that changes
- The invite/registration flow — the first admin uses it exactly like any other employee
- The seed company — it stays, all existing data is unaffected
- `get_caller_employee` — unchanged; super admin endpoints use `get_super_admin` instead

---

## Key invariants to maintain

1. **Super admin has no Employee row.** Never create one. If they need to act on a company's data operationally (rare), they do so through super admin endpoints that accept an explicit `company_id` parameter.
2. **Company UUID is set once and never changes.** It is the foreign key for every row in the system. Treat it as immutable after creation.
3. **CompanyConfig is always present for active companies.** The bootstrap step creates it. Services assume it exists and do a single query — they don't handle "config missing" gracefully.
4. **The invite flow is the only path to a Cognito account.** Super admin does not create Cognito accounts directly. They trigger the invite, the employee registers themselves.
5. **`get_super_admin` never falls back to company-scoped logic.** If the caller is both `super_admin` and somehow has an Employee row (shouldn't happen, but), treat them as super admin only on super admin endpoints. No blending of contexts.

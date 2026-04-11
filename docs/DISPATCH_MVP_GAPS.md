# AsheFlow Dispatch — MVP Gap Analysis
_Last updated: 2026-04-10 (Phase 2 Field Ops complete)_

This document tracks what is built, what is missing, and what the priority order is to reach a shippable MVP for the dispatch system. It should be updated as gaps are closed.

---

## What Is Built (as of 2026-04-06)

| Component | Status | Notes |
|---|---|---|
| SQLAlchemy models (Employee, Truck, TruckAssignment, AssignmentMember, EmployeeRelationship, DayOff) | ✅ Complete | All 6 models with relationships |
| `GET /employees`, `POST /employees`, `PUT`, `DELETE` | ✅ Complete | Full CRUD |
| `GET /trucks`, `POST /trucks`, `PUT`, `DELETE` | ✅ Complete | Full CRUD |
| `GET /relationships`, `POST`, `DELETE` | ✅ Complete | Fav/ban management |
| `GET /days-off`, `POST`, `DELETE` | ✅ Complete | Day-off pool management |
| `available_pool` service | ✅ Complete | Filters pool by role and approved days off |
| `base_weights` service | ✅ Complete | Equal starting weights per truck |
| `calculate_weights` service | ✅ Complete | Fan boosts (bi/tridirectional), consecutive penalty, cap enforcement |
| `assign_drivers` service | ✅ Complete | One driver per truck, consecutive truck penalty |
| `assign_trainers` service | ✅ Complete | Ban enforcement, two-pass even spread, all-zero fallback + warning |
| `assign_walkers` service | ✅ Complete | Tuple ban context, walker-vs-walker override via `check_ban_override`, spread cap |
| `check_ban_override` service | ✅ Complete | Senior crew preference logic, offending walker reassignment |
| `reassign_walker` service | ✅ Complete | Removes from current truck, re-runs assign_walkers for one walker |
| `run_dispatch` service | ✅ Complete | Full pipeline: validate → assign → persist → return warnings |
| `POST /dispatch/` router | ✅ Complete | Duplicate guard (409), driver shortage (400), serialized response |
| Docstrings + inline comments | ✅ Complete | All service files and routers |

---

## MVP Gaps — Priority Order

### P0 — Hard Blockers (app will crash or not start)

**1. Fix circular import**
- **Files:** `assign_walkers.py` → `ban_override.py` → `reassign_walker.py` → `assign_walkers.py`
- **Impact:** Python will raise an `ImportError` at startup. The app will not run.
- **Fix:** Move `perform_walker_reassignment` logic out of `reassign_walker.py` into `ban_override.py` directly (inline it), or extract shared state into a standalone module that neither walker file imports from the other.
- **Status:** ✅ Fixed (Inlined `perform_walker_reassignment` into `ban_override.py` and used local import for `assign_walkers`)

**2. Fix legacy imports in `assignment_members.py`**
- **File:** `backend/app/routers/assignment_members.py` (or similar)
- **Impact:** Any request hitting that router causes a 500. The old monolithic `app.services.dispatch` module no longer exists — `check_consecutive_assignment` and `check_ban_relationship` have been moved to separate service files.
- **Fix:** Update imports in that file to point to the correct modules.
- **Status:** ✅ Fixed (Updated consecutive router import. Restored the missing `check_ban` service manually to point to the correct location and removed the out-of-date `date` arg from tests).

---

### P1 — Security (nothing is protected without this)

**3. Authentication + JWT**
- **What's missing:** No login endpoint, no JWT generation, no token validation middleware, no `Depends(get_current_user)` on any protected route.
- **Impact:** Anyone with network access to the API can trigger dispatch, delete employees, or read all data. The entire API is unauthenticated.
- **What to build:**
  - `POST /auth/login` — accepts email + password, returns JWT access token
  - `POST /auth/refresh` — refreshes token
  - FastAPI dependency `get_current_user` that validates the token and returns the user
  - Apply `Depends(get_current_user)` to all routers
- **Reference:** See `docs/RBAC_RULES.md` for role definitions (driver, walker, dispatch, management)
- **Status:** ✅ Fixed (Implemented AWS Cognito Federated Identity. Backend solely validates AWS JWTs via `get_current_user` using PyJWT and cryptography libraries. Applied to `POST /dispatch/`.)

**4. Role-based access control on dispatch endpoints**
- **What's missing:** Even once auth is added, role enforcement is needed. Only `dispatch` and `management` roles should be able to trigger `POST /dispatch/`. Drivers should not be able to modify assignments.
- **What to build:** A `require_role(...)` dependency that checks the JWT claim against the allowed roles for each endpoint.
- **Depends on:** Item 3 (auth)
- **Status:** ✅ Fixed (Implemented `RoleChecker` callable class in `deps.py` tracking Cognito groups)

---

### P2 — Operational Necessity (dispatch can break without this)

**5. Manual assignment endpoint**
- **What's missing:** `POST /dispatch/assign` — allows a dispatcher to manually place a specific employee on a specific truck for a given date when the algorithm can't run (e.g. not enough drivers).
- **Why it matters:** The auto-dispatch raises a 400 and refuses to run if `num_drivers < num_trucks`. Without a manual fallback, the dispatcher has no way to handle that day at all.
- **Inputs:** `employee_id`, `truck_id`, `role`, `date`
- **Status:** ✅ Fixed (Implemented `ManualAssignmentCreate` schema and `POST /dispatch/assign` endpoint with validation and role security)

**6. Dispatch override/edit after run**
- **What's missing:** No way to swap a crew member out after dispatch has run (e.g. a driver calls out sick after the morning run). Currently the 409 duplicate guard prevents re-running, and there's no patch endpoint.
- **What to build:** `PATCH /dispatch/{date}/reassign` or similar — remove one member, place another.
- **Status:** ✅ Fixed (Implemented `DELETE` for removal and `PATCH` for swapping members, including missing truck up-serts).

---

### P3 — Infrastructure (needed before any deployment)

**7. Alembic migrations**
- **What's missing:** No migration history. The database schema is only created via `Base.metadata.create_all()` in `database.py`, which doesn't track versions.
- **Why it matters:** Can't deploy schema changes to a live database without migrations. Any schema update risks data loss or a broken deploy.
- **What to build:** Initialize Alembic, generate initial migration from current models, add a migration step to the Docker startup or CI pipeline.
- **Status:** ✅ Fixed (Configured `env.py` to target metadata and generated baseline schema)

**8. API versioning**
- **What's missing:** All routes currently use `/employees/`, `/dispatch/` etc. with no version prefix.
- **Why it matters:** Once a frontend or Discord bot consumes these routes, breaking changes without versioning will break clients.
- **What to build:** Mount all routers under `/api/v1/` prefix in `main.py`.
- **Status:** ✅ Fixed (Mounted an `APIRouter` with the `/api/v1` prefix in `main.py` and removed the legacy `create_all()` hook).

---

### P4 — Quality (needed before any release)

**9. Unit tests for dispatch services**
- **What's missing:** No test files exist for the dispatch service layer.
- **Coverage needed:**
  - `calculate_weights` — fan boost, consecutive penalty, cap enforcement, eligible truck filtering
  - `assign_drivers` — one driver per truck, no repeats
  - `assign_trainers` — ban exclusion, two-pass spread, warning on all-zero
  - `assign_walkers` — walker ban override, hard ban, spread cap, warning on all-zero
  - `run_dispatch` — driver shortage raises ValueError, full pipeline produces correct shape
- **Framework:** pytest + SQLAlchemy in-memory (SQLite) or test fixtures
- **Status:** ❌ Not built

---

---

## Field Ops — Driver Tools

Field Ops is the driver-facing page (`/field-ops`, access: driver + admin). It currently has three panels. Below is a full audit of each plus planned additions.

---

### Existing Tools

#### 1. Check-In (`CheckInPanel`)
**What it does:** Driver takes a photo at shift start. One check-in per driver per day enforced server-side. On reload, fetches history and pre-populates "already checked in" state.

| Gap | Severity | Status |
|---|---|---|
| `checked_in_at` timestamp captured in DB but never shown to driver in the UI | Low | ✅ |
| No check-in gate on Departure — driver can depart without checking in | Medium | ✅ |
| Photo stored as base64 in the DB — will bloat fast; future path is S3/presigned URL | Medium | ❌ (future) |
| No late check-in flag relative to scheduled dispatch time | Low | ❌ (future) |

**Fix tasks:**
- [x] Display `checked_in_at` time in the "already checked in" success banner
- [x] Backend: reject `POST /field-ops/departure` if no check-in exists for the same employee + date

---

#### 2. Departure (`DeparturePanel`)
**What it does:** Driver photographs the paper route itinerary before leaving the yard. One departure record per driver per day.

| Gap | Severity | Status |
|---|---|---|
| No check-in prerequisite enforced in backend | Medium | ✅ |
| No return/end-of-day counterpart — no shift duration tracking possible | High | ✅ |
| Only data field is the itinerary photo — no structured info (truck name, route code) captured | Low | ❌ (future) |

**Fix tasks:**
- [x] Backend gate: reject departure if no check-in for same employee + date
- [x] Build **Return / End-of-Day Log** (see New Tools below)

---

#### 3. Walker Rating (`WalkerRatingPanel`)
**What it does:** Driver sees walkers on their truck via `/field-ops/crew/{id}`, rates each 1–5 stars with optional comment. One rating per driver+walker+date.

| Gap | Severity | Status |
|---|---|---|
| No pre-population of already-submitted ratings — page refresh shows all walkers as unrated, submit hits a 400 surfaced as `alert()` | High | ✅ |
| `stars` column stored as `String(2)` on the model — should be `Integer` for analytics/averaging | High | ✅ |
| Walkers only — trainers on the truck are excluded from rating (intentional) | Low | ✅ confirmed |
| `GET /rating/walker/{id}` endpoint exists but no UI surfaces aggregate ratings to anyone | Medium | ❌ (future) |
| Rating window open all day — no enforcement that ratings are submitted at end of shift | Low | ❌ (future) |
| No explicit attendance record — missing rating is ambiguous (forgot vs no-show) | High | ✅ |

**Fix tasks:**
- [x] On `WalkerRatingPanel` mount, call `GET /field-ops/rating/driver/{driver_id}?date=today` and mark already-submitted walkers as done
- [x] Alembic migration: `walker_ratings.stars` `String(2)` → `Integer`
- [x] Add `GET /field-ops/rating/driver/{driver_id}` endpoint filtered by date so frontend can hydrate submitted state
- [x] Add `present` field to `WalkerRating`; no-shows stored as `present=false, stars=null`

---

### New Tools (build in order)

#### 4. Incident Report ⚡ Highest priority
Mid-shift form: text description + optional photo, severity tag (`info` / `warning` / `critical`). Auto-notifies dispatch/management/admin on `warning` and `critical`. Dispatch/management/admin can view all open incidents.

**Built:**
- Model: `incidents` table — category, severity, description, photo_url, incident_time, packages_tba, incident_location, witness_name, body_part_affected, medical_attention_required, driver_id (auto-resolved from assignment), resolved/resolved_by/resolved_at
- Endpoints: `POST /incidents/`, `GET /incidents/my`, `GET /incidents/`, `GET /incidents/unresolved-urgent`, `PATCH /incidents/{id}/resolve`
- UI: `/incidents` page (all field staff), management view with resolve button; Incidents nav link (all authenticated); Dashboard "Active Incidents" card (management/dispatch/admin)

**Status:** ✅ Built

---

#### 5. Return / End-of-Day Log
Symmetric to Departure — driver confirms they're back at the yard. Enables shift duration tracking via `departed_at` → `returned_at`.

**Built:**
- `returned_at` added to `Departure` model (migration `aa7f771104eb`)
- `POST /field-ops/return/{employee_id}` — stamps return, idempotent
- `GET /field-ops/returns/summary` — management fleet view with shift duration
- `ReturnPanel` in FieldOps.tsx (driver-only, appears after departure recorded)
- Dashboard "Fleet Return Status" card (management/admin)

**Status:** ✅ Built

---

#### 6. Pre-Trip Vehicle Inspection Checklist
Structured yes/no checklist submitted before departure. Failed items visible to management via summary endpoint.

**Built:**
- Model: `vehicle_inspections` — JSONB items, has_failures (server-computed), truck_id (auto-resolved)
- `INSPECTION_ITEMS` constant: tyres, lights, mirrors, brakes, fluids, horn, wipers, seatbelts, cargo_security, fuel_level
- Endpoints: `GET /field-ops/inspection/items`, `POST /field-ops/inspection`, `GET /field-ops/inspection/{driver_id}`, `GET /field-ops/inspections/summary`
- `InspectionPanel` in FieldOps.tsx — Pass/Fail toggle per item; submit blocked until all answered; confirmed state shows per-item icons
- Migration: `f4e891bc2d10`

**Status:** ✅ Built

---

#### 7. Walker Attendance Confirmation
Before rating, driver explicitly marks each assigned walker as present or no-show. No-shows stored as `present=false, stars=null`.

**Built:**
- `present` (Boolean, default true) added to `WalkerRating`; `stars` made nullable (migration `c2a983f01e44`)
- `POST /field-ops/rating` cross-validates: present walkers require stars 1–5; no-shows must have stars=null
- `WalkerRatingPanel` updated: attendance step precedes rating form; "Confirm No-Show" for absent walkers
- Pre-population on reload restores both attendance and rating state

**Status:** ✅ Built

---

#### 8. Fuel / Mileage Log
Driver logs departure odometer at shift start and patches return odometer + fuel added at shift end.

**Built:**
- Model: `fuel_mileage_logs` — odometer_start, odometer_end (nullable), fuel_added (nullable), truck_id (auto-resolved)
- Endpoints: `POST /field-ops/fuel-log`, `PATCH /field-ops/fuel-log/{driver_id}`, `GET /field-ops/fuel-log/{driver_id}`, `GET /field-ops/fuel-logs/summary`
- `FuelMileagePanel` in FieldOps.tsx — three states: start form → end form → completed summary; distance computed from odometer delta
- PATCH validates odometer_end ≥ odometer_start
- Migration: `e7d2130af5b1`

**Status:** ✅ Built

---

## Discord Bot Integration

The Discord server is the team's primary communication channel. The bot will act as a thin client over the REST API — all business logic stays in the backend.

### Planned Bot Commands

| Command | Endpoint | Required Role |
|---|---|---|
| `!dispatch run` | `POST /api/v1/dispatch/` | dispatch, management |
| `!dispatch status <date>` | `GET /api/v1/dispatch/<date>` | all |
| `!assign <employee> <truck> <role>` | `POST /api/v1/dispatch/assign` | dispatch, management |
| `!dayoff request <date>` | `POST /api/v1/days-off/` | driver, walker |
| `!dayoff approve <id>` | `PUT /api/v1/days-off/<id>/approve` | dispatch, management |
| `!fav add <employee>` | `POST /api/v1/relationships/` | driver, walker, trainer |
| `!ban add <employee>` | `POST /api/v1/relationships/` | driver, walker, trainer |
| `!crew <date>` | `GET /api/v1/dispatch/<date>` | all |

### What the bot needs from the API

- A service account or bot token type (not a personal JWT) so the bot can authenticate on behalf of Discord users
- All endpoints to be versioned (`/api/v1/`) before the bot is built against them — otherwise URL changes will break the bot
- Role mapping: Discord roles → AsheFlow roles (e.g. `@Dispatch` Discord role maps to `dispatch` JWT claim)

### Integration approach

The bot should make HTTP calls to the API — it should not access the database directly. All data flows through the REST layer so RBAC is enforced uniformly whether the action comes from a web client or a Discord command.

**Status:** ❌ Not started. Blocked on: Auth (item 3), Manual assignment endpoint (item 5), API versioning (item 8).

---

## Summary Table

| # | Item | Blocker? | Status |
|---|---|---|---|
| 1 | Fix circular import | Yes — startup crash | ✅ |
| 2 | Fix legacy router imports | Yes — runtime 500 | ✅ |
| 3 | Authentication + JWT | Yes — API is open | ✅ |
| 4 | RBAC on endpoints | Yes — depends on auth | ✅ |
| 5 | Manual assignment endpoint | Yes — driver shortage deadlock | ✅ |
| 6 | Dispatch override/edit | No — operational need | ✅ |
| 7 | Alembic migrations | Yes — needed for deploy | ✅ |
| 8 | API versioning | No — clean-up | ✅ |
| 9 | Unit tests | No — quality gate | ❌ |
| 10 | Discord bot | No — blocked on 3, 5, 8 | ❌ |
| **Field Ops Fixes** |  |  |  |
| 11 | Show check-in timestamp in confirmed banner | No — UX polish | ✅ |
| 12 | Gate departure on check-in (backend) | No — data integrity | ✅ |
| 13 | Fix walker rating pre-population on refresh | No — UX bug (surfaced as alert) | ✅ |
| 14 | Migrate `walker_ratings.stars` String→Integer | No — analytics blocker | ✅ |
| 15 | Add `GET /field-ops/rating/driver/{id}` endpoint | No — needed for fix 13 | ✅ |
| **Field Ops New Tools** |  |  |  |
| 16 | Incident Report (model, router, UI) | No — operational gap | ✅ |
| 17 | Return / End-of-Day Log (model, router, UI) | No — shift lifecycle | ✅ |
| 18 | Pre-Trip Vehicle Inspection Checklist | No — compliance | ✅ |
| 19 | Walker Attendance Confirmation | No — HR/dispatch planning | ✅ |
| 20 | Fuel / Mileage Log (model, router, UI) | No — fleet metrics | ✅ |

---

## Role Architecture & Dashboard Restructure
_Added: 2026-04-10_

### Role Definitions (canonical)

| Role | Who | Primary Concern |
|---|---|---|
| `driver` | Vehicle operators | Shift lifecycle: check-in, inspection, fuel log, departure, return, walker ratings |
| `walker` | Package delivery on foot | Schedule, preferences, incidents, check-in/departure |
| `trainer` | Senior staff training trainees | Trainee progress, task completion, continuation requests |
| `trainee` | New hires in training | Training tasks, training dashboard |
| `dispatch` | Scheduling coordinator | Running dispatch algorithm, managing daily assignments, approving reassignment requests |
| `management` | Operations supervisor | Reports, statistics, people approvals (time-off, off-days), fleet visibility, training oversight |
| `admin` | Tech lead / developer | System-wide visibility, data integrity tools, user management, audit access, dispatch override |

---

### Immediate Fixes (Correctness)

| # | Item | Type | Status |
|---|---|---|---|
| 21 | Fix `/field-ops` route — allow all field staff (walker, trainer, trainee) not just driver+admin | Frontend route | ❌ |
| 22 | Add auth to `trucks.py` — all endpoints unauthenticated | Backend auth | ❌ |
| 23 | Add auth to `time_off_requests.py` — all endpoints unauthenticated | Backend auth | ❌ |
| 24 | Add auth to `employee_off_days.py` — create/get/delete unprotected | Backend auth | ❌ |
| 25 | Add auth to `employee_relationships.py` — all endpoints unauthenticated | Backend auth | ❌ |
| 26 | Add auth to `schedule.py` — both endpoints unauthenticated | Backend auth | ❌ |
| 27 | Add auth to `notifications.py` — all endpoints unauthenticated | Backend auth | ❌ |
| 28 | Remove admin from `/trainer-dashboard` route — admin needs reports not the trainer form | Frontend route | ❌ |
| 29 | Remove admin from `/my-training` route — admin needs reports not trainee UI | Frontend route | ❌ |
| 30 | Remove management from Dispatch Center nav link — managers don't run dispatch | Navbar | ❌ |
| 31 | Remove Preferences nav link from management/admin (fav/ban not relevant to their role) | Navbar | ❌ |
| 32 | Clean up ghost `"tech"` role from `employees.py` GET allowlist | Backend auth | ❌ |

---

### Dashboard Restructure (Significant Work)

Split the single `isManagement` boolean dashboard into three distinct role-specific views.

#### Dispatch Dashboard (existing `/dispatch` page — keep, refine access)
- Run dispatch algorithm
- Manual assignment overrides (drag-and-drop)
- Pending reassignment request approvals
- Dispatch warnings panel
- Clear Dispatch (admin only)

#### Management Dashboard (new — replace current generic management view on `/`)
Remove: Dispatch Center quicklink, reassignment request approvals
Add:
- **Daily Operations Summary** — drivers departed/returned, any still out past expected return (late flag)
- **Workforce Health** — no-shows today, pending time-off approvals, pending off-day approvals
- **Incident Trend** — count by severity this week, unresolved count, oldest unresolved age
- **Training Pipeline** — active trainees, sessions today, trainers with overdue continuation requests
- **Walker Performance Snapshot** — average star rating per walker this week, no-show count this week
- **Vehicle Compliance** — trucks with inspection failures today/this week, repeated failure flags

#### Admin Dashboard (new dedicated page `/admin`)
- System health: API uptime, DB row counts per major table, current Alembic migration version
- Employee/user CRUD: create accounts, change roles, deactivate, link discord IDs (the Assets stub)
- Truck CRUD: full management
- Audit trail: who approved/rejected what, dispatch history per date, incident resolution log
- Dispatch override tools: Clear Dispatch, re-run for any date, purge stuck records
- All management reporting panels (admin sees everything management sees)
- Training oversight: graduate trainees, reassign between trainers, view all records

---

### New Backend Endpoints Needed (for management reporting)

| # | Endpoint | Purpose | Status |
|---|---|---|---|
| 33 | `GET /field-ops/no-shows?target_date=` | Walker no-shows for a date | ❌ |
| 34 | `GET /field-ops/walker-stats?week_start=` | Avg stars + no-show count per walker, rolling week | ❌ |
| 35 | `GET /field-ops/inspection-failures/summary?days=7` | Trucks with repeated inspection failures | ❌ |
| 36 | `GET /training/pipeline-summary` | Active trainees, sessions today, overdue continuations | ❌ |
| 37 | `GET /incidents/summary?days=7` | Count by severity, oldest unresolved | ❌ |

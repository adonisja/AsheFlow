# Journal: Role Scope Enforcement, Tool Alignment, and Schedule Change System
**Date:** 2026-04-11

---

## Goal for the Session

Following the role architecture restructure (ADR-016) that split the dashboard into DispatchView / ManagementView / WorkerView and built 5 new management reporting endpoints, this session enforced those role definitions all the way through the codebase — backend dependencies, frontend routes, navbar visibility, tool pages, and individual component guards. The session also completed the Schedule Change Request system (model, migration, router, and frontend page) that had been planned but not finished.

---

## What Was Built and Changed

### 1. Schedule Change Request System (Backend)

The `ScheduleChangeRequest` model and Alembic migration were completed in the prior session. This session wired up the router and registered it in `main.py`.

**Router** (`backend/app/routers/schedule_change_requests.py`):

| Endpoint | Access | Behavior |
|---|---|---|
| `POST /` | field staff + dispatch | Submit request; one-pending-at-a-time guard; notifies all management/admin |
| `GET /employee/{id}` | self or management/admin | Own request history |
| `GET /` | management / admin | All pending requests with employee detail |
| `PATCH /{id}/approve` | management / admin | Auto-applies schedule mutation to `employee_off_days` |
| `PATCH /{id}/reject` | management / admin | Status update + employee notification |
| `DELETE /{id}` | self | Self-cancel pending (hard delete, no cancelled status) |

**Auto-apply on approval** — the approve endpoint directly mutates the `employee_off_days` table:
- `add_day`: deletes EmployeeOffDay rows for the specified days (making the employee eligible again)
- `drop_day`: inserts new EmployeeOffDay rows for the specified days
- `full_rework`: clears all existing off days for the employee, then inserts rows for every day NOT in `proposed_schedule`

This was the right call because approval of a permanent schedule change has a deterministic outcome — there is no ambiguity about what "approved" means, unlike truck reassignment where the destination is unknown.

**Registration** — `schedule_change_requests` added to `main.py` import list and `api_v1_router.include_router()` call.

---

### 2. Backend Role Guard Tightening

#### `employee_relationships.py`
- Removed `"trainee"` from `allow_field_staff`
- Trainees cannot create fav/ban relationships — they are too new to the organization to meaningfully influence dispatch pairing. This was the original intent but was never enforced.
- Final: `allow_field_staff = RoleChecker(["driver", "walker", "trainer"])`

#### `field_ops.py`
- Added `_: dict = Depends(allow_driver)` to 6 submission POST endpoints: `check-in`, `departure`, `return`, `rating`, `inspection`, `fuel-log`
- These endpoints already enforced ownership (`payload.employee_id != caller.id`) but had no role check — a walker or trainer with a valid JWT could call them.
- Read endpoints were left as `get_caller_employee` only (management/admin can view history without needing the driver role).
- The `allow_driver` role constant already existed in the file and was unused.

#### `assignment_change_requests.py`
- Added ownership check: `payload.employee_id != caller.id` → 403 (previously missing — any walker/trainer could submit for any other employee)
- Added today-only guard: `payload.requested_date != date.today()` → 400
- Added active assignment guard: employee must have a `TruckAssignment` for today via `AssignmentMember` join — 400 if not found
- Added `get_caller_employee` dependency and `AssignmentMember`, `TruckAssignment` imports

The today-only constraint enforces the business rule that truck reassignment is a same-day operational request, not a future scheduling tool. The active assignment check prevents workers from submitting when they are not currently on a truck — there is nothing to reassign.

---

### 3. Frontend Route Changes (`App.tsx`)

| Route | Before | After |
|---|---|---|
| `/field-ops` | `['driver', 'walker', 'trainer', 'trainee', 'admin']` | `['driver', 'admin']` |
| `/schedule-changes` | did not exist | `['driver', 'walker', 'trainer', 'trainee', 'dispatch', 'admin']` |

The field-ops route was broadened in ADR-016 to include all field staff based on the assumption that walkers and trainers needed check-in. That assumption was incorrect — walkers and trainers meet at the Anchor Point, not the yard. They do not check in, do not drive vehicles, and do not perform pre-trip inspections. Field Ops is a driver-only page. The route was corrected back to `['driver', 'admin']`.

---

### 4. Navbar Changes (`Navbar.tsx`)

| Link | Before | After |
|---|---|---|
| Field Ops | `canAccessFieldOps = isFieldStaff \|\| admin` | `groups.includes('driver') \|\| groups.includes('admin')` |
| Schedule Changes | did not exist | `isFieldStaff \|\| dispatch \|\| admin` |

Added `RefreshCw` icon from lucide-react for the Schedule Changes link. Both desktop and mobile nav updated.

---

### 5. Preferences.tsx Rewrite

The Preferences page was restructured around corrected role rules:

- **Fav/Ban sections** — now gated to `canFavBan = groups.some(r => ['driver', 'walker', 'trainer'].includes(r))`. Trainees see a placeholder explaining the feature unlocks after graduating.
- **Truck Reassignment section** — removed the date picker entirely. The form now always submits `requested_date = today`. If the employee already has a pending request for today, the form is replaced with a warning. History list limited to 5 most recent entries.
- **Schedule Change section** — removed entirely. The content was the old off-day request flow (adding a single recurring off day). The full schedule change system now lives at `/schedule-changes`.
- Removed unused state: `offDays`, `selectedDay`, `changeRequestDate`, `setOffDays`, `setSelectedDay`, `setChangeRequestDate`.
- Removed unused imports: `CalendarClock`, `DAYS_OF_WEEK`.

---

### 6. ScheduleChanges Page (New, `frontend/src/pages/ScheduleChanges.tsx`)

Three-mode form for requesting permanent schedule changes:

| Mode | What it does | Selectable days |
|---|---|---|
| `add_day` | Re-enable currently-off days | Only current off days |
| `drop_day` | Drop currently-working days | Only current working days |
| `full_rework` | Replace entire schedule | All 7 days |

The selectable day list is derived from the employee's current `employee_off_days` — this prevents logically invalid submissions (you cannot "add back" a day you already work, you cannot "drop" a day you already have off).

Pending guard: if the employee already has a pending request, the form is replaced with a warning banner. The backend enforces this too — the UI guard is for UX only.

Reviewer panel: management and admin see all pending requests with approve/reject buttons inline. Approval triggers the auto-apply mutation on the backend.

---

### 7. WorkerView.tsx Quick Links Updated

- Added Schedule Changes link (`/schedule-changes`, RefreshCw icon)
- Field Ops link now only rendered for drivers (`isDriver` check)
- Updated Preferences description to reflect reassignment is now in Preferences, schedule change is at its own page

---

## Problems Encountered

### Preferences.tsx State Drift
Removing the `offDays`, `selectedDay`, and `changeRequestDate` state variables in one edit left orphaned references throughout the JSX and remaining function bodies. The file had to be fully rewritten rather than incrementally patched because the state and JSX were too intertwined for safe targeted edits.

**Lesson:** When removing a feature that has state, handlers, useEffects, and JSX all touching the same state variable, it is faster and safer to rewrite the full component than to patch it in pieces.

### Phantom Alembic Column Drift (Recurring)
Every autogenerated Alembic migration for this project includes spurious `op.drop_column('training_records', 'trainer_rating')` and `op.drop_column('training_records', 'trainee_comments')` lines in `upgrade()`, and corresponding `op.add_column` lines in `downgrade()`. These columns do not exist in the database, but the SQLAlchemy model still references them, causing Alembic's comparison to always flag them as "removed."

**Fix:** Strip these lines manually before running `alembic upgrade head`. This must be done on every new migration.

**Root cause:** The columns were added to the model as planned fields but were never included in any migration, creating a permanent divergence between model and schema.

---

## Key Takeaways

- Backend role guards (`RoleChecker`) and ownership checks (`payload.employee_id != caller.id`) are two separate concerns and both need to be present. Role checks gate entry to the endpoint. Ownership checks prevent users with valid roles from acting on other users' data. Both were missing from assignment_change_requests.py.
- The `allow_driver` constant being defined but unused in `field_ops.py` is a sign that the role constraints were planned but never wired up. Always trace from intent to implementation — unused constants are a code smell for incomplete enforcement.
- When a feature changes scope (Preferences losing schedule change, gaining today-only reassignment), remove the old code entirely rather than leaving it conditionally hidden. Dead code increases cognitive load and creates bugs when state dependencies cross paths.

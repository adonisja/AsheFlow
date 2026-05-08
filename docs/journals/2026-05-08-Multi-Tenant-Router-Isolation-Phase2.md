# 2026-05-08 — Multi-Tenant Router Isolation Phase 2

## What prompted this

After Phase 1 (ADR-063/064) got `company_id` into all 32 tables and converted the dispatch/employee routers, we audited the remaining routers. The audit found 14 files where:

- Queries had no `company_id` filter — a caller from Tenant A could see Tenant B's anchor points, change requests, etc.
- Notification fanout queried all dispatchers/admins across all tenants instead of just the caller's company.
- Some endpoints were using an old auth pattern (Discord-ID lookup) instead of `get_caller_employee`.
- Audit log calls were passing the Cognito sub string as `actor_id` instead of the employee UUID.

## What changed

**Three files completed this session:**

**`anchor_points.py`** — The three helper functions (`_get_assignment`, `_crew_employee_ids`, `_notify`) were each extended with a `company_id: UUID` parameter. Every call site now passes `caller.company_id`. The dispatch notification query gained `Employee.company_id == caller.company_id`. New `AnchorPoint` rows now stamp `company_id`. The two read endpoints (`/date/{target_date}`, `/truck/{truck_id}`) gained `caller: Employee` and filter by company.

**`assignment_change_requests.py`** — Full rewrite. The old code derived the reviewer identity from `Employee.discord_id == current_user.get("username")` — fragile and non-deterministic if an employee had no Discord ID. All six endpoints now use `caller: Employee = Depends(get_caller_employee)`. Reads against `AssignmentChangeRequest` scope through an Employee join since the model doesn't carry `company_id` directly. Notifications stamped with `company_id`. Audit calls use `str(caller.id)` and `str(caller.company_id)`.

**`trainer_coverage.py`** — Minimal change. Added `caller: Employee` and added `TrainerCoverage.company_id == caller.company_id` to the filter. The model already had the column.

## Test breakage and fix

Analytics tests call router functions directly (bypassing HTTP). When `analytics.py` gained `caller: EmployeeModel` as a required parameter in the previous session, those direct calls started failing with `AttributeError: 'Depends' object has no attribute 'company_id'`.

Fix: added `make_admin_caller(db)` helper to `test_analytics.py` that creates an admin employee scoped to `SEED_COMPANY_ID`, then threaded `caller=make_admin_caller(db)` into all 20+ test call sites.

## Pattern for future work

Any router that calls `db.query(SomeModel)` needs to ask: does `SomeModel` have `company_id` directly, or does it need a join? If direct — add `.filter(SomeModel.company_id == caller.company_id)`. If indirect — join through an Employee or TruckAssignment that does have it.

The three write-path items to always check:
1. New row stamped with `company_id=caller.company_id`
2. Notification rows stamped with `company_id=caller.company_id`
3. `write_audit` called with `actor_id=str(caller.id)` and `company_id=str(caller.company_id)`

## Result

97/97 tests passing. All high-severity routers from the Phase 2 audit are now tenant-isolated.

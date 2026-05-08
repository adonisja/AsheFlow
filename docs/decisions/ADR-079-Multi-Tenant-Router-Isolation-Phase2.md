# ADR-079 — Multi-Tenant Router Isolation Phase 2

**Date:** 2026-05-08  
**Status:** Accepted

## Context

Phase 1 (ADR-063, ADR-064) added `company_id` columns to all 32 tables and converted the core dispatch/employee routers. Phase 2 audited the remaining routers and found 14 high-severity endpoints that either leaked cross-tenant data or wrote rows without stamping `company_id`.

The pattern of failure was consistent across all affected files:

1. **Unscoped reads** — `db.query(Model).filter(Model.id == id)` with no `company_id` check, allowing a caller from Company A to read or mutate Company B's records.
2. **Unscoped notification fanout** — `db.query(Employee).filter(Employee.role == "dispatch")` without `company_id`, sending notifications to all dispatchers across all tenants.
3. **Missing `company_id` stamp** on new rows (`AnchorPoint`, `AssignmentChangeRequest` notifications).
4. **Stale auth pattern** — several endpoints still used `current_user: dict = Depends(...)` + a Discord-ID lookup to derive the reviewer identity, rather than the standardised `caller: Employee = Depends(get_caller_employee)`.
5. **Audit calls using Cognito sub** — `actor_id=current_user.get("id")` passed the Cognito sub (a string like `"us-east-1_abc..."`) instead of the UUID employee ID.

## Decision

All 14 high-severity routers were hardened. The changes follow a uniform pattern:

### 1. Standardise the auth dependency

Replace:
```python
current_user: dict = Depends(allow_dispatcher)
```
With:
```python
caller: Employee = Depends(get_caller_employee),
_: dict = Depends(allow_dispatcher),
```

`get_caller_employee` resolves the JWT to an `Employee` row and provides `caller.id` (UUID) and `caller.company_id` — the two values needed for all scoping and audit calls. The `_` dependency still enforces role gating.

### 2. Scope all reads by company_id

```python
# Before — leaks across tenants
db.query(AnchorPoint).filter(AnchorPoint.id == anchor_id).first()

# After — tenant-isolated
db.query(AnchorPoint).filter(
    AnchorPoint.id == anchor_id,
    AnchorPoint.company_id == caller.company_id,
).first()
```

For models without a direct `company_id` (e.g. `AssignmentChangeRequest`), scope via a join:
```python
db.query(AssignmentChangeRequest)
    .join(Employee, AssignmentChangeRequest.employee_id == Employee.id)
    .filter(
        AssignmentChangeRequest.id == request_id,
        AssignmentChangeRequest.status == "pending",
        Employee.company_id == caller.company_id,
    )
```

### 3. Scope notification fanout

```python
# Before
db.query(Employee).filter(Employee.role.in_(["dispatch", "admin"]), Employee.is_active == True).all()

# After
db.query(Employee).filter(
    Employee.company_id == caller.company_id,
    Employee.role.in_(["dispatch", "admin"]),
    Employee.is_active == True,
).all()
```

### 4. Stamp new rows with company_id

```python
new_ap = AnchorPoint(
    company_id = caller.company_id,  # added
    truck_id   = payload.truck_id,
    ...
)
```

### 5. Fix audit calls

```python
# Before — actor_id was Cognito sub, company_id missing
write_audit(db, actor_id=current_user.get("id"), ...)

# After
write_audit(
    db,
    actor_id=str(caller.id),
    company_id=str(caller.company_id),
    ...
)
```

## Files changed

| File | Changes |
|------|---------|
| `routers/anchor_points.py` | `_get_assignment`, `_crew_employee_ids`, `_notify` helpers accept `company_id`; new AP stamped; dispatch queries scoped; `get_anchor_points_for_date` and `get_anchor_points_for_truck` get `caller` |
| `routers/assignment_change_requests.py` | Full rewrite — removed Discord-ID reviewer lookup; all 6 endpoints use `caller: Employee`; queries scoped via Employee join; notifications and audit calls fixed |
| `routers/trainer_coverage.py` | Added `caller: Employee`; filtered `TrainerCoverage` by `company_id` |
| `tests/services/test_analytics.py` | Added `make_admin_caller` helper; threaded `caller=` into all 20+ direct analytics function calls broken by the `caller` parameter addition |

(Previous session also completed: `notifications`, `employee_off_days`, `time_off_requests`, `incidents`, `analytics`, `trainer_marks`, `schedule`, `assignment_members`, `schedule_change_requests`, `continuation_requests`, `feedback`, `trucks`, `audit`, `employees`.)

## Consequences

- All router-layer queries are now tenant-isolated — a caller from one company cannot read, mutate, or receive notifications for another company's data.
- The `current_user: dict` pattern survives only where Cognito group membership is genuinely needed (e.g. `continuation_requests.py` group checks). All other usage has been replaced.
- Tests that call router functions directly must now pass a `caller` employee — the test file pattern is `caller=make_admin_caller(db)` with `company_id=SEED_COMPANY_ID`.
- Notification rows are now stamped with `company_id`, enabling future per-tenant notification queries and retention policies.

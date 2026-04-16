# Journal: Available Pool PTO Filter Fix
**Date:** 2026-04-16

---

## Context

A review of the codebase surfaced a correctness bug in `get_available_pool`. The function is the single source of truth for who is eligible to be dispatched on a given date, but it only excluded employees with approved recurring off-days — not employees with approved PTO requests for the specific date.

The sibling function `get_unavailable_staff` (the inverse — returns who is *not* available and why) had been written correctly with both exclusions. The two functions had diverged silently.

---

## Fix Applied

**File:** `backend/app/services/available_pool.py`

**Problem:** `get_available_pool` built a single `has_off_day_today` EXISTS subquery and used `~has_off_day_today` in the `.filter()`. There was no equivalent check for `TimeOffRequest`.

**Fix:** Added a second EXISTS subquery `has_pto_today` using the already-imported `TimeOffRequest` model, then combined both with `~or_(has_off_day_today, has_pto_today)`:

```python
has_pto_today = (
    db.query(TimeOffRequest)
    .filter(
        TimeOffRequest.employee_id == Employee.id,
        TimeOffRequest.date == target_date,
        TimeOffRequest.status == 'approved'
    )
    .exists()
)

available_employees = (
    db.query(Employee)
    .filter(
        Employee.role.in_(["driver", "trainer", "trainee", "walker"]),
        Employee.is_active == True,
        ~or_(has_off_day_today, has_pto_today)
    )
    .all()
)
```

No new imports were needed — `or_` was already imported from `sqlalchemy` and `TimeOffRequest` was already imported.

---

## Root Cause

`get_available_pool` and `get_unavailable_staff` are inverses of each other — every employee in the pool should be absent from the unavailable list and vice versa. They were written at different times and their exclusion logic was never cross-checked. The PTO filter was added to `get_unavailable_staff` correctly but never backported to `get_available_pool`.

---

## Files Changed

| File | Change |
|---|---|
| `backend/app/services/available_pool.py` | Added `has_pto_today` EXISTS subquery; combined with `has_off_day_today` via `~or_(...)` in the employee filter |

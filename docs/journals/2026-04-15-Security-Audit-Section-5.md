# Journal: Security Audit — Section 5 Remaining Gaps
**Date:** 2026-04-15

---

## Context

Section 5 was a final sweep of the full codebase after sections 1–4 were complete. It found three remaining issues: a missing ownership check on the employee off-days router, CORS origins hardcoded in source code, and silent load failures in the Assets page.

---

## Fixes Applied

---

### 5.1 — `POST /employee-off-days/` Missing Ownership Check (HIGH)

**File:** `backend/app/routers/employee_off_days.py`

**Problem:** `create_employee_off_day` used `allow_any_auth` (all roles) as its only auth dependency. Any authenticated field-staff member could POST a payload with another employee's `employee_id` and silently add recurring off-days to their schedule. The function checked that the target employee existed but never verified the caller was that employee.

**Fix:** Replaced `_: dict = Depends(allow_any_auth)` with `caller: Employee = Depends(get_caller_employee)`. Added ownership check before the DB query:

```python
mgmt_roles = {"management", "admin"}
if caller.role not in mgmt_roles and caller.id != employee_off_day.employee_id:
    raise HTTPException(403, "You can only add off-days for yourself.")
```

Management and admin can still create off-days for any employee — this is required for the admin-managed schedule workflow.

---

### 5.2 — `GET /employee-off-days/{employee_id}` Missing Ownership Check (MEDIUM)

**File:** `backend/app/routers/employee_off_days.py`

**Problem:** The read endpoint also used `allow_any_auth`. Any field-staff member could read any other employee's off-day schedule by providing their UUID. Off-day schedules are not highly sensitive, but cross-user reads with no ownership check are inconsistent with every other field-staff endpoint in the codebase.

**Fix:** Same pattern — replaced with `get_caller_employee`, added ownership check:

```python
mgmt_roles = {"management", "admin", "dispatch"}
if caller.role not in mgmt_roles and caller.id != employee_id:
    raise HTTPException(403, "You can only view your own off-days.")
```

Dispatch is included in the read-allowed roles since they need schedule visibility to run dispatch.

---

### 5.3 — CORS Origins Hardcoded in `main.py` (MEDIUM)

**Files:** `backend/app/main.py`, `backend/app/core/config.py`

**Problem:** Eight `localhost` origin strings were hardcoded directly in `main.py`. A production deployment would require a code change to add the real frontend origin — or risk shipping with `localhost` still in the CORS allowlist, which would silently allow requests from any local machine on the right port.

**Fix:**
- Added `cors_origins: str` to `Settings` in `config.py` with the same eight localhost values as the default (comma-separated string). Added a `get_cors_origins()` helper that splits and strips the string into a list.
- In `main.py`, replaced the hardcoded list with `settings.get_cors_origins()`.
- In production, set `CORS_ORIGINS=https://app.asheflow.com` (or a comma-separated list) in the environment. The default remains unchanged for local dev — no `.env` change required for existing developers.

---

### 5.4 — Assets Page: Silent Load Failures (LOW)

**File:** `frontend/src/pages/Assets.tsx`

**Problem:** Both `PeopleTab` and `FleetTab` used `.catch(console.error)` on their initial data-load calls. When the API was unreachable or returned an error, the spinner would disappear and the user would see either an empty list or the "no records" empty state — with no indication that a network error had occurred. Admins troubleshooting an issue would have no visible signal.

**Fix:** Added `loadError` state to both tabs. On catch, `loadError` is set to a plain-English message. The error renders as a red-bordered card above the table/grid, consistent with other error display patterns in the codebase. The error is cleared on each subsequent `load()` call so a successful retry removes it.

---

## Files Changed

| File | Change |
|---|---|
| `backend/app/routers/employee_off_days.py` | Ownership check on `POST /`; ownership check on `GET /{employee_id}` |
| `backend/app/core/config.py` | Added `cors_origins` setting with dev default; added `get_cors_origins()` helper |
| `backend/app/main.py` | Replaced hardcoded CORS list with `settings.get_cors_origins()`; added `settings` import |
| `frontend/src/pages/Assets.tsx` | `loadError` state + visible error card in `PeopleTab` and `FleetTab` |

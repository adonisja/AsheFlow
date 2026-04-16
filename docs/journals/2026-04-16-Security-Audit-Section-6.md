# Journal: Security Audit — Section 6 Ownership Gaps
**Date:** 2026-04-16

---

## Context

Section 6 was a targeted sweep of routers and pages that handle user-generated relationships and requests, looking for ownership gaps — places where any authenticated user could act on another user's records. Three backend routers had missing ownership checks across seven endpoints. The Schedule page had a residual fragile self-lookup from before Section 3 fixed the same pattern elsewhere.

---

## Fixes Applied

---

### 6.1 — `continuation_requests.py`: POST Missing Trainee Ownership Check (HIGH)

**File:** `backend/app/routers/continuation_requests.py`

**Problem:** `submit_continuation_request` accepted `trainee_id` from the request body without verifying the caller was that trainee. Any trainee could submit a continuation request on behalf of any other trainee. The existing guard (most-recent trainer check) prevented requests to arbitrary trainers but not requests from arbitrary trainees.

**Fix:** Added `caller: Employee = Depends(get_caller_employee)`. Ownership check before all other validation:

```python
caller_groups = current_user.get("cognito_groups", [])
if "admin" not in caller_groups and caller.id != payload.trainee_id:
    raise HTTPException(403, "You can only submit continuation requests for yourself.")
```

Admins bypass the check — they can submit on behalf of any trainee for operational overrides.

---

### 6.2 — `continuation_requests.py`: GET Missing Trainer Ownership Check (MEDIUM)

**File:** `backend/app/routers/continuation_requests.py`

**Problem:** `GET /continuation-requests/trainer/{trainer_id}` returned all pending requests addressed to that trainer with only `allow_trainer` (any authenticated trainer could read). Any trainer could read another trainer's incoming continuation requests by supplying a different trainer UUID.

**Fix:** Added `caller: Employee = Depends(get_caller_employee)` and ownership check:

```python
if "admin" not in caller_groups and caller.id != trainer_id:
    raise HTTPException(403, "You can only view your own continuation requests.")
```

---

### 6.3 — `continuation_requests.py`: Accept/Reject Missing Trainer Ownership Check (MEDIUM)

**File:** `backend/app/routers/continuation_requests.py`

**Problem:** `PATCH /{request_id}/accept` and `PATCH /{request_id}/reject` allowed any authenticated trainer to accept or reject any pending continuation request, regardless of whether it was addressed to them. Trainer A could accept or nullify a request meant for Trainer B.

**Fix:** Added `caller: Employee = Depends(get_caller_employee)` to both handlers. After fetching the request:

```python
if "admin" not in caller_groups and caller.id != req.trainer_id:
    raise HTTPException(403, "You can only accept/reject requests addressed to you.")
```

Note: The `priority` endpoint already had this ownership check from Section 1 (fix 1.5). These two endpoints were missed in that pass.

---

### 6.4 — `employee_relationships.py`: POST Missing Ownership Check (HIGH)

**File:** `backend/app/routers/employee_relationships.py`

**Problem:** `create_employee_relationship` used `allow_field_staff` (any driver/walker/trainer) as its only dependency. The `employee_id` in the payload was accepted without verification against the caller. Any field-staff member could create a ban or fav entry attributed to another employee's `employee_id`, bypassing the per-role fav limits and the two-ban cap for the actual employee.

**Fix:** Added `caller: Employee = Depends(get_caller_employee)`. Ownership check before the employee existence query:

```python
if caller.id != employee_relationship.employee_id:
    raise HTTPException(403, "You can only create relationships for yourself.")
```

---

### 6.5 — `employee_relationships.py`: GET Missing Ownership Check (MEDIUM)

**File:** `backend/app/routers/employee_relationships.py`

**Problem:** `GET /employee-relationships/{employee_id}` used `allow_any_auth`. Any authenticated user (including dispatch or trainees) could read any employee's full fav/ban list by UUID. The fav/ban list reveals operational preferences and interpersonal tensions — not public information.

**Fix:** Replaced with `caller: Employee = Depends(get_caller_employee)` and ownership check:

```python
mgmt_roles = {"management", "admin", "dispatch"}
if caller.role not in mgmt_roles and caller.id != employee_id:
    raise HTTPException(403, "You can only view your own relationships.")
```

Dispatch is included in the read-allowed set — they need this data to inform dispatch decisions.

**Also fixed:** The function was named `get_employee_realtionships` (typo). Renamed to `get_employee_relationships`.

---

### 6.6 — `employee_relationships.py`: DELETE Missing Ownership Check (HIGH)

**File:** `backend/app/routers/employee_relationships.py`

**Problem:** `DELETE /employee-relationships/{id}` used `allow_any_auth`. Any authenticated user could delete any relationship record by UUID — clearing another employee's bans or favs entirely.

**Fix:** Replaced with `caller: Employee = Depends(get_caller_employee)` and ownership check after the 404 guard:

```python
mgmt_roles = {"management", "admin"}
if caller.role not in mgmt_roles and caller.id != relationship.employee_id:
    raise HTTPException(403, "You can only delete your own relationships.")
```

---

### 6.7 — `Schedule.tsx`: Fragile Self-Lookup and Silent Load Errors (MEDIUM)

**File:** `frontend/src/pages/Schedule.tsx`

**Problem:**
1. `myId` was initialised as `user?.userId || user?.username || ''` — the same fragile Cognito-username-as-UUID pattern fixed in other pages in Section 3. The `useEffect` also called `GET /employees/` and searched for `self` using `e.id === user.userId || e.id === user.username`. This would fail silently for any account where neither matched the employee DB UUID.
2. Both the employee list fetch and `fetchSchedule` used `.catch(console.error)` — no user-visible error when data failed to load.

**Fix:**
- `myId` initialised as `''` (no longer seeded from fragile Cognito fields).
- `useEffect` now calls `GET /employees/me` (parallel with `GET /employees/`) to get the real employee UUID. Uses `Promise.all` so both resolve together; catch sets `loadError`.
- `fetchSchedule` now sets `loadError` on failure instead of swallowing it.
- `loadError` state renders as a red-bordered error card above the calendar.
- Removed `user` from the `useEffect` dependency array — `GET /employees/me` is auth-cookie-based, no `user` object needed.
- Removed `a.first_name || a.name` reference — Employee model has only `name`.

---

## Files Changed

| File | Change |
|---|---|
| `backend/app/routers/continuation_requests.py` | Ownership check on POST (trainee), GET (trainer), accept (trainer), reject (trainer) |
| `backend/app/routers/employee_relationships.py` | Ownership check on POST, GET, DELETE; typo fix on GET function name |
| `frontend/src/pages/Schedule.tsx` | `/employees/me` for self-lookup; `loadError` state on all fetches; error card in JSX; removed `first_name` reference |

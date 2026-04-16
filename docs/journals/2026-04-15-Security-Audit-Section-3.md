# Journal: Security Audit — Section 3 Gaps and Cleanup
**Date:** 2026-04-15

---

## Context

Section 3 addressed non-security gaps, missing features, and dead code identified during the broader audit. These were lower severity than Sections 1–2 but collectively represented reliability risks (fragile ID resolution), schema confusion (phantom `first_name` field), and accumulating dead weight (orphaned router, duplicate endpoint).

---

## Fixes Applied

---

### 3.1 — Orphaned Router Deleted

**File deleted:** `backend/app/routers/schedule_availability.py`

**Problem:** The router was never registered in `main.py`. Its `GET /{target_date}` endpoint had no authentication dependency and duplicated logic already implemented — and properly authenticated — in `backend/app/routers/schedule.py`. It was unreachable from the API but was a maintenance hazard: any future developer could wire it in unintentionally, exposing an unauthenticated availability endpoint.

**Fix:** File deleted.

---

### 3.2 — `TraineeDashboard.tsx` Passed Cognito Username as UUID (HIGH for reliability)

**File:** `frontend/src/pages/TraineeDashboard.tsx`

**Problem:** The `fetchHistory` effect resolved the employee ID using `user?.username || (user as any)?.id`. `user.username` is the Cognito username — which is an opaque string (often an email or a UUID-like sub, but never guaranteed to be the employee DB UUID). This was passed directly to `GET /training/trainee/{trainee_id}`, which expects a UUID. On any account where the Cognito username is not the employee UUID, the request returns a 422, and the trainee dashboard renders nothing.

**Fix:** Replaced with `GET /employees/me` to resolve the authenticated caller's actual employee record, then passed `res.data.id` (the true DB UUID) to the training endpoint. The `useEffect` dependency array was updated to `[]` since the request is authenticated via cookie/header — no `user` object dependency needed.

---

### 3.3 — `Incidents.tsx` Used Fragile `GET /employees/` Scan (MEDIUM for reliability)

**File:** `frontend/src/pages/Incidents.tsx`

**Problem:** The component resolved the current user's employee ID by fetching the entire `/employees/` list and searching for a match via `e.discord_id === user.username || e.id === user.userId`. This fails when:
- The Cognito username is an email (not a Discord ID).
- `user.userId` does not map to the employee's DB UUID.
- The employee list is large (unnecessary network overhead).

**Fix:** Replaced with `GET /employees/me`, which uses the four-step `get_caller_employee` lookup chain on the backend. Single request, no linear scan, reliable on all account types.

---

### 3.4 — `FieldOps.tsx` Already Used `/employees/me` (No Change)

**Finding:** The main `FieldOps` page component already resolved `employeeId` via `axiosClient.get('/employees/me')` at the time of the audit. No change needed.

---

### 3.5 — `VehicleCompliance.tsx` Referenced Non-Existent `first_name` Field

**File:** `frontend/src/pages/VehicleCompliance.tsx`

**Problem:** The driver list was built with `.map((e: any) => ({ id: e.id, name: e.first_name || e.name }))`. The `Employee` model has a single `name` field — there is no `first_name`. The `||` fallback meant `e.name` was always used, but the `e.first_name` reference was misleading and fragile.

**Fix:** Simplified to `e.name` directly.

---

### 3.6 — Dead `DELETE /employees/{id}` Endpoint Removed

**File:** `backend/app/routers/employees.py`

**Problem:** `DELETE /employees/{employee_id}` performed a soft-delete (`is_active = False`), which is identical to what `PUT /employees/{employee_id}/deactivate` already does. Two routes doing the same thing under different HTTP verbs creates ambiguity — which do callers use? The frontend used the `deactivate` endpoint exclusively; the DELETE was dead weight.

**Fix:** Removed `delete_employee`. `PUT /employees/{id}/deactivate` is the canonical deactivation endpoint.

---

### 3.7 — `GET /schedule-change-requests/` Hard-Coded to Pending Only

**File:** `backend/app/routers/schedule_change_requests.py`, `frontend/src/pages/ScheduleChanges.tsx`

**Problem:** The management-facing `GET /schedule-change-requests/` always filtered by `status == "pending"`. There was no way to retrieve approved or rejected requests for audit or analytics. The frontend's `loadAllRequests` function had a comment acknowledging this limitation: *"Re-use the same endpoint — it returns pending; for analytics we want all statuses. Fall back to pending list for now since there's no all-statuses endpoint."*

**Fix:**
- Backend: Added optional `?status=` query parameter using `Query(None, alias="status")`. Omitting the param returns all statuses; passing `?status=pending` filters to pending only.
- Frontend: `loadPendingRequests` now passes `{ params: { status: 'pending' } }` explicitly. `loadAllRequests` omits the param to receive all statuses, enabling correct analytics counts for approved and rejected requests.

---

## Files Changed

| File | Change |
|---|---|
| `backend/app/routers/schedule_availability.py` | **Deleted** — orphaned, never mounted, no auth |
| `frontend/src/pages/TraineeDashboard.tsx` | Replaced `user.username` UUID-guess with `GET /employees/me` |
| `frontend/src/pages/Incidents.tsx` | Replaced `GET /employees/` scan with `GET /employees/me` |
| `frontend/src/pages/VehicleCompliance.tsx` | Removed phantom `e.first_name` reference |
| `backend/app/routers/employees.py` | Deleted duplicate `DELETE /employees/{id}` soft-delete route |
| `backend/app/routers/schedule_change_requests.py` | Added `?status=` filter param; imported `Query` |
| `frontend/src/pages/ScheduleChanges.tsx` | Wired `?status=pending` on pending fetch; `loadAllRequests` now gets all statuses |

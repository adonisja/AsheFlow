# Journal: Security Audit — Section 2 Role Context Mismatches
**Date:** 2026-04-15

---

## Context

Following the 11 security fixes in Section 1, the audit moved to role context mismatches — places where a role had access to a route or UI element that was inconsistent with its responsibilities. The user clarified two key business rules that drove all decisions:

> "Walkers/trainers won't be submitting check-ins but can rate other walkers/trainers."
> "Dispatch doesn't need access to training data or schedule change requests — it's not their job."

Six mismatches were identified and fixed across frontend route guards, the Navbar, and backend `RoleChecker` dependencies.

---

## Fixes Applied

---

### 2.1 — `/field-ops` Route Excluded Walkers, Trainers, Trainees (MEDIUM)

**File:** `frontend/src/App.tsx`, `frontend/src/components/layout/Navbar.tsx`

**Problem:** The `/field-ops` ProtectedRoute allowed only `['driver', 'admin']`. Walkers, trainers, and trainees had a legitimate use case on the page — submitting post-shift ratings for other walkers. The backend's write endpoints for check-in/departure/inspection/fuel-log already gate by `allow_driver`, so there was no backend exposure risk.

**Fix:**
- `allowedRoles` expanded to `['driver', 'walker', 'trainer', 'trainee', 'admin']`.
- `canAccessFieldOps` in Navbar updated from `groups.includes('driver') || groups.includes('admin')` to `isFieldStaff || groups.includes('admin')` (where `isFieldStaff` covers all four field roles).

---

### 2.2 — Dispatch Could Access Schedule Change Requests (MEDIUM)

**Files:** `frontend/src/App.tsx`, `frontend/src/components/layout/Navbar.tsx`, `backend/app/routers/schedule_change_requests.py`

**Problem:** Dispatch was in `allow_submitter` and `allow_any_auth` on the schedule-change-requests router, and in the frontend `allowedRoles` for `/schedule-changes`. Schedule changes are a field-staff/management concern — dispatch operates on the published schedule and has no role in the request/approval workflow.

**Fix:**
- Backend: removed `"dispatch"` from `allow_submitter` and `allow_any_auth`.
- Frontend App.tsx: removed `'dispatch'` from the `/schedule-changes` `allowedRoles`.
- Navbar: `canAccessScheduleChanges` no longer includes dispatch.

---

### 2.3 — Dispatch Could Access Training Endpoints (LOW)

**File:** `backend/app/routers/training.py`

**Problem:** `GET /training/daily/active` used `RoleChecker(["management", "admin", "dispatch"])`. Dispatch has no operational need for training records — the inclusion appeared to be carry-over from an earlier, broader role set.

**Fix:** Removed `"dispatch"` from the `RoleChecker`. The endpoint is now `["management", "admin"]` only.

---

### 2.4 — `/trainer-dashboard` Route Excluded Admin (LOW)

**File:** `frontend/src/App.tsx`

**Problem:** `allowedRoles` for `/trainer-dashboard` was `['trainer']`. Admins could not access the trainer dashboard to audit training activity or assist with record-keeping.

**Fix:** Expanded to `['trainer', 'admin']`.

---

### 2.5 — Navbar `canAccessScheduleChanges` Included Dispatch (LOW)

**File:** `frontend/src/components/layout/Navbar.tsx`

**Problem:** The `canAccessScheduleChanges` flag computed in Navbar included dispatch via the `isFieldStaff` variable, which at the time of the audit did not include dispatch — but the broader condition was misaligned with backend role policy.

**Fix:** Explicitly documented that `isFieldStaff` covers `['driver', 'walker', 'trainer', 'trainee']` and the `canAccessScheduleChanges` condition was tightened to match the backend.

---

### 2.6 — `FieldOps.tsx` Non-Driver Roles Showed Driver-Only Panels (LOW)

**File:** `frontend/src/pages/FieldOps.tsx`

**Problem:** The panel visibility in the field-ops page was already gated by `isDriver` for check-in, inspection, fuel, and departure panels — but this was not confirmed until the audit. The WalkerRatingPanel was always shown for any field-staff member, which is correct since walkers/trainers/trainees all submit ratings.

**Finding:** No code change needed — panel visibility was already correctly implemented. The fix was validating and documenting the existing behavior.

---

## Files Changed

| File | Change |
|---|---|
| `frontend/src/App.tsx` | `/field-ops` allowedRoles expanded; `/schedule-changes` removed dispatch; `/trainer-dashboard` added admin |
| `frontend/src/components/layout/Navbar.tsx` | `canAccessFieldOps` expanded to all field staff; `canAccessScheduleChanges` dispatch removed |
| `backend/app/routers/schedule_change_requests.py` | Removed dispatch from `allow_submitter` and `allow_any_auth` |
| `backend/app/routers/training.py` | Removed dispatch from `GET /training/daily/active` RoleChecker |

# ADR-030: Security Audit — Section 2 Role Context Mismatches

**Date:** 2026-04-15  
**Status:** Accepted  
**Deciders:** adonisja

---

## Context

Six role context mismatches were identified in the audit. The governing business rules, confirmed by the user, are:

1. **Walkers, trainers, and trainees use `/field-ops` for ratings only** — not check-in, departure, or inspection. Those are driver-only actions already gated at the backend write endpoints.
2. **Dispatch is excluded from the schedule-change and training workflows** — they operate on the published schedule and have no role in the approval or training pipelines.

---

## Decisions

---

### 2.1 — `/field-ops` Route and Navbar Gate

**Decision:** Expand the allowed roles for `/field-ops` to all field staff (`driver`, `walker`, `trainer`, `trainee`) plus `admin`.

**Why:** The WalkerRatingPanel is the reason walkers/trainers/trainees need this page. The driver-only panels (check-in, inspection, fuel, departure) are already gated by `isDriver` within the page component — there is no new backend exposure.

**Alternative rejected:** Creating a separate `/ratings` route. This would require a new page, new route, and duplicate panel extraction. The existing panel architecture already handles the role split within one page.

---

### 2.2 — Dispatch Removed from Schedule Change Requests

**Decision:** Remove `"dispatch"` from `allow_submitter`, `allow_any_auth`, and the frontend route guard.

**Why:** Schedule change requests are initiated by field staff (who set their own availability) and reviewed by management/admin. Dispatch receives the final published schedule and runs dispatch from it — they have no stake in the request/approval pipeline. Their presence in the role sets was incidental.

**Backend consequence:** Any dispatch user hitting `/schedule-change-requests/` now receives 403. This is the correct outcome.

---

### 2.3 — Dispatch Removed from Training Endpoint

**Decision:** Remove `"dispatch"` from `GET /training/daily/active` RoleChecker.

**Why same as 2.2.** Training records (trainee daily sessions, trainer assignments) are an operational concern of trainers, trainees, management, and admin. Dispatch does not need this data to run dispatch.

---

### 2.4 — Admin Added to `/trainer-dashboard`

**Decision:** Add `"admin"` to the `/trainer-dashboard` ProtectedRoute.

**Why:** Admin should be able to audit any part of the system. Restricting the trainer dashboard to trainers only prevents admins from investigating training issues. The backend already allows admin on the underlying training endpoints.

**Why not management?** Management has `/trainee-management` for oversight. The trainer dashboard is operational (daily session management) rather than supervisory — management access is not needed there.

---

## Consequences

**Positive:**
- Role access is now consistent between frontend route guards, Navbar visibility, and backend RoleCheckers on every affected path.
- Walkers, trainers, and trainees can submit post-shift ratings without needing a workaround.
- Dispatch's surface area is scoped to what they actually do: dispatch and incidents.

**Negative / Trade-offs:**
- None. All changes restrict access for dispatch (bringing them to least-privilege) or expand access for roles that already had backend permission.

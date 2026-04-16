# ADR-031: Security Audit — Section 3 Gaps and Cleanup

**Date:** 2026-04-15  
**Status:** Accepted  
**Deciders:** adonisja

---

## Context

Section 3 addressed reliability gaps and dead code found during the codebase audit. No new features were added — the changes either removed incorrect behavior, eliminated dead endpoints/files, or made existing functionality work correctly for all account types.

---

## Decisions

---

### 3.1 — Delete Orphaned `schedule_availability.py`

**Decision:** Delete the file outright.

**Why not keep it unmounted?** An unmounted router is dead code that grows stale. If it were ever accidentally wired into `main.py` it would expose an unauthenticated endpoint — there is no `Depends(get_current_user)` on its `GET /{target_date}`. Deletion eliminates the risk permanently.

**Why not add auth and mount it?** The endpoint's behavior is already provided, with proper auth, by `GET /schedule/available/{target_date}` in `schedule.py`. A second route for the same data would create confusion about which to call.

---

### 3.2 — `GET /employees/me` as the Standard Self-Lookup

**Decision:** Replace all `user.username`-as-UUID patterns and `GET /employees/` + `Array.find()` patterns with `GET /employees/me`.

**Why `GET /employees/me`?** The backend's `get_caller_employee` dependency implements a four-step lookup chain:
1. `cognito_sub` (O(1), stamped on first login)
2. `discord_id`
3. `email`
4. UUID fallback

Any manual lookup the frontend can do is a subset of this chain. The only correct place to resolve "who am I in the DB?" is the backend — it has the lookup logic, the DB, and the JWT claims.

**Why not fix `user.username` → `user.attributes.sub`?** The Cognito sub is the user pool UUID, not the employee DB UUID. They are different identifiers. The mapping happens inside `get_caller_employee` and should not be replicated in the frontend.

**Affected pages:**
- `TraineeDashboard.tsx` — was passing Cognito username to `/training/trainee/{id}` (UUID expected, string received → 422).
- `Incidents.tsx` — was scanning the full `/employees/` list for a match via `discord_id` or `userId`.
- `FieldOps.tsx` — already correct, no change needed.

---

### 3.3 — Remove Phantom `e.first_name` Reference

**Decision:** Replace `e.first_name || e.name` with `e.name` in `VehicleCompliance.tsx`.

**Why not add `first_name` to the Employee model?** The model has a single `name` field by design. The field-ops business domain does not need a first/last name split — a single display name is sufficient. Adding `first_name` to satisfy a frontend typo would be the wrong direction.

---

### 3.4 — Remove `DELETE /employees/{id}`

**Decision:** Delete the route. `PUT /employees/{id}/deactivate` is the canonical endpoint.

**Why not keep both?** Two routes doing the same thing under different HTTP verbs is ambiguous for future callers and creates surface area with no benefit. `PUT /deactivate` is semantically clearer — a soft-delete is not a destructive HTTP DELETE operation; it is a state change.

**Breaking change?** The AsheFlow frontend never calls `DELETE /employees/{id}`. No external callers are known. Acceptable.

---

### 3.5 — `?status=` Filter on `GET /schedule-change-requests/`

**Decision:** Add an optional `?status=` query parameter. Omitting returns all statuses; passing a value filters by it.

**Why optional rather than required?** The management view's primary use case is reviewing pending requests — that view should remain the default when the param is omitted. Making it required would break the existing callers before they can be updated. Optional-with-explicit-pending is the least-surprise path.

**Why `alias="status"` in FastAPI?** The query parameter exposed to the API is `?status=`, matching what a caller would expect. Internally, the Python variable is named `filter_status` to avoid shadowing the `status` module imported from FastAPI.

---

## Consequences

**Positive:**
- TraineeDashboard now loads correctly for all account types (was broken for any user whose Cognito username ≠ their employee DB UUID).
- Incidents self-lookup is O(1) and account-type-agnostic.
- No more dead file that could be accidentally mounted with missing auth.
- Management can now retrieve approved/rejected schedule change history for audits.
- `DELETE /employees/{id}` is gone — there is one, unambiguous deactivation path.

**Negative / Trade-offs:**
- `DELETE /employees/{id}` removal is a breaking change for any external tool using that route. No such tool is known to exist in this project. The risk is accepted.

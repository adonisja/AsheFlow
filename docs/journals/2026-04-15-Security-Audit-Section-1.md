# Journal: Security Audit — Section 1 Fixes
**Date:** 2026-04-15

---

## Context

A full codebase audit identified 11 security issues across the backend and frontend. All were fixed in a single session. Issues ranged from a completely unauthenticated public endpoint (HIGH) to low-risk config hygiene. No database migrations were required.

---

## Fixes Applied

---

### 1.1 — `POST /feedback/` Was Completely Unauthenticated (HIGH)

**File:** `backend/app/routers/feedback.py`

**Problem:** `create_feedback` had no auth dependency. Any unauthenticated HTTP client could POST feedback without a JWT.

**Fix:** Added `Depends(get_current_user)` to `create_feedback`. Any request without a valid Bearer token now receives a 401. The read endpoint (`GET /feedback/`) already required management/admin and was not changed.

---

### 1.2 — `GET /incidents/my` Leaked Any Employee's Incident History (MEDIUM)

**File:** `backend/app/routers/incidents.py`, `frontend/src/pages/Incidents.tsx`

**Problem:** The endpoint accepted `reporter_id` as a query parameter and returned that employee's full incident history. There was no check that the supplied UUID matched the authenticated caller. Any field-staff member could read a colleague's history by guessing or knowing their UUID.

**Fix:**
- Removed the `reporter_id: UUID = Query(...)` parameter entirely.
- Added `caller: Employee = Depends(get_caller_employee)` — the endpoint now resolves the reporter from the JWT and filters by `caller.id`.
- Frontend updated: removed `{ params: { reporter_id: employeeId } }` from the `GET /incidents/my` call — the server now determines ownership implicitly.

---

### 1.3 — `POST /incidents/` Allowed Reporter Identity Forgery (MEDIUM)

**Files:** `backend/app/routers/incidents.py`, `backend/app/schemas/incident.py`, `frontend/src/pages/Incidents.tsx`

**Problem:** `IncidentCreate` accepted `reporter_id` from the request body. Any authenticated field-staff member could file an incident attributed to a different employee's UUID — the backend performed no ownership check.

**Fix:**
- Removed `reporter_id` from `IncidentCreate`. The schema comment documents why it is absent.
- Added `reporter: Employee = Depends(get_caller_employee)` to `submit_incident`. The reporter is now always the authenticated caller.
- `Incident(reporter_id=reporter.id, ...)` — identity sourced from the JWT, not the payload.
- `_resolve_assignment` now receives `reporter.id` instead of `payload.reporter_id`.
- Frontend updated: removed `reporter_id: employeeId` from the POST body.

---

### 1.4 — Base64 Photos Stored with No Size Cap (MEDIUM)

**Files:** `backend/app/schemas/field_ops.py`, `backend/app/schemas/incident.py`

**Problem:** `photo_url` fields on `CheckIn`, `Departure`, and `Incident` were `Text` columns accepting raw base64 data-URIs with no byte-length validation. An oversized payload would bloat Postgres with no server-side rejection.

**Fix:** Added `@field_validator("photo_url")` (and `itinerary_photo_url`) to `CheckInCreate`, `DepartureCreate`, and `IncidentCreate`. Any payload exceeding 5 MB (UTF-8 encoded) is rejected with a 422 before the DB is touched. The 5 MB limit accommodates high-resolution field photos while preventing abuse.

The cap is enforced at the Pydantic schema layer — the SQLAlchemy models retain `Text` columns, which is correct since a future migration to S3 URLs would leave the column type unchanged while removing the base64 content entirely.

---

### 1.5 — `continuation_requests.py` Admin Bypass Never Fired (MEDIUM)

**File:** `backend/app/routers/continuation_requests.py`

**Problem:** `set_request_priority` used `current_user.get("groups", [])` — the wrong key. Every other router uses `"cognito_groups"`. The result was always `[]`, so `"admin" not in caller_groups` was always `True`, blocking admins from the priority endpoint exactly as if they were ordinary trainers. Additionally, the employee lookup used a fragile `discord_id == username` query instead of `get_caller_employee`.

**Fix:**
- Added `caller_employee: Employee = Depends(get_caller_employee)` to the endpoint signature — no manual DB lookup needed.
- Changed `current_user.get("groups", [])` → `current_user.get("cognito_groups", [])`.
- The ownership check now uses `caller_employee.id != req.trainer_id` (always reliable, no None-guard needed).

---

### 1.6 — Schedule Change Approvals/Rejections Had NULL `reviewed_by` (MEDIUM)

**File:** `backend/app/routers/schedule_change_requests.py`

**Problem:** Both `approve_schedule_change_request` and `reject_schedule_change_request` resolved the reviewer by querying `Employee.discord_id == current_user.get("username", "")`. Cognito usernames can be email addresses, not Discord IDs — so the lookup returned `None` on any non-Discord account. `reviewed_by` was stamped as `NULL` on every approval and rejection, losing the audit trail entirely.

**Fix:**
- Added `reviewer: Employee = Depends(get_caller_employee)` to both handlers — the dependency handles all lookup fallbacks (cognito_sub → discord_id → email → UUID) correctly.
- Removed the manual `db.query(Employee).filter(discord_id == ...)` queries from both handlers.
- Changed `req.reviewed_by = reviewer.id if reviewer else None` → `req.reviewed_by = reviewer.id` — `get_caller_employee` raises 403 if no record is found, so `reviewer` is always a valid Employee.

---

### 1.7 — `verify_aud: False` Bypassed PyJWT Audience Validation (LOW-MEDIUM)

**File:** `backend/app/core/security.py`

**Problem:** `jwt.decode(..., options={"verify_aud": False})` was used for all tokens, with a manual `payload.get("client_id") or payload.get("aud")` check afterward. The manual check was functionally equivalent but fragile — if it were accidentally removed, tokens from any Cognito app in the same user pool would be accepted.

**Fix:** The decoder now handles both Cognito token types explicitly:
- **ID tokens** (have `aud` claim): decoded with `audience=settings.aws_cognito_app_client_id` — PyJWT validates audience natively and raises `InvalidAudienceError` if it doesn't match.
- **Access tokens** (no `aud`, have `client_id`): caught via `except jwt.InvalidAudienceError`, re-decoded with `verify_aud: False`, then `client_id` is validated manually.

This ensures PyJWT's cryptographic audience check is used when the claim is present, while still supporting both token types.

---

### 1.8 — JWKS Cache Had No Key-Rotation Handling (LOW)

**File:** `backend/app/core/security.py`

**Problem:** `_jwks_cache` was a raw blob fetched once on first request and never refreshed. AWS rotates Cognito signing keys periodically. After a rotation, any new token's `kid` would not be in the cache, and every subsequent request would fail with "Public key not found" until the service was restarted.

**Fix:**
- Cache restructured from a raw blob to a `kid → key dict` (`dict[str, dict]`) for O(1) key lookup.
- `_fetch_jwks()` extracted as a standalone function returning the same `kid → key` mapping.
- `verify_cognito_token` now attempts a **single cache refresh** on a `kid` miss before failing:
  ```python
  key_data = jwks.get(kid)
  if not key_data:
      _jwks_cache = _fetch_jwks()   # key rotation — re-fetch once
      key_data = _jwks_cache.get(kid)
  if not key_data:
      raise HTTPException(401, "Public key not found.")
  ```
  This handles rotation transparently without restarting the service. A genuinely forged token (unknown `kid` that doesn't appear after a re-fetch) still fails correctly.

---

### 1.9 — Database Password Hardcoded in Source Code (LOW)

**File:** `backend/app/core/config.py`, `backend/.env`

**Problem:** `database_url` had `"postgresql://asheflow:asheflow_dev_password@localhost:5432/asheflow_db"` as its Pydantic default value. Even though `.env` overrides it in development, the credential was committed to source control and would silently be used if `DATABASE_URL` was ever missing from the environment — including in production if `.env` was misconfigured.

**Fix:**
- Removed the default value from `database_url: str`. Pydantic will now raise a clear `ValidationError` at startup if `DATABASE_URL` is not set — a loud failure is preferable to silently connecting to a hardcoded dev credential.
- Added `DATABASE_URL=postgresql://asheflow:asheflow_dev_password@localhost:5432/asheflow_db` to `backend/.env`. The credential now lives only in the env file (which is gitignored), not in source code.

---

### 1.10 — 401 Response Interceptor Was Unimplemented (LOW)

**File:** `frontend/src/api/axiosClient.ts`

**Problem:** The response interceptor had a comment placeholder where the 401 handler should be. When a JWT expired mid-session, all API calls silently returned errors with no user feedback and no redirect to login.

**Fix:** The interceptor now:
1. Calls `signOut()` from `aws-amplify/auth` to clear the Cognito session.
2. Redirects to `/login` via `window.location.href`.
3. Catches any `signOut()` failure (e.g. already signed out) so the redirect still happens regardless.

---

### 1.11 — `baseURL` Hardcoded to `localhost` (LOW)

**File:** `frontend/src/api/axiosClient.ts`

**Problem:** `baseURL: 'http://localhost:8000/api/v1'` was a compile-time constant. A staging or production build would point every API call at the user's own machine.

**Fix:** `baseURL` is now read from `import.meta.env.VITE_API_URL` — a Vite environment variable already present in `frontend/.env`. The `localhost` value is retained as a fallback (`?? 'http://localhost:8000/api/v1'`) so local development continues to work if `.env` is absent, but any non-local environment must explicitly set `VITE_API_URL`.

---

## Files Changed

| File | Change |
|---|---|
| `backend/app/routers/feedback.py` | Added `Depends(get_current_user)` to `POST /feedback/` |
| `backend/app/routers/incidents.py` | Removed `reporter_id` query param from `GET /my`; resolved reporter from JWT on `POST /`; added `get_caller_employee` import |
| `backend/app/schemas/incident.py` | Removed `reporter_id` from `IncidentCreate`; added 5 MB photo validator |
| `backend/app/schemas/field_ops.py` | Added 5 MB photo validator to `CheckInCreate` and `DepartureCreate` |
| `backend/app/routers/continuation_requests.py` | Fixed `cognito_groups` key; replaced manual employee lookup with `get_caller_employee` |
| `backend/app/routers/schedule_change_requests.py` | Replaced manual reviewer lookup with `get_caller_employee` in both `approve` and `reject` handlers |
| `backend/app/core/security.py` | Restructured JWKS cache; added key-rotation retry; native PyJWT audience validation for ID tokens |
| `backend/app/core/config.py` | Removed hardcoded `database_url` default |
| `backend/.env` | Added `DATABASE_URL` |
| `frontend/src/api/axiosClient.ts` | `baseURL` from `VITE_API_URL`; implemented 401 `signOut()` + redirect |
| `frontend/src/pages/Incidents.tsx` | Removed `reporter_id` from POST body; removed `reporter_id` param from `GET /my` |

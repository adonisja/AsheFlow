# ADR-029: Security Audit — Section 1 Fixes

**Date:** 2026-04-15  
**Status:** Accepted  
**Deciders:** adonisja

---

## Context

A full codebase audit identified 11 security issues. This ADR records the decisions made for each fix, including alternatives considered and trade-offs accepted.

---

## Decisions

---

### 1.1 — Feedback Endpoint Authentication

**Decision:** Require a valid JWT on `POST /feedback/` using `get_current_user`.

**Why not `RoleChecker`?** Feedback is intentionally open to all staff roles — restricting by role would exclude walkers, drivers, or trainees who might have legitimate feedback. `get_current_user` authenticates without role-gating.

---

### 1.2 & 1.3 — Incident Ownership: Remove Client-Supplied IDs

**Decision:** Remove `reporter_id` from both the query param on `GET /incidents/my` and the request body on `POST /incidents/`. Resolve identity exclusively from the authenticated JWT via `get_caller_employee`.

**Why remove rather than validate?** Validating that `payload.reporter_id == caller.id` is a weaker fix — it adds a check but still requires the client to send a value that the server ignores when it matches. Removing the field entirely eliminates the attack surface: there is nothing to forge. The client can still know who the reporter is because they are the authenticated caller.

**Schema implication:** `IncidentCreate` no longer has `reporter_id`. This is a breaking API change for any external client directly POSTing incidents. Acceptable because the only client is the AsheFlow frontend, which was updated in the same commit.

---

### 1.4 — Photo Size Cap at the Schema Layer

**Decision:** Enforce the 5 MB cap in Pydantic validators, not in SQLAlchemy column definitions (`String(length=...)`) or application middleware.

**Why Pydantic?** A `String(5_000_000)` column type in SQLAlchemy would silently truncate on some DB drivers or raise a DB-level error on others — neither produces a clean 422 with a useful message. A Pydantic `field_validator` runs before the DB is touched, returns a structured 422 with the message "photo_url exceeds the 5 MB size limit", and is easy to adjust without a migration.

**Why 5 MB?** A high-resolution mobile photo is typically 3–8 MB uncompressed. Base64 encoding adds ~33% overhead, so a 5 MB cap allows roughly a 3.75 MB binary image — sufficient for a field incident photo. The cap is intentionally generous; it is a safety net against abuse, not a quality constraint.

**Future path:** When photos are migrated to S3 pre-signed URLs, the `photo_url` field will store an S3 object key (a short string). The validator can be relaxed or removed at that point. Keeping the validator in Pydantic makes this change straightforward.

---

### 1.5 — Continuation Request Priority: Use `get_caller_employee`

**Decision:** Replace the manual `discord_id == username` lookup and the `current_user.get("groups", [])` key with `get_caller_employee` + `current_user.get("cognito_groups", [])`.

**Why not fix just the key?** The manual employee lookup was also fragile (same `discord_id` vs. email problem as 1.6 below). Fixing both in one edit avoids a half-fixed state where the admin group check works but the ownership check can still return None for non-Discord accounts.

---

### 1.6 — Schedule Change Reviewer Attribution: Use `get_caller_employee`

**Decision:** Replace the manual `discord_id` query in both `approve` and `reject` with `get_caller_employee`.

**Why is `get_caller_employee` the right fix?** It implements a four-step lookup chain: `cognito_sub` (fast path, stamped after first login) → `discord_id` → `email` → UUID fallback. It handles every account type correctly and stamps `cognito_sub` for future fast-path lookups. Any manual lookup will always be a subset of this chain.

**Consequence:** `reviewer` is now guaranteed non-None (or the request fails with 403 before reaching the approval logic). The `reviewer.id if reviewer else None` guard was removed — it was masking the bug rather than fixing it.

---

### 1.7 — JWT Audience Validation: Native PyJWT for ID Tokens

**Decision:** Use PyJWT's native `audience=` parameter for ID tokens; fall back to manual `client_id` check for access tokens via `except jwt.InvalidAudienceError`.

**Why handle both token types?** Cognito issues two token types:
- **ID tokens** carry `aud` (audience) set to the app client ID — standard OIDC.
- **Access tokens** carry `client_id` in the payload but no `aud` claim.

The app currently uses ID tokens (`session.tokens?.idToken`), so the native PyJWT path will always be taken. The access token fallback is included so that if the auth config is ever changed to use access tokens, the backend continues to work correctly without a code change.

**Why not just always use `verify_aud: False`?** The manual check is equivalent today, but it is one deletion away from being completely absent. Native PyJWT validation is part of the cryptographic chain and cannot be accidentally removed without also removing the decode call itself.

---

### 1.8 — JWKS Cache: Retry on Key Miss

**Decision:** On a `kid` miss, force one JWKS re-fetch before failing. Do not add a TTL-based expiry.

**Why retry on miss rather than TTL expiry?** AWS Cognito key rotations are infrequent (months). A TTL (e.g., 24 hours) would cause unnecessary network requests during normal operation. The miss-based retry handles rotation with zero overhead during the typical case (cache hit) and one extra network request in the exceptional case (rotation). This is the standard pattern used by all major Cognito SDK implementations.

**Why only one retry?** Two retries could mask a genuine forgery (unknown `kid` that never appears). One retry is sufficient to distinguish "key was rotated" (new `kid` appears after re-fetch) from "kid is forged" (still absent after re-fetch).

**Cache structure change:** From `{keys: [...]}` blob to `{kid: key_dict}` mapping. This makes key lookup O(1) and makes the re-fetch path clean — the global is simply replaced with the new mapping.

---

### 1.9 — Database URL: No Default in Config

**Decision:** Remove the hardcoded default from `database_url` in `config.py`. Add the value to `backend/.env`.

**Why loud failure over silent fallback?** A missing `DATABASE_URL` at startup now raises a Pydantic `ValidationError` with a clear message. This is preferable to silently connecting to a dev database in production because the operator misconfigured the environment. Loud failures at boot are always preferable to silent wrong-state failures at runtime.

**The dev password is still in `.env`.** The `.env` file is gitignored. The credential is no longer in tracked source files. This is the correct boundary — `.env` is a local secret store, `config.py` is code.

---

### 1.10 — 401 Interceptor: Sign Out and Redirect

**Decision:** On a 401 response, call `signOut()` then redirect to `/login` via `window.location.href`.

**Why `window.location.href` rather than React Router `navigate()`?** The interceptor lives outside the React component tree and has no access to the router context. `window.location.href` is the correct escape hatch here — it also performs a full page reload, which clears any in-memory state that might be tied to the expired session.

**Why catch `signOut()` failure?** The user might already be in a partially signed-out state (e.g., Cognito session expired locally). A failing `signOut()` should not block the redirect to login.

---

### 1.11 — API Base URL: Environment Variable

**Decision:** Read `baseURL` from `import.meta.env.VITE_API_URL` with a localhost fallback.

**Why keep the fallback?** Local development with a missing `.env` would break entirely without it. The fallback is an acceptable developer experience trade-off. In staging/production, `VITE_API_URL` must be set explicitly — if it is missing, the app will hit `localhost` from the user's browser, which will fail immediately and visibly.

**`VITE_API_URL` was already in `frontend/.env`** — no new variable needed. The old `axiosClient.ts` was simply not reading it.

---

## Consequences

**Positive:**
- The two highest-severity issues (unauthenticated feedback endpoint, incident history leak) are fully closed.
- Reporter identity on incidents is now cryptographically tied to the authenticated session — no forgery possible.
- JWKS cache survives AWS key rotations without a service restart.
- `reviewed_by` audit trail on schedule changes is now reliably populated.
- Admin bypass in continuation requests now actually works.
- JWT expiry produces an immediate, visible login redirect rather than silent failures.

**Negative / Trade-offs:**
- `POST /incidents/` is a breaking API change (removed `reporter_id` from body). Only the AsheFlow frontend calls this endpoint — both were updated in the same session.
- `GET /incidents/my` no longer accepts a `reporter_id` query param — any external script or tooling using that param must be updated.
- Removing the `database_url` default means local dev setup now requires `DATABASE_URL` in `.env`. This is documented and the value has been added to the existing `.env` file.

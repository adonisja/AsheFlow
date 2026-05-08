# 2026-05-07 — Multi-Tenant Foundation

## What was built

Phase 1, Step 1 of the multi-tenant migration. Three new tables created and
seeded; no existing tables modified yet.

## Key decisions made in discussion before coding

- **Single-database isolation** (company_id on every table) chosen over
  schema-per-tenant — right tradeoff at under 10 companies
- **Role hierarchy**: super_admin (platform owner) → admin (per-company) →
  management / dispatch / field roles
- **Config strategy**: all hardcoded constants become nullable columns in
  company_configs; NULL falls back to the legacy hardcoded value
- **Zone storage**: GeoJSON JSONB for now; PostGIS deferred until route
  optimization work begins
- **Seed company ID**: `a0000000-0000-0000-0000-000000000001` — the existing
  DSP test company with all legacy default values

## Infrastructure also completed this session

- `asheflow.com` registered on Route 53
- SES domain verified in us-east-2 (DKIM + SPF records in Route 53)
- SES production access request submitted (pending AWS approval)
- Cloudflare Turnstile selected for public /recruit page CAPTCHA

## Phase 1, Step 2 — completed same session

- Migration `h2b3c4d5e6f7`: added `company_id` to all 32 tables, backfilled seed company, NOT NULL + FK set
- All 26 ORM model files updated with `company_id` column
- `audit_logs` kept nullable (no FK) — supports super_admin cross-company actions
- All models import cleanly

## Phase 1, Step 3 — completed same session

- Migration `h3c4d5e6f7g8`: `username` column added to employees, unique index
- 2 of 8 test accounts seeded (only 2 had employee DB records — the rest were
  Cognito-only and will be recreated in the new pool)
- `Employee.username` added to ORM model
- `deps.py` lookup chain updated: cognito_sub → username → discord_id (old pool fallback) → email → UUID

## Phase 1, Step 4 — completed same session

- New pool AsheFlow-v2 created (ID in `backend/.env`)
- App client created (see `frontend/.env`)
- 9 groups created including new `super_admin`
- All 8 test accounts created with permanent passwords
- `asheflow.bot` and `test.user` cognito_sub stamped in DB
- `backend/.env` and `bot/.env` updated to new pool
- IAM role `AsheFlow-CognitoSMSRole` created for SMS MFA
- SES wired — emails send from `noreply@asheflow.com`
- Known: SNS still in sandbox, federated providers not yet re-wired

## Federated providers — completed same session

- Hosted UI domain `asheflow-auth` created and active
- Discord OIDC provider re-wired to new pool
- Google provider re-wired to new pool
- Both added to app client `SupportedIdentityProviders`
- Redirect URIs updated in Discord Developer Portal and Google Cloud Console
- End-to-end sign-in test still pending (noted in FEDERATED_IDENTITY_PROVIDERS.md)

## Phase 1, Step 5 — completed same session

- **Root cause of stale pool ID**: Shell had `AWS_COGNITO_USER_POOL_ID` with the old pool
  exported in `~/.zshrc` — pydantic-settings prioritises environment variables over `.env`.
  Updated `.zshrc` to new pool values; old values left as comments.
- **`security.py` bug fix**: `verify_cognito_token` only caught `InvalidAudienceError` as the
  fallback to the access-token path, but PyJWT raises `MissingRequiredClaimError` when `aud`
  is absent entirely. Added `MissingRequiredClaimError` to the except tuple.
- **JWT round-trip verified**: `asheflow.bot` (dispatch) and `test.user` (admin) both
  authenticate on new pool; access token and ID token both verify cleanly.
- **company_id propagation through dispatch layer**: All endpoints in `dispatch.py` converted
  from `current_user: dict` to `caller: Employee`; all queries scoped by `caller.company_id`.
  `run_dispatch` service updated to accept and propagate `company_id`; `TruckAssignment` and
  `AssignmentMember` rows now carry `company_id`. `graduate_trainees` service Notifications
  now stamped with `trainee.company_id`.
- **Test suite fixed**: All test fixtures and test files updated to pass `SEED_COMPANY_ID`
  (`a0000000-0000-0000-0000-000000000001`) to all models that gained `NOT NULL company_id`.
  Stale `TestExcessTrainerReSlot` test updated to reflect current business rule (excess
  trainers stay as trainers, not re-slotted as walkers). **97 / 97 tests passing.**
- **Cleanup backlog noted**: Stale `MIN_TRAINERS_PER_TRUCK` cap logic and `_SEED_COMPANY_ID`
  fallback in services to be removed in a dedicated cleanup pass after Phase 1.

## Documentation completed same session

- `ADR-067` — Route 53 domain registration, SES setup, Cloudflare Turnstile selection
- `ADR-068` — JWT pool migration fix: shell env override root cause + `MissingRequiredClaimError` bug
- `ADR-069` — Dispatch router multi-tenant conversion: `caller: Employee`, `company_id` propagation, test suite fixes
- `LEARNING_GUIDE.md` — three new entries: pydantic-settings env priority, PyJWT access token claim shape, pass company_id into services explicitly

## Phase 1, Steps 6-7 — completed same session

- `frontend/.env` updated: pool ID, client ID, OAuth domain (`asheflow-auth`)
- `frontend/.env.template` rewritten as a plain env file (was malformed JS)
- `frontend/src/main.tsx`: Amplify `loginWith` changed from `email: true` → `username: true`
- `frontend/src/components/auth/Login.tsx`: field renamed from "Email" to "Username", `type="email"` → `type="text"`, state var `email` → `username`, placeholder updated to `danny.rivera`
- `frontend/src/contexts/AuthContext.tsx`: `displayName` now derived from `currentUser.username` (Cognito username, e.g. `danny.rivera`) instead of `email.split('@')[0]`
- `mobile/.env` updated: pool ID and client ID to new pool
- `mobile/src/contexts/AuthContext.tsx`: `buildUserFromToken` now uses `cognito:username` as the `firstName` placeholder instead of `email.split('@')[0]`; mobile login screen was already username-based, no change needed

## Up next

- End-to-end login test on the frontend (username + password with new pool)
- Test Discord federated sign-in end to end (hosted UI domain `asheflow-auth`)
- Test Google federated sign-in end to end

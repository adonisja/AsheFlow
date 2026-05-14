# Engineering Journal: 2026-05-13

**Session Start Time**: resuming from 2026-05-10 session
**Session End Time**: ~ongoing

## Goal for the Session

Post-rectification cleanup: fix the ENV-3 CI blocker identified during the full project evaluation, delete two dead files missed by SEC-9, and begin the production deployment planning phase.

## Problems Encountered

**ENV-3 guard blocks CI**
The ENV-3 localhost CORS origins check fires when `"localhost" in cors_origins and app_env != "development"`. GitHub Actions sets `APP_ENV=test`, and `cors_origins` defaults to seven localhost ports when `CORS_ORIGINS` is not set in the CI env block. The guard correctly identifies "localhost in a non-dev environment" and raises `RuntimeError` — blocking `Settings()` import and crashing every test before any test code runs.

The initial attempted fix was to add `CORS_ORIGINS: "http://localhost:5173"` to the CI env block. This fails too: the value still contains `"localhost"`, so the guard still fires.

**Two dead files missed by SEC-9**
`fix_walkers.py` at the repo root was a dev script not caught by SEC-9 because that audit targeted `backend/` only. `docker-compose.redacted.yml` was the renamed original compose file, superseded by the new three-file structure.

## Solutions & Procedures

**ENV-3 CI fix:**
Changed the guard condition from `app_env != "development"` to `app_env not in {"development", "test"}`. `"test"` is the explicit `APP_ENV` value in CI — it is not a deployment environment, so localhost CORS is acceptable there by design.

Did not add `CORS_ORIGINS` to the CI env block as an alternative fix — that approach creates a maintained value that duplicates the intent already captured in the guard. The guard exemption is self-documenting; the env var is a workaround that obscures why it's there.

Reverted the `CORS_ORIGINS` addition to `ci.yml` that was added during diagnosis.

```python
# Before (broke CI):
if "localhost" in self.cors_origins and self.app_env != "development":

# After (correct):
if "localhost" in self.cors_origins and self.app_env not in {"development", "test"}:
```

**Dead file cleanup:**
Confirmed zero references with `grep -r fix_walkers backend/ .github/` and `grep -r docker-compose.redacted .` before deleting both files. No imports, no workflow references, no documentation references.

## Deployment Blockers Resolved

**Blocker 1 — ENV-3 guard breaks CI:** Fixed (see above).

**Blocker 2 — Dockerfile Python version mismatch:** `backend/Dockerfile` used `python:3.11-slim`; CI and local `.venv` use 3.12. Updated to `python:3.12-slim`.

**Blocker 3 — `ENVIRONMENT` vs `APP_ENV` mismatch in docker-compose.yml:** `Settings` reads `APP_ENV` but `docker-compose.yml` injected `ENVIRONMENT`. ENV-2 and ENV-3 guards were never firing in non-production docker-compose environments. Fixed: `docker-compose.yml` now passes `APP_ENV=${APP_ENV:-development}`. Root `.env.example` updated to match.

**Blocker 4 — `backend/.env.example` severely incomplete:** The old file had only three lines (Cognito vars). Updated to document all vars required by `Settings` and `docker-compose.prod.yml`, with generation instructions for secrets and CORS guidance for production.

**Blocker 5 — Dead code in Lambda `_extract_email`:** Lines 47-48 were a for loop over `.items()` with `pass` — the loop body did nothing. Removed the dead loop. `function.zip` re-zipped with the fixed handler.

**Blocker 6 — Cognito pre-signup Lambda deployment status unknown:** Console verification required: check AWS Lambda for the function, verify `USER_POOL_ID` env var, confirm IAM role has `cognito-idp:ListUsers`, and verify the trigger is wired in Cognito user pool settings.

**Blocker 7 — SES still in sandbox:** Production access request was submitted (ADR-067). AWS approval is still pending. No emails will reach unverified addresses until approved. Check AWS console and follow up if approval has not arrived.

**Blocker 8 — Frontend dist/ baked with localhost URL:** Created `frontend/.env.production` with `VITE_API_URL=https://api.asheflow.com/api/v1`. Vite automatically loads `.env.production` during `npm run build` — no manual env var needed. The current `dist/` is stale; rebuild before uploading to S3.

**Blocker 9 — Mobile production URL:** Created `mobile/.env.production.example` documenting the correct `ASHEFLOW_API_URL=https://api.asheflow.com/api/v1` for production builds. Copy to `.env` before running the release build.

**Remaining console-only steps (not in code):**
1. EC2: provision instance, install Docker + Compose, clone repo, copy `.env` files, run `alembic upgrade head`, `docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d`
2. Route 53: add A record for `api.asheflow.com` → EC2 public IP
3. CloudFront: create distribution pointing at S3 bucket containing `frontend/dist/`, alias `asheflow.com`
4. Cognito Lambda: verify deployed and wired
5. SES: check production access approval status

## Key Takeaways

- When writing a startup guard that allowlists safe environments, enumerate the full set explicitly: `{"development", "test"}`. `!= "development"` is an implicit claim that every other name is production-like — a claim that breaks the first time CI or a test runner uses a different `APP_ENV` value.
- A guard exemption belongs in the guard, not in the CI env block. Adding a fake/placeholder env var to silence a guard treats the symptom; exempting the environment in the guard documents the intent.
- Dead script audits should search from the repo root, not a subdirectory. SEC-9 targeted `backend/` and missed `fix_walkers.py` at root level. The correct command is `find . -name "*.py" -maxdepth 1` or searching from `.` with no path restriction.
- Superseded config files (old compose, old workflow drafts) should be deleted immediately when the replacement is committed — not renamed. Renamed files sit in the repo, appear in git status, and confuse future contributors.

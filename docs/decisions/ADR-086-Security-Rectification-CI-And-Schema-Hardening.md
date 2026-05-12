# ADR-086: Security Rectification — CI Pipeline and Schema Input Validation Hardening (CI-1, SEC-5, SEC-6, SEC-7, SEC-8)

## Context

A full security audit was conducted against OWASP Top 10 (2021 and 2025 editions) as part of Lecture 14 coursework on Secure Application Development. The audit identified 19 open findings across three categories: environment/infrastructure (ENV), CI/DevOps automation (CI), and code-level security (SEC).

This ADR covers the first two findings addressed in the rectification session:

**CI-1:** The project had no automated CI pipeline. Every push to `master` was unverified — broken code could land silently with no test run and no notification.

**SEC-5:** Three schema fields across `feedback.py` accepted unconstrained `str` values where only a finite set of values is valid. The router was performing manual validation with `if value not in _VALID_STATUSES` inside the route handler — too late in the request lifecycle. Invalid values were accepted by Pydantic, constructed into Python objects, and passed through the full dependency chain before being caught.

## Considered Options

**CI-1 — CI Pipeline:**
* Option 1: GitHub Actions workflow (`.github/workflows/ci.yml`) — free, integrated with the existing GitHub remote, no additional tooling required
* Option 2: Local pre-commit hooks — runs tests before each commit locally, but gives no protection on the server side and doesn't run for other contributors
* Option 3: No CI — status quo, rely on manual testing

**SEC-5 — Schema validation:**
* Option 1: `Literal` type in Pydantic — enforces the allow list at deserialization, before any route handler code runs
* Option 2: Keep manual `if value not in set` checks in router — validation happens after the object is constructed and passed through dependencies
* Option 3: Custom `field_validator` — more flexible but verbose for simple fixed sets

## Trade-offs

**GitHub Actions** is the correct choice for CI: it runs on every push with no local setup required, results are visible on GitHub per-commit, and failure notifications are sent automatically by email. Pre-commit hooks are additive but not a replacement — they only protect the committing developer.

**`Literal`** is the correct choice for fixed-set validation: it is the most declarative form, requires no custom code, integrates with FastAPI's automatic 422 response generation, and moves rejection to the earliest possible point. Manual router checks are redundant once `Literal` is in place and represent a violation of the principle that validation belongs at the system boundary, not inside business logic.

## Decision

**CI-1:** Added `.github/workflows/ci.yml` that triggers on every push and PR. Uses SQLite in-memory (already used by `conftest.py`) so no Postgres service container is needed. Fake environment variables satisfy `Settings()` validation at import time without exposing real credentials. Pins Python 3.12 to match the local `.venv`.

**SEC-5:** Replaced unconstrained `str` with `Literal` on three fields in `backend/app/schemas/feedback.py`:
- `FeedbackBase.type`: `Literal["bug", "feature_request", "general"]`
- `FeedbackResponse.status`: `Literal["new", "in_progress", "resolved"]`
- `FeedbackStatusUpdate.status`: `Literal["new", "in_progress", "resolved"]`

Also removed stray `import pytest` and `from pydantic import ValidationError` that had been pasted into the schema file by accident, and removed an incomplete `def` at the end of the file.

**SEC-8:** Added `app_env: str = "development"` as a proper Pydantic field to `Settings`. Added `get_cors_methods()` and `get_cors_headers()` helpers backed by `cors_allow_methods` and `cors_allow_headers` str fields. Updated `main.py` to call both helpers instead of hardcoding `["*"]`. Methods and headers return `["*"]` in development, explicit allow-lists in all other environments. Removed now-unused `import os` from `__init__`.

**SEC-7:** Replaced `email: str` with `email: EmailStr` (and `Optional[EmailStr]` on update/response schemas) across `EmployeeCreate`, `EmployeeUpdate`, `EmployeeResponse`, `BulkImportRow`, and `BulkImportResult` in `backend/app/schemas/employee.py`. `pydantic[email]` was already a dependency — no new packages required.

**SEC-6:** Added `Field(min_length=1, max_length=100)` to `TruckCreate.name` and `TruckUpdate.name` in `backend/app/schemas/truck.py`. Used `Field(None, ...)` on `TruckUpdate.name` (optional PATCH field) and `Field(..., ...)` on `TruckCreate.name` (required POST field).

**ENV-4:** Moved JWKS cache from an in-process module-level dict (`_jwks_cache: dict`) to Redis (`jwks_cache` key, 1-hour TTL) in `backend/app/core/security.py`. The dict was per-replica — with `--workers 4`, each uvicorn process fetched JWKS independently and held stale keys after AWS rotation until restart, causing intermittent 401s. Redis is shared across all workers; a cache miss by one worker immediately fixes it for all. Used synchronous `redis.Redis` client (not `redis.asyncio`) to avoid cascading async refactor through `get_current_user` and `deps.py`. Scaling note preserved in code: migrate to async Redis if concurrency ever demands it.

**ENV-1 + ENV-5:** Introduced three-file Docker Compose structure to separate dev from production topology.
- `docker-compose.yml` (base): environment-neutral service definitions — no volume mounts, no `--reload`, no `--beat`
- `docker-compose.override.yml` (dev, auto-loaded): adds volume mounts, `--reload`, and `--beat` for local development
- `docker-compose.prod.yml` (production, explicit): sets `APP_ENV=production`, runs uvicorn with `--workers 4`, and splits Celery into separate `celery_worker` (tasks) and `celery_beat` (scheduler) containers — prevents double-firing of scheduled jobs under horizontal scaling

Usage: `docker-compose up` for dev (override auto-loaded); `docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d` for production.

**ENV-2:** Changed `INTERNAL_SECRET` guard in `Settings.__init__` from `app_env == "production"` to `app_env != "development"`. The original condition silently skipped staging, test, and any unrecognised environment name. The new condition blocks all non-dev environments — only `"development"` is exempt.

**ENV-3:** Added startup check in `Settings.__init__`: if `cors_origins` contains `"localhost"` and `app_env != "development"`, raise `RuntimeError`. Prevents a misconfigured staging deploy from booting with localhost CORS defaults. First attempt used `"local_host"` (underscore) — silently broken, never matched. Fixed to `"localhost"`.

**SEC-9:** Deleted seven dead dev scripts from `backend/`: `add_trainees.py`, `add_one_more_trainee.py`, `add_trainee_fields.py`, `alter_db.py`, `create_dispatch.py`, `create_fake_dispatch.py`, `seed.py`. All bypassed authentication, role checks, company_id scoping, and audit logging. Two ran raw DDL directly against the engine, bypassing Alembic. `seed.py` contained hardcoded UUIDs mapping to real test accounts. None were imported or referenced anywhere in the application or test suite.

**SEC-4:** Eliminated SSRF risk from `_send_discord_invite` in `backend/app/api/deps.py`. `BOT_INTERNAL_URL` was read via `os.environ.get` with no validation — any URL including `http://169.254.169.254` (AWS IMDS) was accepted. Fix: moved `bot_internal_url` into `Settings` as a proper Pydantic field with a `@field_validator` that enforces scheme (`http`/`https` only) and hostname against `_ALLOWED_BOT_HOSTS = {"bot", "localhost", "127.0.0.1"}`. A bad value now raises `ValidationError` at startup before any request is served. Also removed `import os` from `_send_discord_invite` (now unused) and replaced both `os.environ.get` calls with `settings.bot_internal_url` and `settings.internal_secret`.

**SEC-3:** Eliminated the dual-source-of-truth for roles. `RoleChecker` previously read role from the JWT (`cognito_groups`), while `assert_owns_or_privileged` read from `Employee.role` in the database — these could diverge for up to one JWT TTL (≤1 hour) after a role change, leaving a demotion window where a former admin's token still passed `RoleChecker`. Fix: `RoleChecker.__call__` now looks up the `Employee` row by `cognito_sub` (indexed fast path) and checks `employee.role` as the authoritative source. Falls back to JWT groups only when no employee row exists (super admin / platform accounts). All role-guarded endpoints are now immediately consistent with the DB after a role change. No call sites changed. These two sources can diverge during the JWT TTL window (≤1 hour) after a role change in Cognito. Demotion is the dangerous direction: a demoted admin's JWT still carries `admin` until expiry, so `RoleChecker`-guarded endpoints remain open. Emergency demotions must call `AdminUserGlobalSignOut` (already implemented as `_cognito_revoke_access` in `employees.py`) to force re-authentication. Role changes must always update both Cognito groups and `Employee.role` atomically.

**SEC-2:** Added `_: dict = Depends(allow_dispatch_mgmt)` to `get_unavailable_staff_for_date` in `backend/app/routers/dispatch.py`. The endpoint was returning employee contact info (name, Discord ID, phone number) to any authenticated caller regardless of role. `allow_dispatch_mgmt = RoleChecker([ROLE_DISPATCH, ROLE_ADMIN])` was already defined in the file — it was simply not wired to this endpoint. Also added `TruckAssignment.company_id == caller.company_id` to the double-dispatch guard query in `run_dispatch` — the check was not scoped to the caller's company.

**SEC-1:** Added `caller: Employee = Depends(get_caller_employee)` to `get_all_feedback` and `update_feedback_status` in `backend/app/routers/feedback.py`. Added `Feedback.company_id == caller.company_id` to the feedback list query, the employee name lookup query, and the status update record lookup. Before this fix, an admin at Company A could read and mutate feedback records owned by Company B — `RoleChecker` verified role but imposed no tenant boundary.

## Consequences

- Every future push is automatically tested. A failing test produces a red ✗ on the commit and an email notification.
- Invalid feedback type or status values now return HTTP 422 at deserialization — before the route handler, before the database write, before any business logic.
- The router's manual `if payload.status not in _VALID_STATUSES` check is now redundant (harmless but unnecessary).
- `GET /feedback/` and `PATCH /feedback/{id}/status` are now correctly scoped to the caller's company. An admin at Company A cannot read or mutate Company B's feedback records.
- `GET /dispatch/unavailable-staff/{date}` now requires dispatch or admin role. Trainees and walkers receive 403.
- The double-dispatch guard in `run_dispatch` is now scoped per company — Company A's dispatch run no longer conflicts with Company B's.
- ENV-4: JWKS cache is now shared across all worker processes via Redis. Intermittent 401s on AWS key rotation are eliminated.
- ENV-1 + ENV-5: Three-file Compose structure in place. Dev gets hot reload and bundled beat automatically. Production gets multi-worker uvicorn, no source mounts, and split celery containers.
- ENV-2: `INTERNAL_SECRET` guard now fires on any non-dev environment, not just the exact string `"production"`.
- ENV-3: App refuses to start if `cors_origins` contains `"localhost"` in a non-dev environment.
- SEC-9 dead code removed. Seven scripts with no auth, no audit trail, and direct DB access are gone from the repo surface.
- SEC-4 SSRF risk eliminated. `BOT_INTERNAL_URL` is now validated at startup — bad hostname or scheme causes `ValidationError` before any request is served.
- SEC-3 dual-source-of-truth eliminated. `RoleChecker` now checks `Employee.role` from the DB. A demoted admin is blocked immediately on all role-guarded endpoints — no JWT TTL window.
- 14 findings remain open in the rectification plan (ENV-1 through ENV-5, CI-2 through CI-5, SEC-4, SEC-9).

## Learnings & Growth

- `Literal["a, b, c"]` (one string) vs `Literal["a", "b", "c"]` (three arguments) is a subtle but critical distinction. The former creates a single valid value that includes the commas and spaces literally.
- When applying `Literal` to a field that appears across a class hierarchy, each class needs its own correct value set — a copy/paste of the parent's values may be semantically wrong even if syntactically valid (`FeedbackResponse.status` needed status lifecycle values, not feedback type values).
- Secrets in CI files are a supply-chain risk (OWASP 2025 A03). Fake placeholder values satisfy type validation without granting real access. Real secrets belong in GitHub's encrypted secrets store and are referenced as `${{ secrets.NAME }}`.
- SQLite in-memory tests run without a database service — this is the correct architecture for fast, isolated CI. The trade-off is that PostgreSQL-specific column types (JSONB) cannot be tested this way.

# Engineering Journal: 2026-05-10

**Session Start Time**: ~00:45 EST
**Session End Time**: ~01:30 EST

## Goal for the Session

Begin working through the security rectification plan produced from a full OWASP audit (2021 + 2025 editions) of the AsheFlow codebase. Priority order from the plan: CI-1 first (highest impact), then SEC-5 (smallest schema fix, good learning exercise).

Also: establish the understanding of what the existing test suite covers and how to build on it in future.

## Problems Encountered

**CI-1 — No `.github/` directory existed**
The project had zero CI automation. No directory, no workflow file. Any push to `master` was completely unverified.

**YAML syntax error on first draft of `ci.yml`**
`DATABASE_URL: sqlite:///:memory:` triggered a YAML parse error because the second `:` in the URL was interpreted as the start of a nested mapping key. Fix: quote the value — `DATABASE_URL: "sqlite:///:memory:"`.

**SEC-5 — Two mistakes in the schema fix attempt:**

*Mistake 1 — `Literal["bug, feature_request, general"]`*
One string containing all three values separated by commas, instead of three separate string arguments. `Literal` is variadic — commas go between quoted strings, not inside one of them.

*Mistake 2 — Copy/paste applied feedback type values to status fields*
`FeedbackResponse.status` and `FeedbackStatusUpdate.status` received `Literal["bug", "feature_request", "general"]` instead of `Literal["new", "in_progress", "resolved"]`. The valid status values were already defined in the router as `_VALID_STATUSES = {"new", "in_progress", "resolved"}`.

**Bonus finding — `feedback.py` contained stray test imports and a broken `def`**
`import pytest`, `from pydantic import ValidationError`, and an incomplete `def` at the end of the file had been left in from a previous session. Removed as part of the cleanup.

## Solutions & Procedures

**CI-1:**
1. Created `.github/workflows/ci.yml` with four steps: checkout, setup-python 3.12, pip install, pytest
2. Used `working-directory: backend` on both the install and test steps so Python resolves `app.*` imports correctly
3. Added fake env vars in the `env:` block to satisfy `Settings()` validation at import time without real credentials
4. Committed and pushed — workflow ran and passed (96 tests, 39 seconds) on first attempt

**SEC-5:**
1. Replaced `type: str` with `Literal["bug", "feature_request", "general"]` on `FeedbackBase`
2. Replaced `status: str` on `FeedbackResponse` and `FeedbackStatusUpdate` with `Literal["new", "in_progress", "resolved"]`
3. Removed stray pytest imports and broken `def`
4. Ran full test suite — 96 passed, no regressions

**SEC-6 — `TruckCreate.name` and `TruckUpdate.name` missing length constraints**
`TruckUpdate.name` was written as `Optional[str] = Field(..., min_length=1, max_length=100)`. The `...` (Ellipsis) default contradicts `Optional` — Pydantic treats the field as required, breaking PATCH semantics where every field should be omittable. Fix: `Field(None, min_length=1, max_length=100)` for the update schema, `Field(..., ...)` for the create schema.

**SEC-7 — `email: str` instead of `EmailStr` across employee schemas**
No issues encountered. All five relevant classes updated correctly: `EmployeeCreate`, `EmployeeUpdate`, `EmployeeResponse`, `BulkImportRow`, `BulkImportResult`. `Optional[EmailStr]` correctly used on the update and response schemas. `pydantic[email]` was already in `requirements.txt` — no new dependency needed.

**SEC-8 — CORS wildcard hardening (main.py, config.py)**
Four issues in the attempt: (1) `APP_ENV = "production"` was a class attribute not a Pydantic field — always returned `"production"` regardless of environment; (2) `cors_allow_methods: str = [...]` assigned a list to a str-typed field; (3) `get_cors_origins()` was incorrectly changed to return `["*"]` in dev — incompatible with `allow_credentials=True`; (4) `get_cors_methods()` was missing entirely. Fixed: `app_env: str = "development"` as a proper field, both helpers use comma-separated str defaults, origins helper left unchanged, unused `import os` removed.

**SEC-1 — Cross-tenant data exposure in feedback router**
`GET /feedback/` and `PATCH /feedback/{id}/status` used `RoleChecker(["admin"])` for access control but had no `company_id` filter. `RoleChecker` verifies role from the JWT but returns a `dict` — it has no `company_id`. An admin at Company A could query all feedback records regardless of which company they belonged to, and could mutate any record by ID.

## Solutions & Procedures (continued)

**SEC-1:**
1. Added `caller: Employee = Depends(get_caller_employee)` to both `get_all_feedback` and `update_feedback_status`
2. Added `.filter(Feedback.company_id == caller.company_id)` to the feedback list query
3. Added `Employee.company_id == caller.company_id` to the employee name lookup inside `get_all_feedback`
4. Added `Feedback.company_id == caller.company_id` to the record lookup in `update_feedback_status`
5. Ran full test suite — 96 passed, no regressions

Key distinction reinforced: `RoleChecker` ≠ tenant guard. Role and tenant scope are orthogonal concerns requiring separate dependencies.

**SEC-2 — Missing role guard on `GET /dispatch/unavailable-staff/{date}`**
Any authenticated employee could query colleague contact info (name, Discord ID, phone number) for any date. `allow_dispatch_mgmt` was defined at the top of the file but not wired to this endpoint. Fix: added `_: dict = Depends(allow_dispatch_mgmt)` to the signature.

Bonus fix found in the same file: the double-dispatch guard in `run_dispatch` queried `TruckAssignment` without `company_id`, meaning Company A's dispatch state could interfere with Company B's. Added `TruckAssignment.company_id == caller.company_id` to that filter.

96 tests pass after both fixes.

**CI-5 — Audit log coverage for employee lifecycle endpoints**
`grep write_audit routers/` revealed promote, demote, deactivate, and reactivate had no audit rows. Role changes are the highest-priority gap — SEC-3 made `Employee.role` authoritative, so every role change must be traceable. Added `write_audit()` with before/after snapshots to all four endpoints, placed before `db.commit()` so the audit row is transactionally atomic with the state change. 105 tests pass.

**CI-3 — Property-based fuzz testing with Hypothesis**
Added `tests/test_fuzz_schemas.py` with 9 property-based tests across FeedbackCreate, FeedbackStatusUpdate, TruckCreate, and EmployeeCreate. Hypothesis generates 200 random inputs per test including Unicode, empty strings, and very long strings — inputs a developer would never write manually. These tests verify the SEC-5 Literal allow-lists hold under adversarial input. Test count: 96 → 105. All pass.

**CI-2 — pip-audit CVE scanning added to CI**
Added `pip-audit -r requirements.txt` step to `ci.yml` between install and test. Bumped `aiohttp==3.9.3` → `3.13.5` — 3.9.x is end-of-life, the pinned version had a known CVE patched in 3.9.4, and aiohttp is used in the bot HTTP path. 96 tests pass.

**ENV-4 — JWKS cache moved from in-process dict to Redis**
`_jwks_cache` was a module-level dict in `security.py` — per-replica, never shared. With 4 uvicorn workers each worker fetched JWKS independently and held stale keys after AWS rotation until restart. Replaced with Redis key `jwks_cache` (1-hour TTL). All workers share one cache; a rotation miss force-fetches and writes back to Redis, fixing all workers simultaneously.

Chose sync `redis.Redis` over `redis.asyncio` — `verify_cognito_token` is sync; async would cascade through `get_current_user` and all of `deps.py`. Trade-off accepted at this traffic level (~1ms blocking). Scaling note left in code with explicit migration path. 96 tests pass.

**ENV-1 + ENV-5 — Multi-environment Docker Compose separation**
Created three-file Compose structure. Base file strips all dev-only settings (volume mounts, `--reload`, `--beat`). `docker-compose.override.yml` auto-loaded in dev adds them back. `docker-compose.prod.yml` sets `APP_ENV=production`, runs 4 uvicorn workers, and splits Celery into separate `celery_beat` and `celery_worker` containers (ENV-5). The split prevents double-firing of scheduled jobs when workers are scaled horizontally — beat runs in exactly one container.

Two bugs found and fixed during base file editing: (1) `celery_worker` block had wrong indentation — all properties were at the same level as the service name instead of nested inside it; (2) `volumes:` declaration missing at the bottom of the file — named volumes for postgres and redis weren't declared.

**ENV-2 + ENV-3 — Startup guards for non-dev environments**
ENV-2: `INTERNAL_SECRET` guard changed from `== "production"` to `!= "development"`. Staging with `APP_ENV=staging` previously bypassed the check silently.
ENV-3: Added `"localhost" in cors_origins and app_env != "development"` check. First attempt wrote `"local_host"` (underscore) — compiled and ran without error, but never matched. Silently broken. Fixed to `"localhost"`. Lesson: string-match guards need explicit tests asserting the `RuntimeError` is raised.
96 tests pass.

**SEC-9 — Dead code removal**
Deleted 7 one-shot dev scripts from `backend/`: `add_trainees.py`, `add_one_more_trainee.py`, `add_trainee_fields.py`, `alter_db.py`, `create_dispatch.py`, `create_fake_dispatch.py`, `seed.py`. Verified no imports or references in app or tests before deleting. All bypassed auth, roles, company_id scoping, and audit logging. Two ran raw DDL against the engine, bypassing Alembic. `seed.py` had hardcoded UUIDs. 96 tests pass.

**SEC-4 — SSRF via unvalidated BOT_INTERNAL_URL**
`_send_discord_invite` read `BOT_INTERNAL_URL` via `os.environ.get` with no validation. Any URL was accepted — including `http://169.254.169.254` (AWS IMDS), which returns temporary IAM credentials. User correctly identified all three problems with `os.environ` in application code: hidden contract, untestable, no type safety. Also identified hostname whitelisting as the gold standard over IP filtering (DNS rebinding bypasses IP checks).

Fix: moved to `Settings` with `@field_validator` enforcing scheme and hostname against `_ALLOWED_BOT_HOSTS`. Removed `import os` from `_send_discord_invite`. 96 tests pass.

**SEC-3 — Dual source of truth for roles (fixed)**
`RoleChecker` previously read `cognito_groups` from the JWT; `assert_owns_or_privileged` read `Employee.role` from the DB. After a demotion, `RoleChecker` would still accept the old JWT for up to one hour. User identified the asymmetry and pushed to fix it rather than accept it.

Decision: rather than refactoring 17 `assert_owns_or_privileged` call sites to use the JWT (which would make more of the system JWT-dependent — the weaker source), we made `RoleChecker` DB-authoritative in one place. It now looks up the employee by `cognito_sub` and checks `employee.role` directly. Falls back to JWT groups only for accounts with no Employee row (super admins). Zero call sites changed.

95 tests pass (one pre-existing analytics failure unrelated to this change, confirmed by stashing our work and reproducing it against the original code).

## Key Takeaways

- A CI pipeline is the highest-leverage security control: it makes every other fix verifiable and prevents regressions from landing silently. It should be the first thing in any project.
- `Literal` is the correct Pydantic tool for server-side allow-list enforcement on string fields with a finite valid set. It rejects invalid values at deserialization — the earliest possible point in the request lifecycle.
- When a router is doing `if value not in VALID_SET: raise HTTPException(422)`, that's a signal the validation should be moved up to the schema layer with `Literal`. The router check becomes redundant once the schema is correct.
- Tests for security fixes should assert on *rejection*, not *acceptance*. The dangerous case is the one that succeeds when it shouldn't — `pytest.raises(ValidationError)` is the pattern.
- Real secrets must never appear in committed files. GitHub's encrypted secrets store (`${{ secrets.NAME }}`) is the correct mechanism. Fake placeholder values are safe for CI env vars that only need to satisfy type validation.
- `RoleChecker` and `get_caller_employee` are orthogonal: role (can this person act?) and tenant scope (on whose data?) are two distinct access control axes. Every multi-tenant endpoint needs both. Missing `company_id` on a query is OWASP A01 — Broken Access Control, even when the caller is authenticated and has the correct role.
- Read endpoints are as dangerous as write endpoints when the data is sensitive (contact info, schedules, PII-adjacent data). Role guards on reads are not optional.
- A guard defined at the top of a file does nothing until it appears in a function signature. Naming something `allow_X` and then not using it is a silent no-op — no error, no warning, just an open endpoint.
- Always verify secondary queries in the same endpoint (e.g., employee name lookups, existence checks) are also scoped by `company_id`. The primary query getting the filter is not enough if there are others.
- When the same concept is stored in two places (JWT claims vs. DB column), they will diverge. Document the inconsistency window and the emergency sync procedure — don't pretend it doesn't exist.
- JWT TTL creates a role-demotion window. The correct fix is not to document the window but to eliminate it — move the authoritative role check to the DB, which reflects changes immediately.
- When choosing which source to make authoritative in a dual-source system, ask: which direction makes the system more consistent overall? Moving `assert_owns_or_privileged` to the JWT would have increased JWT dependency (17 call sites, weaker source). Moving `RoleChecker` to the DB eliminated the gap in one place with no call site changes.
- Pre-existing test failures must be confirmed before attributing them to a change. `git stash` + reproduce is the procedure.
- `os.environ.get` in application code is an antipattern: hidden contract, untestable, no type safety. Every environment variable belongs in `Settings` where Pydantic validates it at startup.
- SSRF hostname whitelisting is stronger than IP filtering — DNS rebinding can make a whitelisted hostname resolve to a blocked IP after the IP check passes. Reject unknown hostnames outright at startup, not at request time.
- `@field_validator` raising `ValueError` inside Pydantic `Settings` causes a `ValidationError` at import time — the app never boots with a bad value. This is the correct place for security-critical config validation.
- Audit rows must be placed before `db.commit()` — not after. If they're after, a failed commit produces a state change with no record. Transactional atomicity means either both land or neither does.
- `grep -rn "db.commit()" routers/ | grep -v "write_audit"` is the audit coverage check. Any sensitive mutating endpoint without write_audit before its commit is a gap.
- Property-based tests verify invariants, not examples. "Any invalid type raises ValidationError" is a stronger guarantee than "these three specific bad inputs raise ValidationError."
- Hypothesis finds edge cases developers don't think of: empty strings, null bytes, Unicode, strings that are almost-but-not-quite valid. Write properties, let the tool find the counterexamples.
- Dependency pins are a commitment to a version's security posture at the time of pinning. CVEs are discovered continuously — automated scanning closes the gap between "CVE published" and "you know about it" from months to hours.
- End-of-life library versions don't receive backport security patches. Staying on a supported minor version is a prerequisite for being able to apply fixes when they're released.
- In-process caches (module-level dicts, `lru_cache`) break with multiple workers — they never share state across processes. Any cache that must be consistent across replicas belongs in Redis or a database.
- Sync vs async Redis is a refactoring cost decision, not just a performance decision. When a sync function is deep in the call chain, making it async cascades upward through every caller. Accept sync at low scale; plan the migration path before you need it.
- Docker Compose override files only need to specify the keys that change — everything else is inherited from the base. This avoids duplicating 100-line service definitions across environments.
- Volume mounts in production are a security risk: they bypass the image build and let disk content override what was deployed. Remove them from the base file and only add them in the dev override.
- `celery worker --beat` in one process is fine for dev; in production with multiple workers it causes every worker to fire the same scheduled jobs simultaneously. Beat must run in exactly one container.
- YAML indentation errors can be structurally silent — a property at the wrong level may be ignored rather than raising a parse error. Always validate with `docker-compose config`.
- Security guards should allowlist the safe case (`!= "development"`) not blocklist the dangerous one (`== "production"`). Unrecognised environment names are automatically blocked.
- String-match guards that are silently broken (wrong substring) have no runtime signal. Always write a test that asserts the `RuntimeError` is raised with a non-dev config.
- Dead scripts in the repo root are a security surface even if "nobody runs them" — they have no auth, no audit trail, and bypass all application-layer controls. Delete after use or move to `scripts/` with a README.
- Before deleting any file, verify it's unreferenced: `grep -r filename app/ tests/`. Confirm zero results before proceeding.

# Engineering Journal: 2026-05-16

## Goals for the Session

1. Fix the test suite — it had been failing intermittently and lacked coverage for key services
2. Formalize the CI/CD pipeline with proper deploy gates
3. Establish the dev→staging→prod promotion model

---

## Test Suite Overhaul

### conftest.py fixes
Three helpers were broken due to missing `company_id`:
- `make_off_day` — was missing `company_id=employee.company_id`; caused `IntegrityError` on every call
- `make_time_off_request` — same issue; also didn't exist yet, was added fresh

Added four new row-builder helpers: `make_time_off_request`, `make_curriculum`, `make_training_record`, `make_shift_session`. Also added `ShiftSession` to `DISPATCH_TABLES`.

### test_available_pool.py
25 tests written from scratch covering `get_available_pool` and `get_unavailable_staff`. All passing.

Key behaviors tested: role filtering, inactive exclusion, recurring off-day exclusion, PTO exclusion, multi-tenant isolation, `company_id=None` guard, unavailable staff reason field, roles filter, trainees excluded from unavailable list.

### test_training_injection.py
28 tests written from scratch. Writing them immediately exposed a production bug.

**Bug found:** `inject_curriculum` never sets `company_id` on any `TrainingRecord` or `TrainingTask` it creates. This is a NOT NULL column on PostgreSQL. In production this would have caused a `500` on every dispatch with trainees — caught before any trainee was ever dispatched on the live system.

**Fix:**
- Added `company_id: Optional[UUID] = None` to the function signature
- Passed `company_id=company_id` to all four model constructors inside the function
- Updated the `dispatch.py` router call to pass `company_id=caller.company_id`

All 28 tests now pass. Total suite: 154 tests, all green.

---

## CI Pipeline

### CVEs cleared
`pip-audit` was failing CI with 8 vulnerabilities across three packages:
- `pyjwt 2.8.0 → 2.12.1`
- `cryptography 42.0.5 → 46.0.7` (46.0.6 had an additional CVE published same day)
- `requests 2.31.0 → 2.33.0`

Zero CVEs after bumps.

### Workflow restructure
Three-job pipeline: `audit → test → deploy-prod`. Each job blocks the next.

`deploy-prod` SSHs into the EC2, pulls master, and runs `docker compose build backend && docker compose up -d backend`. Only triggers on `push` to `master` (not PRs, not other branches).

`FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: true` at job level clears the Node.js 20 deprecation warnings that were appearing as annotations on every run.

### GitHub Environment
Created `prod` environment with `PROD_EC2_HOST` and `PROD_EC2_SSH_KEY` secrets. Deployment branch rule locked to `master`.

### Pipeline model clarified
- **Dev** = localhost. No CI deploy. Run `uvicorn app.main:app --reload` locally.
- **Prod** = EC2 at `3.141.169.13`. Auto-deploys on green master.
- **Staging** = not yet provisioned. Workflow has commented stubs ready. Planned for 2026-05-19.

Promotion flow once staging exists:
```
feature/* → PR → master → PR → staging branch → PR → prod branch
```

---

## Pipeline Promotion Protocol (researched against GitHub, Martin Fowler, Google SRE)

Correct workflow once staging is provisioned:

```
feature branch → PR to master → CI (audit+test) → merge
                                                     ↓
                                          auto-deploy to staging
                                                     ↓
                                    manual smoke test on staging
                                    (real DB, real Docker, real env vars,
                                     Discord bot, Celery, migrations)
                                                     ↓
                                    PR master → prod branch → CI reruns
                                                     ↓
                                          auto-deploy to prod
```

Key clarifications vs. intuition:
- **Tests run at every promotion**, not just once. Build once, test at each stage.
- **Staging→prod is never automatic.** Manual PR review is the gate (approval rules not available on free GitHub plan, so discipline substitutes).
- **Staging validates what unit tests can't:** real PostgreSQL migrations, Docker networking, Celery task firing, Discord bot connectivity, performance under realistic load. SQLite in-memory tests don't cover any of this.
- **Until staging is live:** treat every PR to master as a prod deploy. Be deliberate — master goes straight to the EC2.

Day-to-day workflow once staging is ready:
```bash
git checkout -b feature/my-thing   # 1. new branch per feature
# build, test locally, push — CI runs on branch push
# open PR to master, merge when green → auto-deploys to staging
# smoke test staging manually
# open PR master → prod, merge when satisfied → auto-deploys to prod
```

## Mixed Content Bug — Anchor Points (Dispatch Role)

**Symptom:** `Mixed Content` browser error on `/anchor-points` for dispatch role only. Requests to `/employees/` and `/trucks/` were going out as `http://api.asheflow.com` instead of `https://`.

**Root cause:** The S3 bundle was built before `.env.production` had `https://api.asheflow.com`. The anchor points dispatch view was rewritten on May 3rd; `.env.production` was corrected to `https` on May 13th; but the frontend was never rebuilt and redeployed after that fix. The stale bundle had `http://` baked in.

It only showed on the dispatch role because the driver view of the same page hits different endpoints — the dispatch view specifically calls `/trucks` and `/employees` which triggered the browser's mixed content block.

**Fix:** Rebuild with `npm run build` (Vite picks up `.env.production` automatically) and redeploy to S3 + CloudFront invalidation for `index.html`.

**Verified:** New bundle contains `https://api.asheflow.com`, zero occurrences of `http://api.asheflow.com`.

**Lesson:** The frontend deploy must be part of CI — a manual S3 deploy can go stale silently. Any env var change or dependency bump requires a full rebuild and redeploy, not just a backend restart. Add frontend build + S3 sync to the CI pipeline when staging is set up.

## What's Next

- Provision staging EC2 (planned Tuesday 2026-05-19)
- Create `staging` and `prod` branches, update branch protection rules
- Uncomment `deploy-staging` in ci.yml, add staging secrets
- Add frontend build + S3 deploy step to CI pipeline
- Phase 2 avatar (image upload to S3)

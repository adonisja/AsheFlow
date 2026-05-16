# ADR-089: CI Pipeline Formalization and Dependency Security

**Date:** 2026-05-16
**Status:** Accepted

## Context

The project had a basic `ci.yml` that ran tests on every push but had several problems:

1. **CVE failures**: Three pinned packages had known vulnerabilities causing `pip-audit` to exit non-zero and fail CI: `pyjwt==2.8.0` (1 CVE), `cryptography==42.0.5` (4 CVEs), `requests==2.31.0` (3 CVEs).
2. **Node.js 20 deprecation warnings**: `actions/checkout@v4` and `actions/setup-python@v5` were running on Node.js 20, which GitHub is deprecating in June 2026.
3. **No deploy pipeline**: There was no automated deployment — code had to be manually SSHed onto the EC2 after every push.
4. **No pipeline gates**: Changes went directly from a developer's machine to production with no formal promotion flow.

## Decision

### Dependency bumps
| Package | Old | New | CVEs cleared |
|---|---|---|---|
| `pyjwt` | 2.8.0 | 2.12.1 | 1 |
| `cryptography` | 42.0.5 | 46.0.7 | 4 |
| `requests` | 2.31.0 | 2.33.0 | 3 |

### CI workflow restructure
The workflow now has three jobs with explicit ordering:

1. **audit** — runs `pip-audit` first. If a CVE is present, the pipeline stops before wasting runner minutes on tests.
2. **test** — runs only after audit passes. Uses `cache: "pip"` keyed on `requirements.txt` to avoid re-downloading deps on every run.
3. **deploy-prod** — runs only after test passes, only on `master` branch pushes, only on `push` events (not PRs). SSHs into the EC2, pulls master, rebuilds and restarts the backend container via `docker compose`.

`FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: true` is set at the job level to opt into Node.js 24 for all action steps, clearing the deprecation warning.

### Environment setup
A `prod` GitHub Environment was created with two secrets:
- `PROD_EC2_HOST` — the EC2 public IP
- `PROD_EC2_SSH_KEY` — the EC2 private key (PEM contents)

Deployment branch rule is set to `master` only.

### Pipeline promotion model
Current state (one server):
```
feature/* → master (CI: audit→test→deploy-prod)
```

Target state (when staging EC2 is provisioned):
```
feature/* → master → staging branch → prod branch
```

`deploy-staging` and `deploy-prod` jobs are stubbed and commented out in the workflow, ready to be uncommented when a staging server is available.

## Consequences

- CI now passes with zero CVEs and zero Node.js deprecation warnings
- Every push to master automatically deploys to the EC2 after tests pass
- PRs get audit + test feedback before merge
- The staging/prod promotion path is documented and partially wired — completing it requires provisioning a second EC2 and creating `staging`/`prod` branches

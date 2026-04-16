# ADR-033: Security Audit — Section 5 Remaining Gaps

**Date:** 2026-04-15  
**Status:** Accepted  
**Deciders:** adonisja

---

## Context

A final sweep after sections 1–4 identified three remaining issues: missing ownership checks on the employee off-days router, CORS origins hardcoded in source code, and silent load failures in the Assets page.

---

## Decisions

---

### 5.1 & 5.2 — Employee Off-Days: Ownership Checks

**Decision:** Replace `allow_any_auth` with `get_caller_employee` on both `POST /employee-off-days/` and `GET /employee-off-days/{employee_id}`. Add an ownership check that permits management/admin to act on any record and restricts field staff to their own.

**Why not just keep `allow_any_auth` and document it?** `allow_any_auth` only authenticates — it does not authorize. The endpoint accepted an arbitrary `employee_id` in the payload, so any caller could forge that field. Documentation of a known exploit is not a fix.

**Why is dispatch included in the read allowlist but not the write allowlist?**
- Read: dispatch needs visibility of all employee off-day schedules to run dispatch correctly. Including them in the read-allowed set is consistent with their role.
- Write: dispatch has no operational reason to create recurring off-days on behalf of field staff. Excluding them follows least-privilege.

**Why not add a schema-level validator that asserts `employee_id == caller.id`?** The schema runs before the request handler — it has no access to the authenticated caller. Ownership checks belong in the handler, where the caller identity is available via `Depends(get_caller_employee)`.

---

### 5.3 — CORS Origins: Config vs. Hardcoded

**Decision:** Move CORS origins to a `cors_origins` setting in `config.py` as a comma-separated string with the existing localhost values as the default.

**Why a comma-separated string rather than a `List[str]`?** Pydantic-settings reads environment variables as strings. A `List[str]` field requires JSON-encoded values in the env (`'["https://...","https://..."]'`), which is error-prone to write manually. A comma-separated string with a `get_cors_origins()` split helper is simpler and matches conventional env config patterns (e.g. `DATABASE_URL`, `ALLOWED_HOSTS` in Django).

**Why keep the localhost defaults in config rather than requiring the env var?** Unlike `DATABASE_URL` (which has a clear wrong-state failure if missing), a missing `CORS_ORIGINS` in dev just means the dev server can't connect — a confusing startup failure rather than a loud error. Keeping the localhost default preserves the existing developer experience while ensuring production deployments can override it cleanly.

**Consequence for production:** A production deployment must set `CORS_ORIGINS=https://app.asheflow.com` (or equivalent) in the environment. If omitted, the dev localhost origins are used — which will cause every browser request from the real domain to be rejected by CORS. This is a visible, immediate failure rather than a silent security misconfiguration.

---

### 5.4 — Assets Load Errors: Visible vs. Silent

**Decision:** Add a `loadError` state to `PeopleTab` and `FleetTab` in `Assets.tsx`. Render as a red-bordered card when set.

**Why not use a toast/notification system?** The app has no global toast infrastructure. Adding one for two error states would be over-engineering. An inline error card is consistent with how errors are displayed elsewhere in the codebase (e.g. `DispatchDashboard`'s `error` banner).

**Why not throw and use an error boundary?** An error boundary would unmount the entire tab and replace it with a fallback. That's too aggressive for a load failure — the toolbar, filters, and add-button are still functional even when the list is empty. An inline error message keeps the page interactive.

---

## Consequences

**Positive:**
- Any authenticated user can no longer forge `employee_id` on off-day creation to pollute another employee's schedule.
- CORS configuration is now environment-driven — a production deployment can restrict origins without a code change.
- Assets page load failures are visible to admins rather than silently degrading to an empty list.

**Negative / Trade-offs:**
- The `cors_origins` default in `config.py` still contains localhost values. If an operator copies the config defaults to production without setting `CORS_ORIGINS`, the app will reject all browser requests from the real domain — failing loudly and immediately. This is preferable to silently accepting the wrong origins.
- `get_caller_employee` is now used on the off-days read endpoint, adding one DB lookup per request. This is consistent with every other ownership-checked endpoint in the codebase and is not a performance concern at operating scale.

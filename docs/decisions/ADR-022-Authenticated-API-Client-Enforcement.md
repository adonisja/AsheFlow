# ADR-022: Always Use `axiosClient` for API Calls — Never Raw `axios`

**Date:** 2026-04-14
**Status:** Accepted

---

## Context

`AdminDashboard.tsx` was using raw `axios` with a hardcoded base URL for all API calls. Every other page in the application uses `axiosClient` from `src/api/axiosClient.ts`, which attaches the Cognito `idToken` as an `Authorization: Bearer` header via a request interceptor.

Raw `axios` has no interceptor. All requests went out unauthenticated. The backend `RoleChecker` dependency returned 401 on every route. `Promise.allSettled` silently absorbed all failures. The dashboard rendered with every data section empty — no error, no warning, just blank state.

---

## Decision

`axiosClient` is the **only** permitted way to make API calls in this frontend. Raw `axios` must never be imported or used for backend requests.

This is enforced by convention, not tooling (no ESLint rule exists yet). Any new page or component must import from `../api/axiosClient` (path adjusted for depth).

`axiosClient` provides:
1. Correct `baseURL` (`http://localhost:8000/api/v1`) — no hardcoding needed per file.
2. Auth token injection on every request via request interceptor.
3. Centralised 401 handling in the response interceptor (extensible without touching every caller).

---

## Consequences

**Positive:**
- Auth token is attached to every request automatically — no per-file token retrieval.
- Base URL is defined once; changing it (e.g. for staging) requires one edit.
- 401 handling can be upgraded globally (e.g. trigger sign-out) without touching individual pages.

**Risk mitigated:**
- `Promise.allSettled` is the correct pattern for fan-out fetches. But it means auth failures are invisible — no rejection propagates. This makes unauthenticated requests especially dangerous: the component renders as if the server returned empty data, not as if requests failed. Using `axiosClient` eliminates the auth failure vector entirely.

---

## Corollary: `include_inactive` on `GET /employees/`

Admin's dashboard needs all employees (active + inactive) for the roster and workforce breakdown. The endpoint previously hard-filtered `is_active == True` with no override.

Added `include_inactive: bool = False` query param to `GET /employees/`, matching the same pattern already on `GET /trucks/`. Only management/admin may pass `include_inactive=true`; all other callers are unaffected.

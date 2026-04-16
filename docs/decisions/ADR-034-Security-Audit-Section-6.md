# ADR-034: Security Audit — Section 6 Ownership Gaps

**Date:** 2026-04-16  
**Status:** Accepted  
**Deciders:** adonisja

---

## Context

Section 6 found seven ownership gaps across three routers and one frontend page. All involved the same root pattern: an endpoint accepted a resource identifier from the request (body, path, or query param) without verifying it matched the authenticated caller.

---

## Decisions

---

### 6.1–6.3 — Continuation Requests: All Trainer/Trainee Endpoints Need Ownership

**Decision:** Add `get_caller_employee` to POST (trainee check), GET (trainer check), accept (trainer check), and reject (trainer check). Admins bypass all ownership checks via `"admin" not in cognito_groups`.

**Why does POST need a trainee check when there's already a most-recent-trainer guard?**
The trainer guard prevents a trainee from requesting continuation with an arbitrary trainer they haven't worked with. It does not prevent a trainee from submitting on behalf of another trainee's UUID. Both guards are needed: the trainer guard validates the *target*, the ownership check validates the *subject*.

**Why were accept/reject missed in Section 1 (fix 1.5)?**
Section 1 fixed the `priority` endpoint, which had the most obvious ownership bug (it had the wrong group key making the check always fail). Accept and reject had no ownership check at all — they were incorrectly assumed to be safe because the caller needed the request's UUID. UUID-based access control is not access control: UUIDs are guessable given a trainer's ID.

**Why does GET need an ownership check if the data is low-sensitivity?**
Pending continuation requests reveal that a trainee wants to stay with a specific trainer — this is personal operational preference data. More importantly, consistency: every endpoint in this router now follows the same rule. Inconsistent ownership policy is a maintenance hazard.

---

### 6.4–6.6 — Employee Relationships: POST, GET, DELETE All Need Ownership

**Decision:** Add `get_caller_employee` and ownership checks to all three endpoints.

**Why does POST matter — can't a malicious user just inspect the DB limits anyway?**
No. An attacker who submits a POST with another employee's `employee_id` can consume that employee's fav/ban quota. If Employee A is out of bans, a malicious actor could exhaust Employee B's quota so B can no longer protect themselves from being paired with someone harmful. The fav/ban system has operational safety implications (e.g., banning someone who has been harassing you on a truck).

**Why is dispatch included in the GET allowlist but not POST/DELETE?**
Dispatch needs to see all employee relationships to make informed dispatch decisions (they need to know who is banned from whom). They have no operational reason to create or delete relationships.

**Why are the `clear` and management-scoped DELETE endpoints unchanged?**
`DELETE /employee-relationships/employee/{id}/clear` already uses `allow_mgmt` — management-only, no ownership issue. The per-record DELETE was the gap.

**Why not use `allow_any_auth` as a fallback and add ownership in the handler?**
`allow_any_auth` signals "any role is welcome here" — it's misleading when the real policy is "only the owning employee, or management." Using `get_caller_employee` as the single dependency is both cleaner and consistent with how every other ownership-checked endpoint in the codebase works. `allow_any_auth` has been removed from the POST and DELETE signatures entirely.

---

### 6.7 — Schedule.tsx: `/employees/me` and Error Visibility

**Decision:** Replace the fragile `user.userId || user.username` seed and `Array.find()` lookup with `GET /employees/me`. Surface load errors as an inline card.

**Why `Promise.all` for the two fetches rather than sequential awaits?**
The employee list (for the management-facing picker) and the self-ID lookup are independent. `Promise.all` lets both resolve in parallel. A failure in either sets `loadError` and both results are discarded — consistent state rather than partial state.

**Why keep `GET /employees/` alongside `GET /employees/me`?**
The Schedule page serves both field staff (personal calendar view) and privileged roles (management view). The full employee list is needed for the management scheduler's employee picker. `GET /employees/me` provides only the caller's own ID. Both are required.

---

## Consequences

**Positive:**
- An employee can no longer consume another employee's fav/ban quota.
- A trainer can no longer accept, reject, or read continuation requests addressed to another trainer.
- A trainee can no longer submit continuation requests on behalf of another trainee.
- Schedule page now works correctly for all account types and surfaces failures visibly.

**Negative / Trade-offs:**
- The continuation request endpoints now require two DB lookups per request: `get_caller_employee` + the request record fetch. At operating scale this is negligible.
- The typo fix on `get_employee_realtionships` → `get_employee_relationships` is a technically breaking change to the function name. Since this is an internal router function (not part of the public API path), no external callers are affected.

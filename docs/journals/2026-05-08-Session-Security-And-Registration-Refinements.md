# 2026-05-08 — Session Security, Registration Refinements & UX Polish

## What prompted this

After completing the registration rewrite (ADR-074), end-to-end testing revealed three issues:

1. A deleted account could still navigate the app — the JWT was still valid
2. Activation wasn't firing on first login because registration now stamps `cognito_sub` before first login
3. The Discord bot couldn't DM new employees not yet on the server

And a round of UX review on the registration page and invite modal surfaced several rough edges.

## Session security (ADR-075)

Rejected the DB-check-per-request approach as an anti-pattern (kills stateless auth performance, incompatible with future offline features). Implemented the industry-standard solution instead:

- Access token TTL: 15 min (was Cognito default ~1 hour)
- Refresh token TTL: 30 days
- `AdminUserGlobalSignOut` + `AdminDisableUser` called on deactivate and delete
- `admin_enable_user` called on reactivate
- `EnableTokenRevocation: true` required on the Cognito app client for refresh token revocation to actually work

Users experience no change — Amplify's silent refresh handles the short TTL invisibly.

## Registration refinements (ADR-076)

**Single email:** Switched from Cognito's system email + our welcome email to a single fully-branded credentials email. `MessageAction="SUPPRESS"` suppresses Cognito's email; we generate our own temp password server-side and send it via `send_credentials_email()`.

**Activation fix:** `get_caller_employee` was only activating when `cognito_sub` was null. Since registration stamps it, activation never fired. Decoupled the two checks — `cognito_sub` stamping and `pending_verification → active` are now independent.

**Discord invite:** Bot can't DM non-server-members. Changed bot to return invite URL synchronously; backend emails it via SES on first login via a background thread.

**Admin delete endpoint:** `DELETE /employees/{id}` — revokes Cognito session, deletes Cognito user, writes audit log with full before-snapshot, then deletes DB record.

**Employee lifecycle states:** Five states derived from existing columns (`account_status` + `invited_at` + `username`): Not Invited → Invited → Registered → Active → Deactivated. No schema changes needed beyond adding `invited_at` and `username` to `EmployeeResponse`.

## UX polish (ADR-077)

**Register.tsx:**
- Bordered input containers (rounded-xl, bg-input, focus-within ring) on all fields
- Discord ID `?` tooltip with Developer Mode instructions and link to Discord guide
- Two-step flow: form → review summary → confirm submit
- Done screen: removed username + sign-in button; directs employee to check email
- Header split into "Welcome, {name}." heading + subtitle
- Footer: "dispatcher" → "admin"

**Invite modal:**
- Same bordered container on all fields
- Two-step flow for create: form → summary card → Send Invite
- Header subtitle updates between steps
- Labels changed to `text-sm font-medium` for readability
- Status filter default changed to "All Statuses"

## Lessons

- Never check `cognito_sub IS NULL` as a proxy for "first login" after a flow that stamps it pre-login
- Discord's DM API blocks non-shared-server users — email is the only reliable channel for invite links
- Short JWT TTL + server-side revocation is the correct stateless auth security model; DB checks per request are not

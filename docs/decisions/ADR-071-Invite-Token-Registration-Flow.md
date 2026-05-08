# ADR-071: Invite Token Registration Flow

**Date:** 2026-05-08
**Status:** Implemented

## Context

Phase 2 of the multi-tenant roadmap requires a self-service registration flow for
employees. Previously, `POST /employees/` called Cognito `AdminCreateUser`, which
sent a system-generated temporary-password email. The employee then had to sign in
and immediately change their password through the Cognito hosted UI — a confusing
UX with no control over the username format.

The new pool (ADR-066) uses `username` as the sign-in identifier, so the employee
must choose their own username at registration time. The old temp-password flow
cannot support this: Cognito `AdminCreateUser` sets the username at creation, and
there is no way for the employee to change it.

## Decision

Replace the Cognito-invite flow with a branded invite-token flow:

1. Manager creates an employee record (`POST /employees/`) — no Cognito user is
   created at this point.
2. Backend mints a `secrets.token_urlsafe(48)` token, stores it in the new
   `invite_tokens` table, and sends a branded SES email with a link to
   `{APP_BASE_URL}/register?token=...`.
3. Employee clicks the link → `GET /registration/validate?token=` validates the
   token and returns their name, email, and role (no sensitive data).
4. Employee fills in their chosen username and password on the `/register` page.
5. `POST /registration/complete` validates the token, calls
   `AdminCreateUser` + `AdminSetUserPassword` with `Permanent=True` (no
   force-change on first login), adds them to their role group, activates the
   Employee record, and marks the token used.

### Why token_urlsafe(48)?

48 bytes → 64 base64url characters. At 256-bit entropy this is effectively
unguessable even with unlimited online attempts, and fits in a URL without
encoding issues.

### Why not JWT for the invite token?

JWTs would require a shared secret or asymmetric key and complicate revocation.
A random opaque token stored in the DB is simpler: a single `SELECT` validates
and revokes it atomically.

### Why `AdminSetUserPassword` with `Permanent=True`?

`AdminCreateUser` with a temporary password forces the employee to complete a
"NEW_PASSWORD_REQUIRED" challenge on their first sign-in. This requires the
Cognito hosted UI or a custom challenge handler. Bypassing it with
`AdminSetUserPassword(Permanent=True)` lets the employee sign in immediately
with the password they just set, matching the expectation set by the
registration form.

## Resend flow

`POST /registration/invite` (management/admin only) re-issues a token for any
`pending_verification` employee and re-sends the email. The previous token is
hard-deleted before the new one is created, so only one valid token ever exists
per employee.

## Bulk import

`POST /employees/bulk` follows the same pattern: Employee row created,
`InviteToken` minted, SES email sent per row. Email failures are logged but do
not fail the row — the manager can resend via the Assets UI.

## Token expiry

Tokens expire after `INVITE_EXPIRY_DAYS` (default 7) days, matching the existing
`invited_at`-based Celery cleanup job. The validate and complete endpoints return
`410 Gone` for expired tokens.

## Files changed

| File | Change |
|---|---|
| `backend/app/models/invite_token.py` | New — InviteToken ORM model |
| `backend/app/models/__init__.py` | Added InviteToken import |
| `backend/alembic/versions/4dce9ab938ce_add_invite_tokens_table.py` | New migration |
| `backend/app/services/email.py` | New — SES invite email helper |
| `backend/app/core/config.py` | Added `ses_from_email`, `app_base_url` settings |
| `backend/app/routers/registration.py` | New — `/registration/invite`, `/validate`, `/complete` |
| `backend/app/routers/employees.py` | Replaced Cognito AdminCreateUser with token+SES flow |
| `backend/app/main.py` | Registered `registration` router |
| `frontend/src/pages/Register.tsx` | New — public `/register?token=` page |
| `frontend/src/App.tsx` | Added public `/register` route |

## Consequences

- All existing `pending_verification` employees created under the old flow have
  no `invite_tokens` row. They must be re-invited via `POST /registration/invite`.
- Test accounts (`driver.test`, `walker.test`, etc.) already have Cognito users
  with permanent passwords — they are unaffected.
- SES must be out of sandbox before production invite emails reach unverified
  addresses (pending AWS approval per ADR-067).

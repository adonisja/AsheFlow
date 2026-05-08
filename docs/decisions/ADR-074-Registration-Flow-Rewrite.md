# ADR-074 — Registration Flow Rewrite (Work Item A)

**Date:** 2026-05-08  
**Status:** Superseded in part by ADR-076

## Context

The original `POST /registration/complete` let the employee choose their own username and password. The agreed flow moves username derivation to the server and delegates password setup to Cognito's forced-reset challenge, so the employee only needs to confirm their identity and supply missing info.

## Decision

### Flow (final)

1. Manager creates employee stub (name, email, phone, role) → invite token minted → SES invite email sent
2. Employee clicks link → `GET /registration/validate` returns name/email/role/phone_last4 (last 4 digits of phone on file)
3. Employee fills in Discord ID and full phone number; submit hits `POST /registration/complete`
4. Backend derives username as `firstname.lastname` (numeric suffix if taken)
5. `AdminCreateUser` called with no `TemporaryPassword` — Cognito auto-generates a temp password and emails it to the employee's address directly
6. Employee record stamped: `username`, `cognito_sub`, `discord_id`, `phone_number`; account_status stays `pending_verification` until first login
7. Backend sends branded welcome email with the derived username
8. Employee signs in → Cognito FORCE_CHANGE_PASSWORD challenge → they set their own permanent password
9. `get_caller_employee` (first login) flips `account_status → active`, fires Discord server invite

### Backend changes

- `ValidateResponse` — added `phone_last4: str | None`
- `CompleteRequest` — removed `username` and `password`; added `discord_id` and `phone_number`
- `_derive_username(name, db)` — strips non-alphanumeric chars from first/last name, loops with numeric suffix until unique
- `complete_registration` — Discord ID uniqueness check, derive username, `AdminCreateUser` (no TemporaryPassword), role group add, stamp Employee, send welcome email
- `send_welcome_email()` added to `email.py` — includes username and login link
- `POST /employees/` — added management role guard: callers with `role == "management"` may only create `driver` or `trainee` accounts (403 otherwise)

### Frontend changes (`Register.tsx`)

- Removed username and password fields entirely
- Added Discord ID field (required)
- Added phone number field (required); if `phone_last4` is set, shows hint and validates that the entered number ends with those 4 digits
- Locked info block shows name/email/role with lock icon
- Done screen shows derived username and instructs employee to check email for credentials

## Superseded decisions

The following parts of this ADR were changed before shipping — see ADR-076 for the authoritative description:

- Steps 5 & 7 changed: `AdminCreateUser` is called with `MessageAction="SUPPRESS"` and a server-generated temp password. A single branded `send_credentials_email()` replaces both Cognito's system email and a separate welcome email.
- `discord_id` is no longer collected at employee creation — only at registration. Column is nullable with a partial unique index.
- The Done screen no longer shows the username or a sign-in button — it directs the employee to check their email.

## Consequences

- Employees never choose usernames — naming is consistent (`firstname.lastname`) and controlled
- Password security is delegated to Cognito's built-in forced-reset flow — no risk of weak passwords slipping through a custom validator
- The registration form is minimal and clear: two fields the employee actually need to provide
- Phone re-verification gives a lightweight identity check without requiring SMS OTP infrastructure
- Welcome email + Cognito credential email means the employee gets two emails; this is intentional — one from our domain explaining context, one from Cognito with the actual credentials

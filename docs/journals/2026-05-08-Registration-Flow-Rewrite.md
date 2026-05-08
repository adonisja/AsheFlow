# 2026-05-08 — Registration Flow Rewrite (Work Item A)

## What changed

The registration page previously had username and password fields. The agreed flow removes both:
- Username is now derived server-side as `firstname.lastname` (suffix if taken)
- Password setup is delegated to Cognito's FORCE_CHANGE_PASSWORD challenge on first login
- The form collects Discord ID (new required field) and phone number (with last-4 verification hint if phone was on file)

## Backend

- `_derive_username(name, db)` helper in `registration.py` — strips non-alpha chars, loops until unique
- `AdminCreateUser` called without `TemporaryPassword` — Cognito generates and emails credentials automatically
- `account_status` stays `pending_verification` after registration completes; only flips to `active` on first login via `get_caller_employee`
- `send_welcome_email()` added to `email.py` — employee receives two emails: Cognito's credential email and our branded welcome
- `POST /employees/` now guards management callers to driver/trainee only at the API layer (was previously UI-only)

## Frontend

`Register.tsx` rewritten:
- Locked info block (name/email/role) with lock icons — employee can't change these
- Two editable fields: Discord ID and phone number
- If `phone_last4` is in the token info, the phone field shows a hint and validates the last 4 match
- Done screen shows the derived username prominently (so employee knows what to log in as before the email arrives)

## Key decisions

- Phone re-verification is client-side only (last 4 match check). It's an identity hint, not cryptographic proof — full SMS OTP would be overkill for this use case.
- The `field_validator` on `CompleteRequest` accepts any phone format and strips to digits for length check. We store the human-entered format in the DB.
- Cognito's credential email goes to the same `email` we set in `UserAttributes`, so it matches our record — no risk of mismatch.

# ADR-072: Assets UI — Resend Invite Button

**Date:** 2026-05-08
**Status:** Implemented

## Context

ADR-071 introduced the invite-token registration flow. Managers need a way to
re-trigger the invite email from the UI when:
- The original email was never received (spam folder, wrong address)
- The 7-day token expired before the employee registered

## Decision

Add a **Resend** button to the People tab in Assets for any employee whose
`account_status === 'pending_verification'` and who has an email address on file.

### Behaviour
- Calls `POST /api/v1/registration/invite` with `{ employee_id }`.
- The backend invalidates the previous token and issues a fresh one with a new
  7-day expiry, then sends a new SES invite email.
- Inline feedback shown in the Actions column: green on success, red on failure.
- Button shows a spinner while the request is in-flight; disabled during that time.

### Status column
The Status column now has three states:
| State | Display |
|---|---|
| `pending_verification` | ⚠ Pending (warning colour) |
| `is_active = true` | ✓ Active (success colour) |
| `is_active = false` | ✗ Inactive (muted) |

## Files changed

- `frontend/src/pages/Assets.tsx` — `account_status` added to Employee type;
  `resendingId` / `resendMsg` state; `handleResendInvite` handler; Resend button
  and Pending badge in the People table

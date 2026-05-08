# 2026-05-08 — Assets UI: Resend Invite Button

## What changed

Added manager-facing resend invite capability to the People tab in Assets.

### Modified files
- `frontend/src/pages/Assets.tsx`
  - `account_status` field added to `Employee` type
  - `resendingId` + `resendMsg` state added to `PeopleTab`
  - `handleResendInvite` calls `POST /registration/invite`
  - Status column now shows "Pending" badge for `pending_verification` employees
  - Actions column shows Resend button (Mail icon) for pending employees with email
  - Inline success/error feedback displayed next to the button
- `docs/decisions/ADR-072-Assets-Resend-Invite-Button.md`

## Notes

TypeScript hints fired for each state variable and the handler between edits
because they were added before the JSX that consumes them — all resolved by the
final edit. No actual type errors at any point.

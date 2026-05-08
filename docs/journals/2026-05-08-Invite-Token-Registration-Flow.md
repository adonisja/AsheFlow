# 2026-05-08 — Invite Token Registration Flow

## What changed

Replaced the Cognito `AdminCreateUser` temp-password invite flow with a
branded invite-token flow (Phase 2, Step 1).

### New files
- `backend/app/models/invite_token.py` — InviteToken table
- `backend/alembic/versions/4dce9ab938ce_add_invite_tokens_table.py` — migration
- `backend/app/services/email.py` — SES send helper
- `backend/app/routers/registration.py` — `/registration/invite`, `/validate`, `/complete`
- `frontend/src/pages/Register.tsx` — public registration page
- `docs/decisions/ADR-071-Invite-Token-Registration-Flow.md`

### Modified files
- `backend/app/models/__init__.py` — InviteToken import
- `backend/app/core/config.py` — `ses_from_email`, `app_base_url`
- `backend/app/routers/employees.py` — POST / and POST /bulk now use token+SES
- `backend/app/main.py` — registration router registered
- `frontend/src/App.tsx` — `/register` public route added

## Corrections made mid-session

- Alembic autogenerate picked up unrelated schema drift (removed FKs from
  previous migrations, dropped columns). Manually rewrote the migration to only
  create the `invite_tokens` table.
- `secrets` and `timedelta` imports added to `employees.py` before the
  `create_employee` body was updated — IDE flagged them as unused until the
  body replacement happened in the next edit.

## Open issues

- `pending_verification` employees created under the old flow have no
  `invite_tokens` row. They need to be re-invited via `POST /registration/invite`.
- SES still in sandbox — invite emails only reach verified addresses until AWS
  approves production access (ADR-067).
- Mobile `/register` equivalent not yet built (Phase 2, Step 2).

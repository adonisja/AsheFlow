# Journal: Employee Onboarding — Email Verification, Lifecycle States, and Celery Cleanup
**Date:** 2026-04-18

---

## Context

The existing employee creation flow had no email verification, no lifecycle state distinction between "invited" and "active", no Discord server invite, and no cleanup for stale invites. This session addressed all four.

---

## Changes Applied

### `backend/app/models/employee.py`

- Added `account_status` column: `String(30)`, check constraint `IN ('pending_verification', 'active', 'deactivated')`, default `pending_verification`, indexed.
- Added `invited_at` column: `DateTime(timezone=True)`, nullable.
- Changed `is_active` default from `True` to `False`.
- Added `VALID_ACCOUNT_STATUSES` constant.

### `backend/alembic/versions/f1a2b3c4d5e6_add_account_status_invited_at_to_employees.py`

New migration. Existing rows default to `account_status = 'active'` (they're already real employees). New rows default to `pending_verification`. `is_active` server default flipped to `false`.

### `backend/app/schemas/employee.py`

Added `account_status: str = "active"` to `EmployeeResponse`.

### `backend/app/routers/employees.py`

- `create_employee`: Removed `email_verified: true` from `AdminCreateUser` attributes. Employee created with `is_active=False`, `account_status="pending_verification"`, `invited_at=now()`.
- `update_employee`: If email changes on a `pending_verification` account — delete old Cognito user, recreate with new email, stamp new `cognito_sub`, reset `invited_at`. Role-change group sync unchanged but now only runs for non-pending accounts.

### `backend/app/api/deps.py`

`get_caller_employee` first-login path: when `cognito_sub` is stamped for the first time and `account_status == pending_verification`, flip to `active` + `is_active = True` and call `_send_discord_invite()`. New `_send_discord_invite()` helper fires the bot webhook in a daemon thread — best-effort, never blocks the login response.

### `backend/app/core/config.py`

Added `invite_expiry_days: int = 7`.

### `backend/requirements.txt`

Added `celery[redis]==5.3.6`.

### `backend/app/celery_app.py` (new)

Celery app pointed at Redis. Beat schedule: `expire_pending_invites` daily at 03:00 UTC.

### `backend/app/tasks/__init__.py` (new, empty)

### `backend/app/tasks/cleanup.py` (new)

`expire_pending_invites` task. Queries `pending_verification` employees older than `invite_expiry_days`. For each: `admin_delete_user` in Cognito (tolerates `UserNotFoundException`), then `db.delete(employee)`. Commits once after all deletions. Returns summary dict for observability.

### `docker-compose.yml`

Uncommented and configured `celery_worker` service. Uses `--beat` flag to run scheduler and worker in one process. Mounts `./backend:/app` volume. Depends on postgres (healthy) and redis (healthy).

### `bot/main.py`

- Added `cogs.invite` to `COGS` list.
- Added `trigger_invite(discord_id, name)` method to `AsheFlowBot`.
- Added `handle_invite` aiohttp route handler at `POST /internal/invite`.
- Registered route in `start_webhook_server`.

### `bot/cogs/invite.py` (new)

`InviteCog` with `send_guild_invite(discord_id, name)`. Creates a single-use 7-day `discord.Invite` on the configured channel, fetches the user by ID, DMs the invite link. All failures logged, none raised.

### `bot/config.py`

Added `discord_invite_channel_id: int = 0` (optional; falls back to drivers channel if 0).

---

## Files Changed

| File | Change |
|---|---|
| `backend/app/models/employee.py` | `account_status`, `invited_at`, `is_active` default |
| `backend/app/schemas/employee.py` | `account_status` field in `EmployeeResponse` |
| `backend/app/routers/employees.py` | Pending-status creation, wrong-email recovery |
| `backend/app/api/deps.py` | First-login activation + `_send_discord_invite` |
| `backend/app/core/config.py` | `invite_expiry_days` |
| `backend/requirements.txt` | `celery[redis]` |
| `backend/app/celery_app.py` | New |
| `backend/app/tasks/__init__.py` | New |
| `backend/app/tasks/cleanup.py` | New |
| `backend/alembic/versions/f1a2b3c4d5e6_...` | New migration |
| `docker-compose.yml` | `celery_worker` service enabled |
| `bot/main.py` | Invite cog, `trigger_invite`, `/internal/invite` route |
| `bot/cogs/invite.py` | New |
| `bot/config.py` | `discord_invite_channel_id` |

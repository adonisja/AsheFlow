# ADR-044: Employee Onboarding — Email Verification, Account Lifecycle, and Invite Expiry

**Date:** 2026-04-18  
**Status:** Accepted

---

## Context

The previous `POST /employees/` flow created employees with `is_active=True` and `email_verified: true` stamped on the Cognito user at creation time. This meant:

1. If the admin entered a wrong email address, the Cognito user and DB record were permanently linked to a bad address with no recovery path.
2. The employee was considered "active" before they had ever logged in — a ghost account eligible for dispatch.
3. No Discord server invite was sent; employees had to be added to the server manually.
4. Expired/abandoned invites (wrong email, employee left before onboarding) accumulated in the DB indefinitely.

---

## Decision

### Account lifecycle state machine

A new `account_status` column (enum: `pending_verification` | `active` | `deactivated`) replaces the implicit "active by default" assumption. `is_active` is now derived from `account_status`:

| Status | `is_active` | Meaning |
|---|---|---|
| `pending_verification` | `False` | Invited, never logged in |
| `active` | `True` | Logged in at least once, verified |
| `deactivated` | `False` | Manually disabled by management |

`invited_at` timestamp records when the invite was issued.

### Invite flow

`AdminCreateUser` no longer pre-stamps `email_verified: true`. Cognito sends its own temp-password email. The employee verifies email, completes the password-change challenge, and logs in.

### First-login activation (`deps.py`)

When `get_caller_employee` stamps `cognito_sub` for the first time (the moment we know the email was valid and the person completed verification), if `account_status == pending_verification`:
- Flip to `active`, set `is_active = True`
- Fire `POST /internal/invite` to the bot in a background thread (best-effort)

### Wrong-email recovery

If management updates an email on a `pending_verification` account (`PUT /employees/{id}`):
- Delete the old Cognito user
- Recreate with the corrected email (fresh invite sent)
- Stamp new `cognito_sub` and reset `invited_at`

This is only allowed while `account_status == pending_verification`. Active accounts must use the Cognito console.

### Discord server invite (`cogs/invite.py`)

On first login, the bot DMs a single-use, 7-day guild invite to the employee's Discord ID. The invite lands in a configurable channel (`DISCORD_INVITE_CHANNEL_ID`, defaults to drivers channel).

### Celery cleanup job

A Celery Beat task (`expire_pending_invites`) runs daily at 03:00 UTC. It deletes all employees where `account_status = pending_verification` AND `invited_at < now - INVITE_EXPIRY_DAYS` (default 7 days). For each:
1. Delete the Cognito user (`admin_delete_user`)
2. Delete the DB row

`UserNotFoundException` from Cognito is treated as success (already gone). Other Cognito failures are logged but don't block DB deletion.

---

## Consequences

- **Data integrity**: No active employees in the DB that haven't verified an email.
- **Wrong-email recovery**: Admin can correct the email before first login with a single `PUT` — no manual Cognito console work required.
- **DB hygiene**: Abandoned invites are automatically pruned after 7 days.
- **Discord onboarding**: New employees receive a server invite automatically on first login.
- **New infrastructure**: Celery worker container added to `docker-compose.yml`. Uses existing Redis as broker — no new services.

---

## Alternatives Considered

- **APScheduler** — rejected; tied to web server uptime, doesn't scale correctly across multiple backend instances. Celery was already planned in `docker-compose.yml`.
- **Keep `email_verified: true`** — rejected; defeats the purpose of verification and prevents wrong-email detection.
- **Separate Celery Beat container** — valid for production at scale; deferred. Current `--beat` flag on the worker is sufficient for single-worker deployments.

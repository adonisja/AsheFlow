# ADR-076 — Registration Flow Refinements

**Date:** 2026-05-08  
**Status:** Accepted

## Context

ADR-074 described the initial registration rewrite. Several follow-on decisions were made during testing and UX review that materially changed the implementation.

## Changes from ADR-074

### Single branded credentials email (replaces two-email flow)

ADR-074 described Cognito sending its own plain-text credential email plus a separate branded welcome email. This was replaced:

- `AdminCreateUser` is now called with `MessageAction="SUPPRESS"` — Cognito's system email is suppressed entirely
- The backend generates its own temp password meeting Cognito's policy: `3 uppercase + 3 digits + 2 lowercase + 2 symbols`
- `send_credentials_email()` sends one branded HTML email containing both username and temp password
- The employee receives exactly one email after registration

### Discord invite via SES (replaces bot DM)

The Discord bot cannot DM users who don't already share a server with it. The invite flow was changed:

- Bot's `/internal/invite` endpoint now returns `{"invite_url": "..."}` synchronously (creates a guild invite URL)
- `_send_discord_invite()` in `deps.py` calls the bot endpoint, reads the URL, and emails it via SES on a background thread
- This fires on first login when `account_status` flips from `pending_verification` to `active`

### Activation decoupled from cognito_sub stamping

The original `get_caller_employee` only activated an account when `cognito_sub` was null. Since registration now stamps `cognito_sub` before the employee ever signs in, activation was never firing. Fixed by checking `account_status == "pending_verification"` independently:

```python
if employee and sub and not employee.cognito_sub:
    employee.cognito_sub = sub
    needs_commit = True

if employee and employee.account_status == "pending_verification":
    employee.account_status = "active"
    employee.is_active = True
    needs_commit = True
    _send_discord_invite(employee)
```

### discord_id nullable + partial unique index

`discord_id` is not collected at employee creation (manager may not know it) — only at registration. The column was made nullable and the table-level unique constraint replaced with a partial index:

```sql
CREATE UNIQUE INDEX uq_employees_company_discord_id
ON employees (company_id, discord_id)
WHERE discord_id IS NOT NULL;
```

This allows multiple pending employees without Discord IDs while still enforcing uniqueness once set.

### Admin delete endpoint

`DELETE /employees/{id}` added (admin-only). Sequence:
1. `_cognito_revoke_access` — kills active sessions
2. `admin_delete_user` — removes Cognito account
3. `write_audit(...)` — records `employee.deleted` with full before-snapshot
4. `db.delete` + `db.commit`

### Employee lifecycle states

`account_status` + `invited_at` + `username` together express five distinct states:

| State | Condition |
|---|---|
| Not invited | `pending_verification` + `invited_at IS NULL` |
| Invited | `pending_verification` + `invited_at IS NOT NULL` + `username IS NULL` |
| Registered | `pending_verification` + `username IS NOT NULL` |
| Active | `account_status = active` + `is_active = true` |
| Deactivated | `account_status = active` + `is_active = false` |

`invited_at` and `username` added to `EmployeeResponse` schema so the frontend can derive state without a separate endpoint. The People table status badge and filter dropdown now use these five states instead of the previous three.

## Consequences

- Single email is cleaner UX and eliminates the risk of Cognito's plain email arriving before/after our branded one
- Discord invite via email works for all employees regardless of server membership
- Lifecycle states give admins precise visibility into where each employee is in the onboarding pipeline, making failure diagnosis straightforward
- The partial unique index correctly handles the multi-tenant case where different companies could theoretically have employees with the same Discord ID (they're scoped to `company_id`)

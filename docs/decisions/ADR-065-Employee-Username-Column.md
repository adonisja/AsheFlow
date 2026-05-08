# ADR-065: Employee Username Column and Auth Lookup Chain Update

**Date:** 2026-05-07
**Status:** Implemented

## Context

Phase 1, Step 3 of the multi-tenant migration. The new Cognito user pool uses
`username` as the sign-in identifier (e.g. `danny.rivera`) rather than email.
The `employees` table needed a matching column, and the auth lookup chain in
`deps.py` needed updating to match on it.

## Decision

Added `username VARCHAR(100) UNIQUE` to `employees`, nullable for now.
Becomes NOT NULL after the new Cognito pool is live and all employees have
completed registration.

**Username generation rules (for registration flow — Phase 2):**
- Auto-generated as `firstname.lastname` from the employee's full name
- Lowercased, spaces stripped
- Collision: append incrementing integer (`danny.rivera` → `danny.rivera2`)
- Managers cannot manually set usernames — system-assigned only

**Auth lookup chain updated in `_resolve_employee_from_cognito` (`deps.py`):**

1. `cognito_sub` match — fast path after first login
2. `Employee.username == jwt_username` — new pool (danny.rivera)
3. `Employee.discord_id == jwt_username` — old pool fallback (discord_id was username)
4. `Employee.email` match
5. UUID fallback

Steps 2 and 3 run concurrently during the pool transition period. Once the
old pool is decommissioned, step 3 can be removed.

## Seeded usernames

8 test Cognito accounts were given clean usernames:

| role | username |
|---|---|
| driver | driver.test |
| walker | walker.test |
| trainer | trainer.test |
| trainee | trainee.test |
| management | manager.test |
| dispatch | dispatch.test |
| dispatch (bot) | asheflow.bot |
| admin | test.user |

Only 2 of these existed as DB employee records (asheflow.bot, test.user).
The other 6 were Cognito-only and were recreated in the new pool.

## Files changed

- `backend/alembic/versions/h3c4d5e6f7g8_add_username_to_employees.py`
- `backend/app/models/employee.py` — username column added
- `backend/app/api/deps.py` — `_resolve_employee_from_cognito` updated

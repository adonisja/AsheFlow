# Journal: Bot DM Trainer-Trainee Pairing + reset_on_graduation

**Date:** 2026-04-22  
**Session context:** Follow-up to ADR-046 training system implementation

---

## What was done

### reset_on_graduation

- Added `reset_on_graduation Boolean NOT NULL DEFAULT false` to `employees` table via migration `b2c3d4e5f6a1`
- Added matching column to `Employee` ORM model
- Updated `graduate_trainees.py` to branch on this flag:
  - `False` (default): promotes to walker as before
  - `True`: deletes all training records/tasks for the trainee, leaves role as trainee, fires `trainee_reset` notification
- Set `reset_on_graduation=True` for Timmy Trainee via `scripts/seed_trainees.py`

### Seed trainees

- Created `scripts/seed_trainees.py` — idempotent script that:
  - Sets Timmy's reset flag
  - Adds 8 simulation trainees (Alex Rivera, Jordan Wu, Morgan Davis, Casey Thompson, Riley Patel, Taylor Brooks, Drew Okafor, Cameron Singh)
- All 8 added with `account_status=active`, no Cognito accounts (simulation only)

### Bot DM pairing

- Added `_fetch_trainee_phases()` async helper in `bot/cogs/dispatch.py` — calls API per trainee, falls back to `"?"` on error
- Added `get_trainee_current_phase(trainee_id)` to `bot/services/api_client.py`
- DM description now appends:
  - Trainee: `🎓 Your trainer today: [names]` or a warning if no trainer
  - Trainer: `📋 Your trainee(s) today: [name — Phase N]` per trainee

---

## Key decisions

- Phase lookup fires at publish time, not post-confirmation. Accepted risk: ~small fraction of declined-before-seen DMs carry a phase callout that becomes irrelevant. No correctness issue.
- Hard-delete training records on reset (not soft-reset) because training_injection reads `current_day_number` from existing records; leaving stale records would skip Phase 1 re-injection.

---

## Files changed

- `backend/alembic/versions/b2c3d4e5f6a1_add_reset_on_graduation_to_employees.py` (new)
- `backend/app/models/employee.py`
- `backend/app/services/graduate_trainees.py`
- `backend/scripts/seed_trainees.py` (new)
- `bot/cogs/dispatch.py`
- `bot/services/api_client.py`
- `docs/decisions/ADR-047-Bot-DM-Trainer-Trainee-Pairing-And-Reset-On-Graduation.md` (new)

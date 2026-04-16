# Journal — Training Debt Age Tracking and Escalation

**Date:** 2026-04-10  
**Author:** adonisja

---

## Context

The training injection system (introduced in a prior session) rolls mandatory
incomplete tasks forward into the next dispatch day's `TrainingTask` rows as
"training debt." While deduplication by `topic_title` prevents the same task
from appearing multiple times on a single record, the original implementation
had no mechanism to track how long a debt had been outstanding or to alert
managers when a trainee had chronic unresolved gaps.

The gap: a trainee could carry the same mandatory task as debt indefinitely,
progressing through `current_day_number` with no enforcement, and no one in
management would know unless they manually reviewed individual records.

---

## Problem Discussion

Four options were considered:

1. **Debt age counter + UI highlight** — track how many times a task has rolled
   over and surface age in the UI (yellow at 2, red at 3+).

2. **Day progression lock** — don't advance `current_day_number` while debt
   exists. Forces completion before moving forward.

3. **Debt threshold → escalation flag** — let debt accumulate but automatically
   flag the record for manager review when age hits a threshold.

4. **Mandatory vs. recommended debt split** — two tiers of mandatory: one that
   blocks progression, one that only warns.

Options 2 and 4 were deferred. Option 2 risks penalizing trainees for trainer
failures (tasks left unchecked by an absent or negligent trainer). Option 4
requires upfront curriculum design decisions and UI for tier management.

**Decision:** Options 1 and 3 combined. Low implementation cost, no structural
changes to the progression model, creates a human review loop for chronic cases.

---

## Implementation

### Model changes — `training_tasks`

Two new columns added to `TrainingTask`:

- `debt_age` (Integer, default 0) — increments by 1 each time the task rolls
  into a new record as debt. A task introduced today has `debt_age = 0`. On
  first rollover it becomes 1, on second rollover 2, etc.

- `is_escalated` (Boolean, default False) — set to `True` automatically when
  `debt_age >= DEBT_ESCALATION_THRESHOLD` (currently 3). Never set manually.

### Constant — `DEBT_ESCALATION_THRESHOLD = 3`

Added to `backend/app/services/constants.py`. Threshold of 3 means a task
must survive 3 dispatch days unresolved before escalating. This gives trainers
reasonable time to complete tasks across different field conditions before
management is alerted.

### Injection change — `training_injection.py`

In the debt rollover loop, `new_debt_age = (dt.debt_age or 0) + 1` is computed
before creating the new `TrainingTask`. `is_escalated` is set inline:

```python
is_escalated=new_debt_age >= DEBT_ESCALATION_THRESHOLD
```

No separate pass required — escalation is a pure function of age at the moment
of rollover.

### New endpoint — `GET /training/escalated`

Management/Admin only. Returns all trainees with at least one unresolved
escalated task, deduped to their most recent record, sorted by number of
escalated tasks descending (worst case first). Each entry includes:

- Trainee and trainer identity
- The full training record
- All escalated tasks sorted by `debt_age` descending (oldest debt first)

### Schema changes — `TrainingTaskResponse`

`debt_age` and `is_escalated` added to `TrainingTaskBase` so they are returned
on all task reads, not just the escalation endpoint. This allows the trainer
dashboard and trainee history views to highlight aging debt in the UI.

### Migration — `a79c6156f489`

`op.add_column` for both new columns with `server_default` values (`0` and
`false`) so existing rows are backfilled safely without a data migration step.
Phantom `drop_column` lines for `training_records.trainee_comments` and
`trainer_rating` were stripped before running (known model/DB drift from prior
`alter_db.py` scripts).

---

## Files Changed

- `backend/app/models/training.py` — added `debt_age`, `is_escalated` to `TrainingTask`
- `backend/app/services/constants.py` — added `DEBT_ESCALATION_THRESHOLD = 3`
- `backend/app/services/training_injection.py` — imported constant, increments age, sets flag on rollover
- `backend/app/schemas/training.py` — added `debt_age`, `is_escalated` to `TrainingTaskBase`
- `backend/app/routers/training.py` — added `GET /training/escalated` endpoint
- `backend/alembic/versions/a79c6156f489_add_debt_age_and_escalation_to_training_.py` — migration

---

## UI Notes (not yet implemented)

The frontend should use `debt_age` and `is_escalated` from task responses to:

- Show a neutral badge for `debt_age == 1` (first rollover)
- Show a yellow warning badge for `debt_age == 2`
- Show a red escalation badge for `is_escalated == True` (`debt_age >= 3`)

The `GET /training/escalated` endpoint should be polled or surfaced on the
manager/trainer dashboard as an alert count badge.

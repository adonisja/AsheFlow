# Journal — Manual Trainee Reassignment

**Date:** 2026-04-10  
**Author:** adonisja

---

## Context

Dispatchers, managers, and admins needed the ability to manually reassign a
trainee to a specific trainer after dispatch has already run for a given day.
The existing system only allowed trainee-trainer pairing to be determined by the
dispatch algorithm at run time, with no post-dispatch override mechanism.

---

## Implementation

### Schema — `TraineeReassignRequest`

Added to `backend/app/schemas/training.py`:

```python
class TraineeReassignRequest(BaseModel):
    trainee_id: UUID
    new_trainer_id: UUID
    target_date: date
```

### Endpoint — `PATCH /training/trainee/reassign`

Accessible to: management, dispatch, and admin.

**Full workflow:**

1. Fetch the trainee's `TrainingRecord` for `target_date`. Return 404 if none
   exists — reassignment only makes sense for days where training injection
   already ran.

2. Verify `new_trainer_id` exists and has `role == "trainer"`. Return 404 if
   not found or wrong role.

3. Check if the new trainer already owns a `TrainingRecord` for `target_date`
   with a different trainee (i.e., they already have someone assigned):
   - **If yes:** Find all active trainers with no training record today (no
     current trainee). If none are available, return 409 — the operation cannot
     proceed without displacing a trainee with nowhere to go.
   - If available trainers exist: pick one at random (`random.choice`), update
     the displaced trainee's record to point to the fallback trainer, build a
     warning message, and send a `Notification` of type
     `"trainee_reassign_warning"` to the acting user's employee record (looked
     up via `current_user["username"]` matching `discord_id`).

4. Update the target trainee's `TrainingRecord.trainer_id` to `new_trainer_id`.

5. Commit and return summary: trainee identity, new trainer identity, date, and
   any warnings.

### Warning notification

The warning is both returned in the response body (`warnings` list) and
persisted as a `Notification` row for the acting user. This means:
- The dispatcher sees it immediately in the UI response
- It also appears in their in-app notification banner on next load

### No changes to TrainingTask rows

Reassignment only updates `trainer_id` on the `TrainingRecord`. Existing
`TrainingTask` rows are untouched — the task list for the day was set by
curriculum injection and remains valid regardless of which trainer delivers it.

---

## Design Decisions

- **Random fallback, not algorithmic:** The displaced trainee's new trainer is
  chosen with `random.choice` from available trainers rather than running the
  full dispatch weight algorithm. This is intentional — the reassignment is a
  manual override already, and running the weight algorithm for a single
  placement mid-day adds complexity with marginal benefit.

- **409 on no available fallback, not silent best-effort:** If there is no
  trainer available to absorb the displaced trainee, the operation is rejected
  outright. A silent best-effort (e.g., leaving displaced trainee without a
  trainer) would create a confusing state harder to detect and correct.

- **Notification to actor, not to affected trainers:** The warning goes to the
  dispatcher/manager who performed the action, not to the affected trainers.
  Trainers will see their updated trainee assignment by checking their trainer
  dashboard — a separate notification to them is a future enhancement.

---

## Files Changed

- `backend/app/schemas/training.py` — added `TraineeReassignRequest`
- `backend/app/routers/training.py` — added `PATCH /training/trainee/reassign`,
  imported `Notification` and `TraineeReassignRequest`

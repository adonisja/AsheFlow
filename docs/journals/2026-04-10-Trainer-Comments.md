# Journal — Trainer Comments on Training Records

**Date:** 2026-04-10  
**Author:** adonisja

---

## Context

`trainer_comments` already existed as a nullable `Text` column on `TrainingRecord`
and was present in `TrainingRecordResponse`, but no write endpoint existed and the
field was returned to all callers including trainees — who should not see internal
trainer notes.

---

## Implementation

### Schema — `TrainerCommentCreate`

Added to `backend/app/schemas/training.py`:

```python
class TrainerCommentCreate(BaseModel):
    comments: str
```

### Endpoint — `POST /training/trainee/{trainee_id}/trainer-comments`

Accessible to: trainer and admin.

- Fetches the trainee's most recent `TrainingRecord`
- Returns 404 if no record exists
- Returns 400 if the record is locked (same lock rule as task edits)
- Appends to existing `trainer_comments` with an `[Added later]` prefix if
  content already exists, rather than overwriting
- Returns the full `TrainingRecordResponse` including tasks

### Visibility restriction on `GET /training/trainee/{id}`

The existing history endpoint allows trainee, trainer, management, and admin.
Added a privilege check: if the caller's groups do not include trainer,
management, or admin, `trainer_comments` is set to `None` before returning.
Trainees see their own records but never see internal trainer notes.

---

## Files Changed

- `backend/app/schemas/training.py` — added `TrainerCommentCreate`
- `backend/app/routers/training.py` — added `POST /training/trainee/{id}/trainer-comments`,
  imported `TrainerCommentCreate`, added visibility strip in `get_trainee_history`

# Journal — Trainer Continuation Requests

**Date:** 2026-04-10  
**Author:** adonisja

---

## Context

Trainees needed the ability to request continuation with the same trainer on
their next assigned dispatch day. The process is deliberately silent — trainers
see and respond to requests on their dashboard, but the trainee receives no
feedback either way. This removes social pressure on the trainer's decision and
prevents trainees from knowing whether they were accepted or rejected.

---

## Full Lifecycle

```
Trainee submits request
  → POST /continuation-requests/
  → status = "pending"
  → Trainer receives in-app notification

Trainer sees request on dashboard
  → GET /continuation-requests/trainer/{trainer_id}

Trainer accepts
  → PATCH /continuation-requests/{id}/accept
  → status = "accepted"

  OR

Trainer rejects (silent)
  → PATCH /continuation-requests/{id}/reject
  → status = "nullified", resolved_at = now

On trainee's next dispatch day (training_injection runs):
  Case A — accepted request exists:
    - Check if requested trainer is in assigned_crews for today
    - If available: override dispatch-assigned trainer_id with requested trainer
    - If unavailable: use dispatch-assigned trainer (request ignored)
    - Either way: nullify the request (resolved)

  Case B — pending request still exists (trainer never responded):
    - Auto-nullify (expired)
    - Use dispatch-assigned trainer normally

  Case C — no active request:
    - Use dispatch-assigned trainer normally
```

---

## Implementation

### Model — `TrainerContinuationRequest`

New table `trainer_continuation_requests`:
- `trainee_id` / `trainer_id` — FK to employees (CASCADE delete)
- `status` — `"pending"` | `"accepted"` | `"nullified"`
- `created_at` — server default now()
- `resolved_at` — nullable, set on accept/reject/nullify

### Router — `continuation_requests.py`

| Endpoint | Role | Behaviour |
|---|---|---|
| `POST /continuation-requests/` | trainee/admin | Creates request, nullifies any prior active one, notifies trainer |
| `GET /continuation-requests/trainer/{id}` | trainer/admin | Returns all pending requests for that trainer |
| `PATCH /continuation-requests/{id}/accept` | trainer/admin | Sets status to accepted |
| `PATCH /continuation-requests/{id}/reject` | trainer/admin | Sets status to nullified — silent, no trainee notification |

Only one active (pending or accepted) request per trainee is allowed at a time.
Submitting a new request auto-nullifies any existing active one.

### Injection hook — `training_injection.py`

At the start of each trainee's processing loop, before the `TrainingRecord` is
created or updated:

1. Query for an `accepted` request for this trainee.
   - If found and the requested trainer is in today's `assigned_crews` → override
     `trainer_id` with the requested trainer.
   - Nullify the accepted request regardless (it has served its purpose).

2. Query for a `pending` request (trainer never responded).
   - If found → auto-nullify (expired on next dispatch day).

3. Proceed with `trainer_id` as resolved above into `TrainingRecord` creation.

The availability check uses `assigned_crews` (already in memory) rather than a
DB query — the trainer must be actively assigned to a truck today, not just
available in the pool.

### Notification

On submission, the trainer receives a `Notification` of type
`"continuation_request"` with the trainee's name. This surfaces on their
existing notification feed / dashboard. No notification is sent on accept or
reject — the process is one-directional and silent to the trainee.

---

## Files Changed

- `backend/app/models/trainer_continuation_request.py` — created
- `backend/app/models/__init__.py` — registered model
- `backend/app/schemas/continuation_request.py` — created
- `backend/app/routers/continuation_requests.py` — created
- `backend/app/main.py` — registered router
- `backend/app/services/training_injection.py` — added continuation request
  resolution block before record creation
- `backend/alembic/versions/fc431d5d5452_add_trainer_continuation_requests.py` — migration applied

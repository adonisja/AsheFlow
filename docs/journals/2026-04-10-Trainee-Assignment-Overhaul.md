# Journal — Trainee Assignment Overhaul

**Date:** 2026-04-10  
**Author:** adonisja

---

## Context

The original trainee assignment system distributed trainees across trucks using a
truck-level round-robin, the same mechanism used for walkers. This was incorrect
— trainees are attached to trainers, not trucks. A trainee cannot be on a truck
without a paired trainer, but a trainer can be on a truck without a trainee.

Additionally, several issues were identified with the continuation request system,
the rebalancer, and graduation nullification.

---

## Changes

### 1. assign_trainees.py — Trainer-centric round-robin

Complete rewrite. Trainees now roll onto trainers (not trucks):

- Build `trainer_to_truck` map from `assigned_crews` after Pass 2.
- Count trainees already paired to each trainer.
- Eligible trainers = those at the current minimum paired-trainee count.
- Uniform random selection (no fav/ban weights — trainees have no relationship list).
- Trainee appended to the trainer's truck with `paired_trainer_id` set in the
  crew dict so downstream code (injection, rebalancer) knows the bond without
  a DB query.
- `base_weights` parameter removed — no longer used.

### 2. run_dispatch.py — Continuation request pre-pass before Pass 3

Accepted continuation requests are now resolved in `run_dispatch` before the
trainee rolling pool runs, not in `training_injection` after DB write.

**Pre-pass flow:**
1. After Pass 2 (trainers placed), build `trainer_to_truck`.
2. Fetch all accepted requests whose trainee is in today's pool.
3. Group by trainer. For each trainer's requests, apply sort order:
   - Explicit `priority` integer (lower = higher priority, None = unranked/lowest)
   - LIFO tiebreaker: most recent `TrainingRecord.record_date` where trainee
     trained with this trainer (most recent relationship = higher priority)
4. Trainer unavailable in `assigned_crews` → nullify all their requests, trainees
   rejoin pool.
5. Trainer available → winner (index 0) is injected directly into `assigned_crews`
   with `paired_trainer_id`, removed from rolling pool. Losers nullified, rejoin pool.
6. Any still-pending requests (trainer never responded) are auto-expired here too.

This moves expiry logic out of `training_injection` — injection now only reads
`paired_trainer_id` from the crew dict, no longer queries for continuation requests.

### 3. rebalance_crews.py — Trainee/bonded-trainer exclusion + dispatch notification

Candidate eligibility updated:
- **Excluded:** drivers, trainees (always), trainers with a paired trainee.
- **Eligible:** walkers, trainers without a paired trainee.

On no-safe-move exit: `_notify_dispatch()` queries all active employees with
`role in ("dispatch", "management", "admin")` and sends each a
`"rebalance_intervention_required"` notification including truck names (not IDs)
and the member count delta.

### 4. continuation_requests.py — Backend guard + priority endpoint

**Backend guard:** `POST /continuation-requests/` now verifies the requested
`trainer_id` matches the trainee's most recent `TrainingRecord.trainer_id`.
Prevents requests to arbitrary trainers.

**Priority endpoint:** `PATCH /continuation-requests/{id}/priority`
- Trainer/admin only
- Ownership check: caller's `discord_id` must match the request's `trainer_id`
  (admins bypass)
- No duplicate priority integers allowed among same trainer's active requests
- `priority=None` clears ranking (reverts to unranked)
- Only pending/accepted requests can be ranked

### 5. graduate_trainees.py — Nullify open requests on graduation

When a trainee graduates to walker, any pending/accepted continuation requests
are nullified with `resolved_at = now()`. Prevents stale requests from sitting
open indefinitely since graduated trainees no longer go through training_injection.

### 6. training_injection.py — Simplified (continuation logic removed)

The accepted-request check and pending-expiry logic have been removed from
injection — both now happen in `run_dispatch` pre-pass. Injection simply reads
`paired_trainer_id` from the crew dict member if present, falls back to
`trainer[0]` on the truck for legacy compatibility.

---

## Migration

`3f487497f021` — adds nullable `priority` integer column to
`trainer_continuation_requests`. Applied cleanly.

---

## Files Changed

- `backend/app/services/assign_trainees.py` — full rewrite
- `backend/app/services/run_dispatch.py` — pre-pass, updated call signature
- `backend/app/services/rebalance_crews.py` — candidate filter, notify dispatch
- `backend/app/services/graduate_trainees.py` — nullify open requests
- `backend/app/routers/continuation_requests.py` — backend guard, priority endpoint
- `backend/app/schemas/continuation_request.py` — PriorityUpdate, priority field
- `backend/app/models/trainer_continuation_request.py` — priority column
- `backend/alembic/versions/3f487497f021_add_priority_to_continuation_requests.py`

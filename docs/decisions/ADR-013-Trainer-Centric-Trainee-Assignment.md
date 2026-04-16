# ADR-013 — Trainer-Centric Trainee Assignment and Continuation Request Overhaul

**Date:** 2026-04-10  
**Status:** Accepted  
**Author:** adonisja

---

## Context

The original dispatch treated trainees as truck-level assignees (same as walkers).
This produced incorrect outcomes: multiple trainees could pile onto one trainer,
trainees could be placed on trucks with no trainer, and the trainer:trainee bond
had no structural enforcement.

---

## Decisions

### Trainees roll onto trainers, not trucks

The unit of distribution for trainees is the trainer, not the truck. A trainee's
truck placement is a derived consequence of their trainer's truck placement.

No fav/ban weights are applied — trainees have no relationship list. Assignment
is a uniform random round-robin across trainers at the current minimum paired
count. This naturally enforces max-1-per-trainer-first, max-2-per-trainer-second,
etc.

The `paired_trainer_id` field is stored in the in-memory crew dict so all
downstream logic (injection, rebalancer) can read the bond without DB queries.

### Continuation request resolution moves to run_dispatch pre-pass

Previously resolved in `training_injection` after DB write. This was too late —
the trainee was already placed on a truck by the normal algorithm.

Resolution now happens between Pass 2 (trainers placed) and Pass 3 (trainee pool
runs). Accepted requests are honoured by injecting the trainee directly into the
trainer's truck and removing them from the rolling pool. Trainer unavailability
is checked against `assigned_crews` (must be dispatched, not just available).

### LIFO + explicit priority for collision resolution

When multiple accepted requests target the same trainer on the same dispatch day:

1. Explicit `priority` integer (lower = higher priority)
2. LIFO: most recent shared `TrainingRecord.record_date` (most recent training
   relationship = higher priority)
3. Unranked requests always lose to ranked ones; duplicate unranked resolved by LIFO

Priority is visible only to the trainer who set it (ownership enforced at endpoint
level, admins bypass). No duplicate priority integers allowed per trainer.

### Rebalancer excludes trainees and bonded trainers

Trainer:trainee bonds are never broken by rebalancing. Eligible candidates are
walkers and trainers without a paired trainee. Trainees are never moved
independently. On no-safe-move exit, all active dispatch/management/admin
employees are notified with truck names and the size delta.

### Continuation requests nullified on graduation

Graduated trainees no longer go through `training_injection`, so open requests
would otherwise be permanent. Nullification happens in `graduate_trainees` at the
moment of role change.

### Backend guard: most-recent-trainer only

The `POST /continuation-requests/` endpoint verifies the requested trainer matches
the trainee's most recent `TrainingRecord.trainer_id`. This is not merely a UI
concern — it must be enforced at the API layer to prevent arbitrary pairings.

---

## Consequences

**Positive:**
- Trainer:trainee bond is structurally enforced throughout the dispatch pipeline
- Trainees never land on trucks without a paired trainer
- Max-1-trainee-per-trainer-first guaranteed by round-robin structure
- Continuation request collision resolution is deterministic and auditable
- Rebalancer cannot break training relationships

**Negative:**
- `assign_trainees` no longer uses fav/ban weights — this is correct since trainees
  have no relationship list, but means no preference signal influences trainee
  placement beyond the continuation request mechanism
- Trainer priority rankings add UI complexity; trainers must be educated on their
  use to avoid confusion when a request is silently deprioritized

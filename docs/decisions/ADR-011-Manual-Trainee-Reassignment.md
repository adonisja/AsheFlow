# ADR-011 — Manual Trainee Reassignment

**Date:** 2026-04-10  
**Status:** Accepted  
**Author:** adonisja

---

## Context

The dispatch algorithm pairs trainees with trainers automatically at run time.
No mechanism existed to override this pairing after dispatch ran. Dispatchers,
managers, and admins needed a post-dispatch reassignment tool to handle cases
such as trainer absence, trainee-trainer conflict, or administrative corrections.

---

## Decision

Add `PATCH /training/trainee/reassign` accessible to management, dispatch, and
admin roles.

The endpoint handles the displacement case explicitly: if the target trainer
already has an assigned trainee, the displaced trainee is moved to a randomly
selected available trainer (one with no trainee today). If no available trainer
exists, the operation is rejected with 409 rather than proceeding into an
unresolvable state.

A warning notification is sent to the acting user both in the response body and
persisted to the `notifications` table.

---

## Alternatives Considered

### Run the full dispatch weight algorithm for the displaced trainee

The displaced trainee would be re-assigned using fav/ban weights rather than
random selection.

**Rejected.** Mid-day single-placement dispatch adds disproportionate complexity.
The displacement is a side-effect of a manual override — preference satisfaction
for the displaced trainee is secondary to completing the primary reassignment
cleanly. Random selection from available trainers is sufficient.

### Allow reassignment even with no available fallback trainer

Leave the displaced trainee without a trainer rather than blocking the operation.

**Rejected.** A trainee with a locked `TrainingRecord` and no trainer is an
ambiguous state — tasks still need to be checked off by someone. 409 forces the
dispatcher to resolve the staffing gap explicitly rather than leaving it silent.

### Notify affected trainers directly

Send notifications to both the old and new trainer about the change.

**Deferred.** Trainer-facing notifications require knowing the trainer's
`employee_id` reliably from the auth context, which is the same lookup problem
faced in other notification flows. This is a future enhancement once that
resolution pattern is standardised.

---

## Consequences

**Positive:**
- Dispatchers, managers, and admins have a clean override path for post-dispatch
  trainer-trainee pairings
- Displacement is handled atomically — no trainee is left unassigned
- Warning is surfaced immediately in the response and persisted for audit trail

**Negative:**
- Displaced trainee's new trainer is chosen randomly — no preference signal
- Trainers are not directly notified of the change; they must check their dashboard
- Operation fails entirely if all trainers already have trainees, even if the
  primary reassignment itself would be valid

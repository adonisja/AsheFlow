# ADR-060: Fix Excess-Trainer Dispatch Role Corruption

**Date:** 2026-05-04  
**Status:** Accepted

## Context

When more trainers were available than `num_trucks × MIN_TRAINERS_PER_TRUCK`, the dispatch engine moved excess trainers into the walker pool (`available_pool["walkers"].extend(excess_trainers)`). The `assign_walkers` function then hardcoded `role="walker"` for every employee it processed, creating `AssignmentMember` rows with `role="walker"` for employees whose canonical `Employee.role` is `"trainer"`.

This caused:
- Terry Trainer appearing as a walker on the dispatch dashboard
- Training records failing to surface (no trainer-role member found for the crew)
- Incorrect mobile Field Ops and Training screen data for the affected trainer

The bug was invisible at write time because no guard compared `AssignmentMember.role` against `Employee.role`.

## Decision

1. **Remove the trainer cap block entirely.** `assign_trainers` already uses a pure round-robin spread (minimum-first placement) with no ceiling per truck. The cap was the only thing preventing it from distributing all available trainers. With the cap gone, all trainers in the available pool are distributed evenly across trucks — there is no such thing as an "excess" trainer. 12 trainers across 5 trucks becomes 2-2-2-3-3, dynamically.

2. **Add a role-integrity guard at `AssignmentMember` write time.** Before persisting each crew member, look up `Employee.role`. If the employee is a trainer but the assigned role is not `"trainer"`, correct it, append a `role_integrity_violation` warning, and log the discrepancy. This acts as a last-resort safety net against any future code path that would silently demote a trainer.

## Consequences

- All available trainers are always dispatched; no trainer is ever left unassigned due to a per-truck ceiling.
- The `excess_trainer_unassigned` warning type is eliminated — dispatch never needs to be notified of it.
- `AssignmentMember.role` will always equal `Employee.role` for trainers (self-correcting guard).
- `MIN_TRAINERS_PER_TRUCK` is retained only for the understaffing warning (fires when trainers < trucks × 2), not as a ceiling.

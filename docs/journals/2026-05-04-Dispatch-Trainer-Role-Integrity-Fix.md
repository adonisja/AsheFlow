# 2026-05-04 — Dispatch Trainer Role Integrity Fix

## What happened

Terry Trainer appeared as `role="walker"` in `assignment_members` after a dispatch run. This broke training record surfacing on the mobile app and showed Terry as a walker on the dispatch dashboard.

## Root cause

`run_dispatch.py` lines 111-120 moved excess trainers (beyond `num_trucks × MIN_TRAINERS_PER_TRUCK`) into `available_pool["walkers"]`. The `assign_walkers` service hardcodes `role="walker"` for every employee it processes, so those trainer employees got the wrong role written to the DB.

## Fix applied

- **`backend/app/services/run_dispatch.py`**: Removed the walker re-slotting block. Excess trainers are now dropped from dispatch with an `excess_trainer_unassigned` warning per trainer. Added a role-integrity guard at `AssignmentMember` write time that corrects any trainer assigned a non-trainer role and appends a `role_integrity_violation` warning.

## DB remediation (already done in prior session)

- `UPDATE assignment_members SET role='trainer' WHERE employee_id = '<terry_id>'`
- Moved Timmy Trainee's `assignment_member` to the Falcon truck, updated `training_records.trainer_id` to Terry's ID.

## Files changed

- `backend/app/services/run_dispatch.py`
- `docs/decisions/ADR-060-Excess-Trainer-Dispatch-Fix.md`
- `docs/LEARNING_GUIDE.md`

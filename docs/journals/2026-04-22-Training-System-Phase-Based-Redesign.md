# Journal — Training System Phase-Based Redesign Design Session
**Date:** 2026-04-22

---

## What We Did

Conducted a full design specification session for the training system redesign. The existing 5-day calendar model was evaluated against the real-world training workflow and found to have structural problems that would produce incorrect data in production.

The session covered: phase progression model, debt definition and attribution, trainer accountability (marks, exemplary flags, underperforming flags), mid-shift handoff tracking, Phase 4 observation structure, pass/fail scoring, remediation on fail, early completion handling, missed days, submission deadlines, and curriculum content derived from the NYCD walker training form.

---

## Key Design Decisions Made

### Phase-based, not calendar-day-locked
Early completion of Phase 1 is expected and frequent. Locking progression to calendar dates would penalize strong trainers and produce false debt signals for all downstream trainers. Phases are curriculum units — a phase advances when all mandatory tasks are complete, not when a date ticks over.

### Debt only arises from force-unlock overrides
Under normal operation, the phase gate prevents Phase N+1 from opening while Phase N has outstanding mandatory tasks. This eliminates false positive debt entirely. Debt only exists when management manually overrides the gate.

### Single mark per incident, attributed to originator
A trainer who fails to close their phase receives one mark. If that failure creates a debt chain affecting subsequent sessions, the downstream impact is documented as context on the original mark — not as additional marks on subsequent trainers. This prevents a trainer from being penalized for someone else's failure.

### Trainer handoff tracking at topic level
Mid-shift handoffs (e.g. trainer emergency mid-session) are tracked via a `TrainerCoverage` table — one row per topic per trainer per record. The coverage log shows exactly who covered what and when, making handoff attribution auditable without ambiguity.

### Phase 4 is a scored observation, not a classroom day
Phase 4's curriculum is auto-generated from all mandatory topics in Phases 1–3 as observation items. Trainers observe the DA completing real deliveries and mark each item as observed-correctly or not. Score ≥ 90% with all mandatory items passing = pass. On fail, a Phase 5 remediation record is generated containing only the failed items.

### Exemplary trainer recognition
Trainers who close inherited debt AND their own phase in the same session are flagged as exemplary — positive signal for identifying strong trainers who can help train other trainers or refine procedures.

---

## What We Confirmed About Existing Infrastructure

- Continuation request system is fully built and wired into dispatch — trainer assignment is already driven by dispatch, with accepted continuation requests overriding the dispatch-assigned trainer
- `training_injection.py` already handles debt rollover but uses calendar-day logic (increments `current_day_number` linearly) — needs rework for phase-gate logic
- The 5-day cap in `training_injection.py` (line 104) needs to change to 4 phases + Phase 5 remediation path
- `TrainingCurriculum`, `TrainingRecord`, `TrainingTask` all exist — need column additions, not replacements

---

## Curriculum Source

Derived from the NYCD walker training Google Form (4-day regimen). Key addition from a separate HR email: ADP timekeeping compliance block added to Phase 1 (clock in/out with badge, timecard accuracy, Sunday night submission deadline, schedule removal for missing punches/incorrect times, mobile app for all punch corrections).

---

## Open Items / Follow-Up

None — all design questions were fully resolved in this session. See ADR-046 for the complete decision record. Implementation plan is in `docs/TRAINING-SYSTEM-IMPLEMENTATION-PLAN.md`.

---

## Files to be Created / Modified

**New:**
- Alembic migration for schema additions
- `backend/app/models/trainer_coverage.py`
- `backend/app/models/trainer_mark.py`
- `backend/app/services/check_phase_gate.py`
- `backend/app/services/record_trainer_mark.py`
- `backend/app/services/score_phase4.py`
- `backend/app/tasks/training_deadlines.py` (Celery Beat midnight check)
- `backend/app/routers/trainer_marks.py`
- `backend/app/routers/trainer_coverage.py`
- Frontend: training curriculum admin page
- Frontend: Phase 4 observation checklist UI
- Frontend: trainer mark / performance view

**Modified:**
- `backend/app/models/training.py` — column additions
- `backend/app/services/training_injection.py` — phase-gate logic
- `backend/app/celery_app.py` — register midnight deadline task
- `backend/app/services/constants.py` — update day cap from 5 to 4

# ADR-046 — Training System: Phase-Based Curriculum Redesign

**Date:** 2026-04-22  
**Status:** Accepted  
**Authors:** Akkeem (operations), Claude (architecture)

---

## Context

The existing training system was built around a 5-day calendar model: Day 1 topics are expected on Day 1, Day 2 topics on Day 2, and so on. Debt was any mandatory task not completed by end of its assigned calendar day.

When evaluated against the actual training workflow, the calendar-day model has several structural problems:

1. **Early completion is frequent and expected**, particularly on Day 1 (orientation and app setup). Blocking progression until the next calendar day penalizes strong trainers and motivated trainees.
2. **The existing debt system produces false positives** when early progression occurs — if a trainer completes Day 1 and partially covers Day 2 topics in a single session, the system would flag the partial Day 2 coverage as debt when it shouldn't be.
3. **Trainer attribution is missing entirely** — the system has no way to distinguish between a trainer who failed to cover topics vs. a trainer who inherited an unresolvable situation from the previous day.
4. **Mid-shift trainer handoffs are untracked** — if Trainer A leaves an emergency and Trainer B picks up, the system has no record of who covered which topics, making accountability impossible.
5. **The form-based curriculum** (the Google Form used by trainers) is a flat checklist across all 4 days with no enforced progression. Trainers can technically mark anything complete on any day.
6. **Day count was wrong** — the system was built for 5 days; the actual training regimen is 4 days, with Day 4 being a practical field shadowing session.

A new training design was developed through a detailed specification session covering early completion, debt attribution, trainer handoffs, missed days, pass/fail thresholds, and Phase 4 evaluation structure.

---

## Decision

### 1. Phase-Based Progression (Not Calendar-Day Locked)

`day_number` in `TrainingCurriculum` and `TrainingRecord` is reframed as a **phase number**. A phase is a curriculum unit, not a calendar date. The field name stays `day_number` in the database; the semantic meaning changes to "phase."

**Phase gate rule:** All mandatory topics in Phase N must be marked complete before any Phase N+1 topics can be started. The gate is enforced at the service layer — a topic completion request for Phase N+1 is rejected if Phase N still has open mandatory tasks.

**Phase progression in `training_injection.py`:** Instead of incrementing `current_day_number` linearly, the service checks whether the previous record's `phase_closed = True`. If yes, increment the phase. If no, the DA stays in the same phase on their next dispatch day.

**Phases only advance on confirmed dispatch days where the DA is physically present.** A missed day, callout, or no-show pauses training with no debt incurred and no penalty to any trainer.

### 2. Debt Definition — Phase-Scoped, Not Calendar-Scoped

Debt is redefined as: **a mandatory topic from Phase N that was not completed before Phase N+1 topics were started.**

Because the phase gate prevents Phase N+1 from opening while Phase N has outstanding mandatory tasks, debt can only arise in one scenario: a management override force-unlocks the next phase (e.g. operational necessity). In that case, skipped mandatory topics are flagged as debt with `force_unlocked_by` recorded.

The practical implication: under normal operation, debt as previously defined (calendar rollover) is eliminated. The gate enforces completion before progression.

### 3. Trainer Attribution and the Mark System

A new `TrainerMark` table records trainer accountability events. Marks are distinct from debt — a mark is a performance record against a specific trainer, while debt is a curriculum state on a training record.

**Mark assignment rules:**
- A mark fires when a phase is not closed (all mandatory tasks not complete) by midnight of a dispatch day, AND the trainer had no inherited debt when they started the session
- Only one mark is issued per incident, to the trainer who was active at end of day when the phase failed to close
- If inherited debt was present, no mark is issued regardless of whether the phase closed
- The downstream impact of an original trainer's failure (debt rolling into subsequent sessions) is recorded as context on the original mark's `debt_chain_context` field — not as additional marks

**Exemplary trainer flag:**
- Fires when a trainer closes inherited debt AND their own phase within the same dispatch session
- Also fires when a trainer consistently completes phases significantly ahead of shift end (early completion data point)

**Underperforming trainer flag:**
- Fires when a trainer has accumulated marks across 3 or more distinct trainees
- Does not count days where debt was inherited

### 4. Mid-Shift Trainer Handoff — Topic-Level Attribution

A new `TrainerCoverage` table records a row per topic per trainer at the moment a topic is marked complete. This replaces the implicit assumption that the trainer on the `TrainingRecord` covered all topics.

When Trainer A leaves mid-shift and Trainer B picks up, the coverage log shows exactly which topics each trainer covered and at what time. End-of-day attribution for mark purposes goes to whoever was the active trainer at midnight.

### 5. Submission Deadline and Management Flag

Training records must be submitted by **midnight** of the dispatch day. If not submitted:
- A Celery Beat task running at 00:01 AM flags the record to management
- The record is soft-locked (management can reopen it for late submission)
- Late submission is noted on the record but does not automatically trigger a trainer mark — management reviews and decides

Operational end of shift is 5:45 PM. The submission window from 5:45 PM to midnight is a grace period, not an extension.

### 6. Phase 4 — Structured Observation Checklist

Phase 4 is a field shadowing session, not classroom instruction. Its curriculum is auto-generated from all mandatory topics in Phases 1–3 as observation items (`record_type = "demonstration"`).

**Scoring:**
- Score = (mandatory observation items passed / total mandatory observation items) × 100
- Pass threshold: 90% AND all mandatory items must pass individually (no averaging over failures)
- Free-form `observation_notes` field for additional trainer commentary

**On fail:**
- Record flagged to management for review
- A Phase 5 remediation record is auto-generated
- Phase 5 curriculum is built only from the topics that failed in the Phase 4 observation — targeted remediation, not a full restart

### 7. Curriculum Content — 4-Phase Structure

The curriculum is seeded from the NYCD walker training form with the following phase assignment:

**Phase 1 — Orientation & Setup**
App setup (Discord, Amazon AZ, ADP payroll, Amazon Flex), ADP timekeeping compliance (clock in/out, timecard accuracy, Sunday night submission deadline, schedule removal consequences), attendance policy, contact information, Flex activation, bonus hours, NY State break law.

**Phase 2 — Delivery Standards**
Keys to Success (address/GeoPin verification, wrong GeoPin protocol, group stop label check, knock/ring procedure, direct-to-customer protocol, physical location delivery, unsecure location handling, no mailbox delivery, correct reason codes, POD photo requirements, NEVER household member), scorecard overview (DSB, POD, CDF, CC), DSB — simultaneous deliveries, DSB — household member rule.

**Phase 3 — Delivery Types & Edge Cases**
DSB — delivered >50m / Airplane mode / GeoPin wrong location, POD photo requirements and 8 defect types, POD bypass bucket flow, CDF trigger and DA-attributable categories, Contact Compliance standard workflow, Contact Compliance — no phone / disconnected / LAN line workflow, lockers, floor walk-up buildings, secure delivery location, bulk building drops.

**Phase 4 — Practical Shadowing**
Observation checklist auto-generated from all mandatory Phase 1–3 topics. Free-form notes. Scored pass/fail.

### 8. Early Completion Handling

Early completion (phase closed significantly before shift end) is a positive signal:
- Timestamped on the phase record (`phase_closed_at`)
- No system action required — trainer may optionally run a comprehension check and log the result
- No unlock of the next phase on the same calendar day — the next phase opens on the next dispatch day the DA is present (the phase gate check runs at `training_injection` time, which is dispatch publish time)

---

## Alternatives Considered

**Keep calendar-day gating** — Rejected. Early completion is expected on Phase 1 and creates false debt signals for all subsequent trainers.

**Two separate tables (TrainingCoverage + TrainingDemonstration)** — Rejected in favor of Option C (keep TrainingTask for trainee-side, add TrainerCoverage as a lightweight companion). Avoids duplicating debt tracking infrastructure while cleanly separating trainer accountability from trainee progress.

**Single mark accumulation per debt chain** — Selected. Only the trainer who originated the debt chain receives a mark. Downstream trainers who fail to close their phase due to inherited debt are not penalized, but the chain's impact is documented as context.

---

## Consequences

**Positive:**
- Debt system no longer produces false positives for early completion
- Trainer accountability is now auditable at the topic level
- Phase 4 produces a quantitative pass/fail score with targeted remediation
- Mid-shift handoffs are fully traceable
- Trainer performance analytics (underperforming, exemplary) are data-driven

**Negative:**
- Requires schema additions: `TrainerCoverage`, `TrainerMark` (new tables); `TrainingRecord` gains 7 new columns; `TrainingTask` gains 3 new columns; `TrainingCurriculum` gains 2 new columns
- `training_injection.py` requires significant rework of phase advancement logic
- Existing `TrainingRecord` rows have no `phase_closed`, `submitted_at`, or `score` — migration sets them to null (nullable columns)
- The 5-day cap in `training_injection.py` (line 104) must be changed to 4 phases + Phase 5 remediation path

---

## Schema Summary

### New columns on `TrainingCurriculum`
- `category` — String(50): `app_setup | policy | delivery_standards | delivery_types | scorecard | observation`
- `record_type` — String(20): `coverage | demonstration`

### New columns on `TrainingRecord`
- `submitted_at` — DateTime(timezone=True), nullable
- `phase_closed` — Boolean, default False
- `phase_closed_at` — DateTime(timezone=True), nullable
- `passed` — Boolean, nullable (null until Phase 4 submitted)
- `score` — Float, nullable (Phase 4 only)
- `observation_notes` — Text, nullable (Phase 4 free-form)
- `extended` — Boolean, default False (true if Phase 4 failed and Phase 5 generated)

### New columns on `TrainingTask`
- `record_type` — String(20): `coverage | demonstration`
- `completed_late` — Boolean, default False
- `completed_late_at` — DateTime(timezone=True), nullable

### New table: `trainer_coverage`
- `id` — UUID PK
- `training_record_id` — FK to `training_records`
- `trainer_id` — FK to `employees`
- `curriculum_item_id` — FK to `training_curriculums`
- `topic_title` — String(255) snapshot
- `covered_at` — DateTime(timezone=True)

### New table: `trainer_marks`
- `id` — UUID PK
- `trainer_id` — FK to `employees`
- `training_record_id` — FK to `training_records`
- `trainee_id` — FK to `employees`
- `reason` — String(50): `phase_not_closed | submitted_late`
- `debt_originated` — Boolean (true = this mark started a debt chain)
- `debt_chain_context` — Text, nullable
- `created_at` — DateTime(timezone=True)

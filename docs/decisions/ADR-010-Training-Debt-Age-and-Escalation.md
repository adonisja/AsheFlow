# ADR-010 — Training Debt Age Tracking and Manager Escalation

**Date:** 2026-04-10  
**Status:** Accepted  
**Author:** adonisja

---

## Context

The training injection system creates `TrainingTask` rows for each trainee on
every dispatch day. Mandatory tasks left incomplete at end-of-day roll forward
into the next record as "training debt." The original implementation had no
mechanism to:

1. Track how long a specific debt had been outstanding across dispatch days
2. Surface chronic unresolved debts to managers for intervention

Without this, a trainee could accumulate debt indefinitely with no accountability
and no visibility outside of manually reviewing individual training records.

---

## Decision Drivers

1. **Non-punitive by default.** Trainees should not be blocked from dispatch or
   day progression for missing tasks — field conditions vary and trainers
   sometimes fail to check off completed work. Blocking is too blunt an instrument
   without first understanding the failure pattern.

2. **Human review loop for chronic cases.** Systematic debt (same task missed 3+
   times) is a signal worth escalating. A manager decision — not an automated
   policy — is the right response.

3. **Low implementation cost.** The fix should not require a curriculum redesign,
   a new DB table, or changes to the progression model.

4. **UI-legible.** The severity of debt should be readable at a glance by
   trainers and managers without requiring them to compute ages manually.

---

## Options Considered

### Option A: Day progression lock

Block `current_day_number` advancement while any mandatory debt exists. The
trainee repeats the same day until all mandatory tasks are cleared.

**Rejected.** Penalizes trainees for trainer failures (unchecked tasks, absent
trainers). Creates operational friction on days when a task genuinely could not
be completed due to field conditions. Deferring to Option A after real data
exists on debt frequency is preferable to deploying it preemptively.

### Option B: Mandatory vs. recommended debt split

Two tiers: `mandatory` (blocks progression) and `recommended` (ages and warns
but never blocks). Curriculum items get assigned a tier.

**Rejected for now.** Requires curriculum design decisions before we have data
on which tasks are actually problematic. Can be layered on top of this decision
later as Option A + tier awareness if needed.

### Option C: Debt age counter + escalation flag (chosen)

Track `debt_age` (increments each rollover) and `is_escalated` (set when age
hits threshold) on each `TrainingTask`. No progression change. Expose an
escalation endpoint for managers.

**Accepted.** Satisfies all four decision drivers. Composable — Options A and B
can be built on top of this without removing it.

---

## Decision

Add `debt_age` (Integer) and `is_escalated` (Boolean) to `TrainingTask`.

- `debt_age` starts at 0 for all non-debt tasks. Increments by 1 each time a
  task rolls over as debt into a new `TrainingRecord`.
- `is_escalated` is set to `True` automatically when `debt_age >= DEBT_ESCALATION_THRESHOLD`.
- `DEBT_ESCALATION_THRESHOLD = 3` — a task must survive 3 dispatch days
  unresolved before escalating. Configurable via `constants.py`.

Add `GET /training/escalated` (management/admin only) that returns all trainees
with at least one unresolved escalated task, sorted by severity (most escalated
tasks first, oldest debt surfaced first within each trainee).

Expose `debt_age` and `is_escalated` on all `TrainingTaskResponse` payloads so
trainer and trainee views can render age-aware UI badges.

---

## Consequences

**Positive:**
- Managers have a single endpoint to identify trainees needing intervention
- Trainers see debt age on every task, creating natural accountability without
  blocking dispatch
- No progression model changes — existing trainee flow is unaffected
- Threshold is a constant, easy to tune based on operational experience

**Negative:**
- Escalation is informational only — a manager must act on it. If managers
  don't check the escalation view, the flag is silent.
- `debt_age` only counts dispatch days, not calendar days. A trainee dispatched
  infrequently could have a 3-day-old debt that spans weeks of calendar time.
  This is the correct behavior (age = number of opportunities missed) but may
  be surprising without UI clarification.

---

## Threshold Rationale

`DEBT_ESCALATION_THRESHOLD = 3` was chosen because:

- Day 1 debt: likely a field condition or oversight — no action needed
- Day 2 debt: pattern forming — trainer should be aware (yellow UI)
- Day 3 debt: systematic failure — manager should be in the loop (escalation)

This maps naturally to the 5-day training cycle: by day 3 of debt, the trainee
is at risk of completing the cycle without ever clearing the task.

---

## Future Considerations

- **Option A (day lock):** Layer on top of this once real debt frequency data
  exists. A trainee with `debt_age >= 5` and `is_escalated == True` would be
  a reasonable candidate for a day lock after manager review.
- **Manager resolution workflow:** Add a `POST /training/escalated/{task_id}/resolve`
  endpoint allowing managers to excuse a task (mark resolved without completing)
  and record a reason. This closes the loop on the escalation.
- **UI badge rendering:** `debt_age == 1` → neutral, `debt_age == 2` → yellow
  warning, `is_escalated == True` → red. Trainer dashboard should show an
  aggregate escalation count badge.

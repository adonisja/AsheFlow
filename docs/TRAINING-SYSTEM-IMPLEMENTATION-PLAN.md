# Training System — Phase-Based Redesign Implementation Plan
**Date:** 2026-04-22  
**ADR:** ADR-046  
**Status:** Ready for implementation — all design questions resolved

---

## Overview

This plan implements the phase-based training curriculum redesign. It replaces the calendar-day model with a phase-gate model, adds trainer accountability (marks, coverage tracking), restructures Phase 4 as a scored observation session, and seeds the 4-phase curriculum from the NYCD walker training content.

Work is sequenced: migration → models → services → tasks → routers → frontend. Each step has clear inputs and outputs. Do not skip ahead — later steps depend on earlier schema being in place.

---

## Step 1 — Alembic Migration

**File:** `backend/alembic/versions/<hash>_training_system_phase_redesign.py`

### Columns to add to `training_curriculums`
```sql
ALTER TABLE training_curriculums ADD COLUMN category VARCHAR(50);
ALTER TABLE training_curriculums ADD COLUMN record_type VARCHAR(20) DEFAULT 'coverage';
```

### Columns to add to `training_records`
```sql
ALTER TABLE training_records ADD COLUMN submitted_at TIMESTAMPTZ;
ALTER TABLE training_records ADD COLUMN phase_closed BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE training_records ADD COLUMN phase_closed_at TIMESTAMPTZ;
ALTER TABLE training_records ADD COLUMN passed BOOLEAN;
ALTER TABLE training_records ADD COLUMN score FLOAT;
ALTER TABLE training_records ADD COLUMN observation_notes TEXT;
ALTER TABLE training_records ADD COLUMN extended BOOLEAN NOT NULL DEFAULT FALSE;
```

### Columns to add to `training_tasks`
```sql
ALTER TABLE training_tasks ADD COLUMN record_type VARCHAR(20) DEFAULT 'coverage';
ALTER TABLE training_tasks ADD COLUMN completed_late BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE training_tasks ADD COLUMN completed_late_at TIMESTAMPTZ;
```

### New table: `trainer_coverage`
```sql
CREATE TABLE trainer_coverage (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    training_record_id UUID NOT NULL REFERENCES training_records(id) ON DELETE CASCADE,
    trainer_id UUID NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    curriculum_item_id UUID REFERENCES training_curriculums(id) ON DELETE SET NULL,
    topic_title VARCHAR(255) NOT NULL,
    covered_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_trainer_coverage_training_record_id ON trainer_coverage(training_record_id);
CREATE INDEX ix_trainer_coverage_trainer_id ON trainer_coverage(trainer_id);
```

### New table: `trainer_marks`
```sql
CREATE TABLE trainer_marks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trainer_id UUID NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    training_record_id UUID NOT NULL REFERENCES training_records(id) ON DELETE CASCADE,
    trainee_id UUID NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    reason VARCHAR(50) NOT NULL,  -- phase_not_closed | submitted_late
    debt_originated BOOLEAN NOT NULL DEFAULT FALSE,
    debt_chain_context TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_trainer_marks_trainer_id ON trainer_marks(trainer_id);
```

### Existing data
All new columns are nullable or have safe defaults. Existing `training_records` rows get `phase_closed = FALSE`, `extended = FALSE`. No data loss.

### Update curriculum day cap in `training_injection.py`
After migration, update line 104 from `current_day = 5` to `current_day = 4`.

---

## Step 2 — Model Updates

### `backend/app/models/training.py`

Add to `TrainingCurriculum`:
```python
category    = Column(String(50), nullable=True)   # app_setup|policy|delivery_standards|delivery_types|scorecard|observation
record_type = Column(String(20), nullable=False, default="coverage")  # coverage|demonstration
```

Add to `TrainingRecord`:
```python
submitted_at      = Column(DateTime(timezone=True), nullable=True)
phase_closed      = Column(Boolean, nullable=False, default=False)
phase_closed_at   = Column(DateTime(timezone=True), nullable=True)
passed            = Column(Boolean, nullable=True)   # null until Phase 4 submitted
score             = Column(Float, nullable=True)     # Phase 4 only
observation_notes = Column(Text, nullable=True)      # Phase 4 free-form
extended          = Column(Boolean, nullable=False, default=False)
```

Add to `TrainingTask`:
```python
record_type       = Column(String(20), nullable=False, default="coverage")
completed_late    = Column(Boolean, nullable=False, default=False)
completed_late_at = Column(DateTime(timezone=True), nullable=True)
```

### `backend/app/models/trainer_coverage.py` (new)
```python
class TrainerCoverage(Base):
    __tablename__ = "trainer_coverage"
    id                 = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    training_record_id = Column(UUID(as_uuid=True), ForeignKey("training_records.id", ondelete="CASCADE"), nullable=False, index=True)
    trainer_id         = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    curriculum_item_id = Column(UUID(as_uuid=True), ForeignKey("training_curriculums.id", ondelete="SET NULL"), nullable=True)
    topic_title        = Column(String(255), nullable=False)
    covered_at         = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
```

### `backend/app/models/trainer_mark.py` (new)
```python
class TrainerMark(Base):
    __tablename__ = "trainer_marks"
    id                 = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trainer_id         = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    training_record_id = Column(UUID(as_uuid=True), ForeignKey("training_records.id", ondelete="CASCADE"), nullable=False)
    trainee_id         = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    reason             = Column(String(50), nullable=False)  # phase_not_closed | submitted_late
    debt_originated    = Column(Boolean, nullable=False, default=False)
    debt_chain_context = Column(Text, nullable=True)
    created_at         = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
```

Register both new models in `backend/app/models/__init__.py`.

---

## Step 3 — Service: Phase Gate (`check_phase_gate.py`)

**File:** `backend/app/services/check_phase_gate.py`

**Purpose:** Before a trainer can mark a Phase N+1 topic complete, verify all mandatory Phase N tasks on this DA's current record are complete.

**Logic:**
```
def check_phase_gate(db, trainee_id, target_phase) -> tuple[bool, list[str]]:
    # Get current open TrainingRecord for this trainee
    # Query TrainingTask where training_record_id = record.id
    #   AND is_mandatory = True
    #   AND is_completed = False
    #   AND record_type = 'coverage'  (not observation items)
    #   AND is_training_debt = False  (debt items are tracked separately)
    # If any exist: return False, [list of blocking topic titles]
    # If none: return True, []
```

**Called by:** The task completion endpoint in `training.py` router before writing `is_completed = True`.

---

## Step 4 — Service: Record Trainer Mark (`record_trainer_mark.py`)

**File:** `backend/app/services/record_trainer_mark.py`

**Purpose:** Issue a TrainerMark when a phase fails to close by midnight.

**Logic:**
```
def record_trainer_mark(db, training_record_id, reason) -> TrainerMark | None:
    record = get TrainingRecord by id
    
    # Check if any inherited debt tasks exist on this record
    has_inherited_debt = any task where is_training_debt = True on this record
    if has_inherited_debt:
        return None  # No mark — trainer was hampered by prior debt
    
    # Issue mark
    mark = TrainerMark(
        trainer_id = record.trainer_id,
        training_record_id = record.id,
        trainee_id = record.trainee_id,
        reason = reason,
        debt_originated = True,  # This trainer started a new debt chain
    )
    db.add(mark)
    db.commit()
    
    # Check underperforming threshold: marks across 3+ distinct trainees
    distinct_trainee_count = count distinct trainee_id in TrainerMark where trainer_id = record.trainer_id
    if distinct_trainee_count >= 3:
        fire_notification(management, "Underperforming trainer: {trainer.name}")
    
    return mark
```

---

## Step 5 — Service: Score Phase 4 (`score_phase4.py`)

**File:** `backend/app/services/score_phase4.py`

**Purpose:** Compute pass/fail score from completed Phase 4 observation tasks.

**Logic:**
```
def score_phase4(db, training_record_id) -> dict:
    tasks = all TrainingTask where training_record_id = id AND record_type = 'demonstration'
    mandatory = [t for t in tasks if t.is_mandatory]
    passed_mandatory = [t for t in mandatory if t.is_completed]
    
    score = len(passed_mandatory) / len(mandatory) * 100 if mandatory else 0
    all_mandatory_passed = len(passed_mandatory) == len(mandatory)
    passed = score >= 90.0 and all_mandatory_passed
    
    return {"score": score, "passed": passed, "failed_topics": [t.topic_title for t in mandatory if not t.is_completed]}
```

**On fail — generate Phase 5 remediation record:**
```
def generate_remediation_record(db, original_record, failed_topics):
    # Create new TrainingRecord with current_day_number = 5
    # Create TrainingTask for each failed_topic only
    # is_training_debt = False (this is a fresh targeted session, not debt)
    # Flag management via Notification
```

---

## Step 6 — Service: Update `training_injection.py`

**Changes required:**

1. **Phase advancement logic** — replace linear increment:
```python
# OLD
current_day = last_record.current_day_number + 1

# NEW
if last_record.phase_closed:
    current_day = last_record.current_day_number + 1
else:
    current_day = last_record.current_day_number  # DA stays in same phase
```

2. **Day cap** — change from 5 to 4 (Phase 5 is only generated by remediation):
```python
# OLD
if current_day > 5:
    current_day = 5

# NEW
if current_day > 4:
    return  # DA has completed all phases; no new record needed
```

3. **Phase 4 curriculum injection** — when `current_day == 4`, instead of fetching from `curriculum_by_day[4]`, query all mandatory topics from phases 1–3 and create them as `record_type = "demonstration"` tasks.

---

## Step 7 — Celery Beat: Midnight Deadline Task

**File:** `backend/app/tasks/training_deadlines.py`

**Task:** `check_training_submissions` — runs at 00:01 AM daily

**Logic:**
```python
@celery_app.task
def check_training_submissions():
    yesterday = date.today() - timedelta(days=1)
    
    # Find records for yesterday that were not submitted
    unsubmitted = db.query(TrainingRecord).filter(
        TrainingRecord.record_date == yesterday,
        TrainingRecord.submitted_at == None,
        TrainingRecord.is_locked == False,
    ).all()
    
    for record in unsubmitted:
        # Check if DA was actually dispatched yesterday (avoid flagging non-dispatch days)
        was_dispatched = check_dispatch_assignment(db, record.trainee_id, yesterday)
        if not was_dispatched:
            continue
        
        # Soft-lock the record
        record.is_locked = True
        
        # Issue trainer mark if no inherited debt
        record_trainer_mark(db, record.id, reason="phase_not_closed")
        
        # Notify management
        db.add(Notification(
            employee_id=mgmt_id,
            type="training_record_unsubmitted",
            message=f"Training record for {trainee.name} (Phase {record.current_day_number}) not submitted by trainer {trainer.name}."
        ))
    
    db.commit()
```

Register in `backend/app/celery_app.py`:
```python
"check-training-submissions-nightly": {
    "task": "app.tasks.training_deadlines.check_training_submissions",
    "schedule": crontab(hour=0, minute=1),
}
```

---

## Step 8 — Curriculum Seed Data

**File:** `backend/scripts/seed_training_curriculum.py`

Seed all Phase 1–4 curriculum items. Run once after migration. Script should be idempotent (check for existing records before inserting).

### Phase 1 — Orientation & Setup (`app_setup`, `policy`, `coverage`)

| topic_title | category | is_mandatory |
|-------------|----------|--------------|
| Discord: tagging and how to use, assignment posting time (8:00–8:20 AM) | app_setup | True |
| Amazon AZ: schedule is sent out Thursday weekly | app_setup | True |
| ADP: payroll is submitted Monday weekly | app_setup | True |
| Amazon Flex: transportation settings (walker vs. driver) | app_setup | True |
| ADP: clock in/out using badge number | policy | True |
| ADP: all timecard edits submitted via ADP Mobile App or web portal only | policy | True |
| ADP: timecard must be 100% accurate and submitted by Sunday night | policy | True |
| ADP: review timecard daily for accuracy | policy | True |
| ADP: missing punches or incorrect times result in schedule removal | policy | True |
| ADP: use "Forgot username/password" immediately if credentials are lost | policy | True |
| Contact: Dispatch for delivery/route issues, hr@yourdsp.com for HR issues | policy | True |
| Attendance policy: 24-hour notice required for callout via email to HR | policy | True |
| Attendance policy: 2 no-call-no-shows = schedule removal, considered job abandonment | policy | True |
| Flex activation: request work block from Driver / Driver activates from station | policy | True |
| Bonus hours: discretionary based on performance and attendance | policy | True |
| Bonus hours: disqualifiers — attendance, leaving early, low package count, poor scorecard | policy | True |
| Shift time: 10:30 AM – 5:30 PM; mandatory 30-min unpaid lunch 1:00–1:30 PM | policy | True |
| NY State law: 30-min mandatory unpaid lunch when working 6+ hours (11 AM–2 PM in timecard) | policy | True |

### Phase 2 — Delivery Standards (`delivery_standards`, `scorecard`, `coverage`)

| topic_title | category | is_mandatory |
|-------------|----------|--------------|
| Keys to Success: always verify address and check the GeoPin before delivery | delivery_standards | True |
| Keys to Success: what to do when GeoPin is wrong | delivery_standards | True |
| Keys to Success: always check labels in a group stop — may be a package for another address | delivery_standards | True |
| Keys to Success: knock on door and ring bell to alert customer | delivery_standards | True |
| Keys to Success: direct-to-customer protocol — get name, enter in Flex, get signature if third party accepts | delivery_standards | True |
| Keys to Success: deliver to physical location — do not deliver beyond the GeoPin | delivery_standards | True |
| Keys to Success: unsecure location — call and text the customer to confirm | delivery_standards | True |
| Keys to Success: NEVER deliver to a customer's mailbox | delivery_standards | True |
| Keys to Success: scan delivered packages with correct reason codes | delivery_standards | True |
| Keys to Success: take a clear photo including surroundings as proof of delivery | delivery_standards | True |
| Keys to Success: NEVER mark "household member" | delivery_standards | True |
| Scorecard overview: DSB, POD, CDF, CC — what each metric is and why it matters | scorecard | True |
| DSB: simultaneous deliveries — what it means, when to use, when NOT to use | scorecard | True |
| DSB: delivered to household member — what it means, why it is not a valid delivery method, what to do instead | scorecard | True |

### Phase 3 — Delivery Types & Edge Cases (`delivery_types`, `scorecard`, `coverage`)

| topic_title | category | is_mandatory |
|-------------|----------|--------------|
| DSB: delivered >50 meters — GeoPin wrong location, what to do, Airplane mode and its function | scorecard | True |
| POD: photo requirements — no totes, no wheels/carts/racks, no humans, no up-close shots, adequate lighting | scorecard | True |
| POD: 8 primary photo defect types — blurry, too close, not clearly visible, no package, wrong orientation, vehicle in photo, too dark, package not present | scorecard | True |
| POD: bypass bucket flow — select "?" → Help → Unable to take photo → enter reason → Submit | scorecard | True |
| CDF: customer delivery notification trigger and DA-attributable positive/negative feedback categories | scorecard | True |
| Contact Compliance: NEVER close the "Having trouble?" prompt — call then text workflow | scorecard | True |
| Contact Compliance: no phone / disconnected / LAN line — contact driver support workflow | scorecard | True |
| Locker delivery: how to deliver and mark properly, common issues (full locker, broken locker) | delivery_types | True |
| Floor walk-up buildings: how to mark in Flex, when and how to contact customer, common issues, lobby dumping | delivery_types | True |
| Secure delivery location: how to mark a secure delivery location | delivery_types | True |
| Bulk building drops: doorman protocol, mailroom vs. receptionist, common issues, PODs for bulk drops | delivery_types | True |

### Phase 4 — Practical Shadowing (`observation`, `demonstration`)

Phase 4 tasks are **not seeded from the script**. They are auto-generated at dispatch time by `training_injection.py` from all mandatory Phase 1–3 curriculum items with `record_type = "demonstration"`. No static Phase 4 rows in `training_curriculums`.

---

## Step 9 — Router Updates

### `backend/app/routers/training.py`

- On `PATCH /training/tasks/{task_id}/complete`: call `check_phase_gate()` before writing completion; write `TrainerCoverage` row; check if all mandatory tasks are now complete → if yes, set `phase_closed = True`, `phase_closed_at = now()` on the record; check if trainer completed inherited debt + their own phase → if yes, fire exemplary trainer notification
- On `POST /training/records/{record_id}/submit`: set `submitted_at = now()`; if Phase 4, run `score_phase4()` and update `passed`, `score`; if fail, call `generate_remediation_record()`

### New: `backend/app/routers/trainer_marks.py`

- `GET /trainer-marks/` — management/admin: list all marks with trainer name, trainee name, date, reason
- `GET /trainer-marks/trainer/{trainer_id}` — management/admin: all marks for a specific trainer
- `GET /trainer-marks/summary` — management/admin: trainer mark counts, underperforming flag status

### New: `backend/app/routers/trainer_coverage.py`

- `GET /trainer-coverage/record/{record_id}` — management/admin/trainer: full topic-by-topic coverage log for a training record

---

## Step 10 — Frontend

### 10a — Training Curriculum Admin Page (new)

**Route:** `/admin/training-curriculum` (admin only)  
**Purpose:** View and edit the Phase 1–3 curriculum. Add topics, mark mandatory/optional, assign category.  
**Note:** Phase 4 items are auto-generated — this page should show a read-only preview of what Phase 4 will contain based on the current mandatory Phase 1–3 topics.

### 10b — Phase 4 Observation Checklist UI

**Route:** Part of existing trainer dashboard  
**Purpose:** Trainer working a Phase 4 session sees the observation checklist (auto-generated from mandatory Phase 1–3 topics), checks off each item as observed correctly, adds free-form notes, submits the record.  
**Score display:** Show computed score before final submission so trainer can see where the DA stands.

### 10c — Trainer Mark / Performance View (management)

**Route:** `/management/trainer-performance` or as a tab on the existing analytics section  
**Purpose:** List trainers with mark counts, exemplary flags, underperforming flags. Drilldown to per-trainer mark history with trainee, date, reason, and debt chain context.

### 10d — Training Record Submission Flow

Update the existing trainer training record UI to:
- Show phase gate status (which mandatory topics are still open before next phase unlocks)
- Add a "Submit Record" button that sets `submitted_at` and locks the record
- For Phase 4: show score after submit, show pass/fail result, show which topics failed (if any)

---

## Step 11 — Update LEARNING_GUIDE.md

Add a section for:
- Phase-based training gate logic (why calendar-day locking was rejected)
- Trainer mark attribution chain (why only one mark per incident)
- `TrainerCoverage` as audit trail for handoffs

---

## Execution Order Summary

| Step | What | Dependency |
|------|------|------------|
| 1 | Alembic migration | None — do first |
| 2 | Model updates | After Step 1 |
| 3 | `check_phase_gate` service | After Step 2 |
| 4 | `record_trainer_mark` service | After Step 2 |
| 5 | `score_phase4` service | After Step 2 |
| 6 | Update `training_injection.py` | After Steps 2, 3 |
| 7 | Celery Beat midnight task | After Steps 4, 6 |
| 8 | Seed curriculum data | After Step 1 (needs schema) |
| 9 | Router updates | After Steps 3, 4, 5 |
| 10 | Frontend | After Step 9 |
| 11 | LEARNING_GUIDE.md | After all above |

---

## What This Does NOT Change

- Continuation request system — already correct, no changes needed
- Trainee graduation logic (`graduate_trainees.py`) — unchanged
- Trainee assignment in dispatch (`assign_trainees.py`) — unchanged
- `TrainerContinuationRequest` model — unchanged
- All existing training record endpoints not listed above — unchanged

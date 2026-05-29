"""
Tests for training_injection.inject_curriculum.

HOW inject_curriculum WORKS (summary):
1. Collect all (trainee_id, trainer_id) pairs from today's assigned_crews.
2. Lock any past TrainingRecords that are still open (is_locked=False, date < target).
3. Resolve continuation requests: if the preferred trainer is available, swap them in.
   Nullify accepted and pending continuation requests.
4. For each trainee, determine current_phase:
   - No prior records → Phase 1.
   - Last record phase_closed=True → advance to next phase.
   - Last record phase_closed=False → stay in same phase.
   - Phase 4 closed → training complete, skip (no new record).
5. Create a new TrainingRecord for today.
6. Roll over uncompleted mandatory coverage tasks from all prior records as debt.
   Deduplicate by topic_title; increment debt_age; escalate if age >= threshold.
7. Add tasks for current phase:
   - Phase 4: generate "demonstration" tasks from all mandatory Phase 1–3 curriculum items.
   - Phase 1–3: add "coverage" tasks from curriculum for that phase;
     skip topics already in debt.
8. db.commit().

COVERAGE:
- No trainees in crews → no records created (early return)
- First-ever dispatch day → Phase 1 record created
- Phase closed → next phase record created
- Phase not closed → same phase record created
- Phase 4 closed (training complete) → no new record
- Curriculum tasks added for the correct phase
- Phase 4 creates demonstration tasks from mandatory Phase 1–3 items
- Debt rollover from prior uncompleted mandatory tasks
- Debt deduplicated by topic_title across multiple prior records
- Debt age incremented correctly
- Debt escalated when debt_age >= threshold
- Tasks already in debt are not duplicated in the phase curriculum
- Continuation request: preferred trainer swapped in when available
- Continuation request: preferred trainer absent → original trainer kept
- Continuation request: nullified after resolution
- Pending continuation request: nullified regardless
- Past open records locked before creating today's record
- Existing record for today: trainer_id updated, no duplicate record
- Non-mandatory curriculum items included for Phase 1–3
- db.commit called (records persist)
"""

import uuid
from datetime import date, timedelta

import pytest

from app.services.training_injection import inject_curriculum
from app.models.training import TrainingRecord, TrainingTask, TrainingCurriculum
from app.models.trainer_continuation_request import TrainerContinuationRequest
from tests.conftest import (
    SEED_COMPANY_ID,
    make_employee,
    make_curriculum,
    make_training_record,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_crews(trainee, trainer, truck_id=None):
    """Build a minimal assigned_crews dict for inject_curriculum."""
    tid = truck_id or str(uuid.uuid4())
    return {
        tid: [
            {"id": trainer.id, "role": "trainer"},
            {"id": trainee.id, "role": "trainee", "paired_trainer_id": trainer.id},
        ]
    }


def _records_for(db, trainee) -> list:
    return (
        db.query(TrainingRecord)
        .filter(TrainingRecord.trainee_id == trainee.id)
        .order_by(TrainingRecord.record_date)
        .all()
    )


def _tasks_for_record(db, record) -> list:
    return db.query(TrainingTask).filter(TrainingTask.training_record_id == record.id).all()


# ---------------------------------------------------------------------------
# Early-return: no trainees in crews
# ---------------------------------------------------------------------------

class TestNoTrainees:
    def test_no_trainees_creates_no_records(self, db):
        """
        ARRANGE: crews contain only a driver — no trainees.
        ASSERT: zero TrainingRecord rows created.
        """
        driver = make_employee(db, role="driver")
        crews = {str(uuid.uuid4()): [{"id": driver.id, "role": "driver"}]}

        inject_curriculum(db, target_date=date.today(), assigned_crews=crews, company_id=SEED_COMPANY_ID)

        assert db.query(TrainingRecord).count() == 0

    def test_empty_crews_creates_no_records(self, db):
        inject_curriculum(db, target_date=date.today(), assigned_crews={}, company_id=SEED_COMPANY_ID)
        assert db.query(TrainingRecord).count() == 0


# ---------------------------------------------------------------------------
# Phase advancement
# ---------------------------------------------------------------------------

class TestPhaseAdvancement:
    def test_first_day_creates_phase_1_record(self, db):
        """
        ARRANGE: trainee with no prior records dispatched for the first time.
        ASSERT: TrainingRecord created with current_day_number=1.
        """
        trainee = make_employee(db, role="trainee")
        trainer = make_employee(db, role="trainer")
        make_curriculum(db, day_number=1, topic_title="Day 1 Topic")

        inject_curriculum(db, target_date=date.today(), assigned_crews=_build_crews(trainee, trainer), company_id=SEED_COMPANY_ID)

        records = _records_for(db, trainee)
        assert len(records) == 1
        assert records[0].current_day_number == 1

    def test_phase_closed_advances_to_next_phase(self, db):
        """
        ARRANGE: trainee's last record was Phase 1, phase_closed=True.
        ASSERT: today's record is Phase 2.
        """
        trainee = make_employee(db, role="trainee")
        trainer = make_employee(db, role="trainer")
        yesterday = date.today() - timedelta(days=1)
        make_training_record(db, trainee, trainer, record_date=yesterday, phase=1, phase_closed=True)
        make_curriculum(db, day_number=2, topic_title="Day 2 Topic")

        inject_curriculum(db, target_date=date.today(), assigned_crews=_build_crews(trainee, trainer), company_id=SEED_COMPANY_ID)

        records = _records_for(db, trainee)
        today_record = next(r for r in records if r.record_date == date.today())
        assert today_record.current_day_number == 2

    def test_phase_not_closed_stays_in_same_phase(self, db):
        """
        ARRANGE: trainee's last record was Phase 2, phase_closed=False.
        ASSERT: today's record is also Phase 2.
        """
        trainee = make_employee(db, role="trainee")
        trainer = make_employee(db, role="trainer")
        yesterday = date.today() - timedelta(days=1)
        make_training_record(db, trainee, trainer, record_date=yesterday, phase=2, phase_closed=False)
        make_curriculum(db, day_number=2, topic_title="Day 2 Topic")

        inject_curriculum(db, target_date=date.today(), assigned_crews=_build_crews(trainee, trainer), company_id=SEED_COMPANY_ID)

        records = _records_for(db, trainee)
        today_record = next(r for r in records if r.record_date == date.today())
        assert today_record.current_day_number == 2

    def test_phase_4_closed_skips_new_record(self, db):
        """
        ARRANGE: trainee completed Phase 4 (phase_closed=True).
        ASSERT: no new TrainingRecord created today — training is complete.
        """
        trainee = make_employee(db, role="trainee")
        trainer = make_employee(db, role="trainer")
        yesterday = date.today() - timedelta(days=1)
        make_training_record(db, trainee, trainer, record_date=yesterday, phase=4, phase_closed=True)

        inject_curriculum(db, target_date=date.today(), assigned_crews=_build_crews(trainee, trainer), company_id=SEED_COMPANY_ID)

        records = _records_for(db, trainee)
        assert all(r.record_date != date.today() for r in records), (
            "No record should be created after Phase 4 is closed"
        )


# ---------------------------------------------------------------------------
# Curriculum task injection
# ---------------------------------------------------------------------------

class TestCurriculumTasks:
    def test_phase_1_tasks_created_from_curriculum(self, db):
        """
        ARRANGE: 2 Phase 1 curriculum items. First dispatch day.
        ASSERT: 2 coverage tasks created for today's record.
        """
        trainee = make_employee(db, role="trainee")
        trainer = make_employee(db, role="trainer")
        make_curriculum(db, day_number=1, topic_title="Topic A")
        make_curriculum(db, day_number=1, topic_title="Topic B")

        inject_curriculum(db, target_date=date.today(), assigned_crews=_build_crews(trainee, trainer), company_id=SEED_COMPANY_ID)

        records = _records_for(db, trainee)
        tasks = _tasks_for_record(db, records[0])
        coverage_tasks = [t for t in tasks if t.record_type == "coverage" and not t.is_training_debt]
        assert len(coverage_tasks) == 2
        titles = {t.topic_title for t in coverage_tasks}
        assert titles == {"Topic A", "Topic B"}

    def test_phase_4_creates_demonstration_tasks(self, db):
        """
        ARRANGE: trainee in Phase 4. Mandatory Phase 1-3 curriculum items exist.
        ASSERT: today's record has demonstration tasks, not coverage tasks.
        """
        trainee = make_employee(db, role="trainee")
        trainer = make_employee(db, role="trainer")
        yesterday = date.today() - timedelta(days=1)
        make_training_record(db, trainee, trainer, record_date=yesterday, phase=3, phase_closed=True)
        make_curriculum(db, day_number=1, topic_title="Phase 1 Mandatory", is_mandatory=True)
        make_curriculum(db, day_number=2, topic_title="Phase 2 Mandatory", is_mandatory=True)
        make_curriculum(db, day_number=3, topic_title="Phase 3 Mandatory", is_mandatory=True)
        make_curriculum(db, day_number=1, topic_title="Phase 1 Optional", is_mandatory=False)

        inject_curriculum(db, target_date=date.today(), assigned_crews=_build_crews(trainee, trainer), company_id=SEED_COMPANY_ID)

        records = _records_for(db, trainee)
        today_rec = next(r for r in records if r.record_date == date.today())
        assert today_rec.current_day_number == 4

        tasks = _tasks_for_record(db, today_rec)
        demo_tasks = [t for t in tasks if t.record_type == "demonstration"]
        coverage_tasks = [t for t in tasks if t.record_type == "coverage" and not t.is_training_debt]

        # Only mandatory Phase 1-3 items → 3 demo tasks (optional item excluded)
        assert len(demo_tasks) == 3
        assert len(coverage_tasks) == 0, "Phase 4 should not create coverage tasks"

    def test_non_mandatory_curriculum_items_included_in_phase_1_3(self, db):
        """
        Non-mandatory items are still included as coverage tasks in Phases 1–3.
        Only in Phase 4 demonstration are optionals excluded.
        """
        trainee = make_employee(db, role="trainee")
        trainer = make_employee(db, role="trainer")
        make_curriculum(db, day_number=1, topic_title="Mandatory", is_mandatory=True)
        make_curriculum(db, day_number=1, topic_title="Optional", is_mandatory=False)

        inject_curriculum(db, target_date=date.today(), assigned_crews=_build_crews(trainee, trainer), company_id=SEED_COMPANY_ID)

        records = _records_for(db, trainee)
        tasks = _tasks_for_record(db, records[0])
        titles = {t.topic_title for t in tasks if not t.is_training_debt}
        assert "Mandatory" in titles
        assert "Optional" in titles

    def test_no_curriculum_items_creates_record_with_no_tasks(self, db):
        """
        If no curriculum exists for the current phase, the record is still
        created but with zero tasks.
        """
        trainee = make_employee(db, role="trainee")
        trainer = make_employee(db, role="trainer")
        # No curriculum items added

        inject_curriculum(db, target_date=date.today(), assigned_crews=_build_crews(trainee, trainer), company_id=SEED_COMPANY_ID)

        records = _records_for(db, trainee)
        assert len(records) == 1
        tasks = _tasks_for_record(db, records[0])
        assert tasks == []


# ---------------------------------------------------------------------------
# Debt rollover
# ---------------------------------------------------------------------------

class TestDebtRollover:
    def test_uncompleted_mandatory_task_rolled_over_as_debt(self, db):
        """
        ARRANGE: prior record with 1 uncompleted mandatory coverage task.
        ASSERT: today's record has 1 debt task with is_training_debt=True.
        """
        trainee = make_employee(db, role="trainee")
        trainer = make_employee(db, role="trainer")
        yesterday = date.today() - timedelta(days=1)
        prev_record = make_training_record(
            db, trainee, trainer, record_date=yesterday, phase=1, phase_closed=False
        )
        # Add an uncompleted mandatory task to the prior record
        db.add(TrainingTask(
            id=uuid.uuid4(),
            company_id=SEED_COMPANY_ID,
            training_record_id=prev_record.id,
            topic_title="Debt Topic",
            is_mandatory=True,
            is_completed=False,
            is_training_debt=False,
            record_type="coverage",
            debt_age=0,
        ))
        db.commit()

        make_curriculum(db, day_number=1, topic_title="Other Topic")

        inject_curriculum(db, target_date=date.today(), assigned_crews=_build_crews(trainee, trainer), company_id=SEED_COMPANY_ID)

        records = _records_for(db, trainee)
        today_rec = next(r for r in records if r.record_date == date.today())
        tasks = _tasks_for_record(db, today_rec)
        debt_tasks = [t for t in tasks if t.is_training_debt]
        assert len(debt_tasks) == 1
        assert debt_tasks[0].topic_title == "Debt Topic"

    def test_debt_age_incremented(self, db):
        """
        ARRANGE: prior record with a debt task already at debt_age=1.
        ASSERT: rolled-over debt task has debt_age=2.
        """
        trainee = make_employee(db, role="trainee")
        trainer = make_employee(db, role="trainer")
        yesterday = date.today() - timedelta(days=1)
        prev_record = make_training_record(
            db, trainee, trainer, record_date=yesterday, phase=1, phase_closed=False
        )
        db.add(TrainingTask(
            id=uuid.uuid4(),
            company_id=SEED_COMPANY_ID,
            training_record_id=prev_record.id,
            topic_title="Aging Debt",
            is_mandatory=True,
            is_completed=False,
            is_training_debt=True,
            record_type="coverage",
            debt_age=1,
        ))
        db.commit()

        inject_curriculum(db, target_date=date.today(), assigned_crews=_build_crews(trainee, trainer), company_id=SEED_COMPANY_ID)

        records = _records_for(db, trainee)
        today_rec = next(r for r in records if r.record_date == date.today())
        debt = [t for t in _tasks_for_record(db, today_rec) if t.is_training_debt]
        assert debt[0].debt_age == 2

    def test_debt_escalated_at_threshold(self, db):
        """
        ARRANGE: debt task at debt_age=2 (threshold is 3, so new age=3 triggers escalation).
        ASSERT: rolled-over task has is_escalated=True.
        """
        trainee = make_employee(db, role="trainee")
        trainer = make_employee(db, role="trainer")
        yesterday = date.today() - timedelta(days=1)
        prev_record = make_training_record(
            db, trainee, trainer, record_date=yesterday, phase=1, phase_closed=False
        )
        db.add(TrainingTask(
            id=uuid.uuid4(),
            company_id=SEED_COMPANY_ID,
            training_record_id=prev_record.id,
            topic_title="Escalating Debt",
            is_mandatory=True,
            is_completed=False,
            is_training_debt=True,
            record_type="coverage",
            debt_age=2,  # new age will be 3, threshold is 3
        ))
        db.commit()

        inject_curriculum(db, target_date=date.today(), assigned_crews=_build_crews(trainee, trainer), company_id=SEED_COMPANY_ID)

        records = _records_for(db, trainee)
        today_rec = next(r for r in records if r.record_date == date.today())
        debt = [t for t in _tasks_for_record(db, today_rec) if t.is_training_debt]
        assert debt[0].is_escalated is True

    def test_debt_not_duplicated_in_curriculum_tasks(self, db):
        """
        ARRANGE: prior uncompleted task has same topic_title as a Phase 1 curriculum item.
        ASSERT: today's record has exactly 1 task with that title (debt, not duplicated
        by the regular curriculum injection).
        """
        trainee = make_employee(db, role="trainee")
        trainer = make_employee(db, role="trainer")
        yesterday = date.today() - timedelta(days=1)
        prev_record = make_training_record(
            db, trainee, trainer, record_date=yesterday, phase=1, phase_closed=False
        )
        db.add(TrainingTask(
            id=uuid.uuid4(),
            company_id=SEED_COMPANY_ID,
            training_record_id=prev_record.id,
            topic_title="Shared Topic",
            is_mandatory=True,
            is_completed=False,
            is_training_debt=False,
            record_type="coverage",
            debt_age=0,
        ))
        db.commit()
        make_curriculum(db, day_number=1, topic_title="Shared Topic")  # same title

        inject_curriculum(db, target_date=date.today(), assigned_crews=_build_crews(trainee, trainer), company_id=SEED_COMPANY_ID)

        records = _records_for(db, trainee)
        today_rec = next(r for r in records if r.record_date == date.today())
        matching = [t for t in _tasks_for_record(db, today_rec) if t.topic_title == "Shared Topic"]
        assert len(matching) == 1, "Debt topic must not be duplicated by curriculum injection"
        assert matching[0].is_training_debt is True

    def test_completed_mandatory_task_not_rolled_over(self, db):
        """
        ARRANGE: prior record with 1 COMPLETED mandatory task.
        ASSERT: no debt task created for it today.
        """
        trainee = make_employee(db, role="trainee")
        trainer = make_employee(db, role="trainer")
        yesterday = date.today() - timedelta(days=1)
        prev_record = make_training_record(
            db, trainee, trainer, record_date=yesterday, phase=1, phase_closed=True
        )
        db.add(TrainingTask(
            id=uuid.uuid4(),
            company_id=SEED_COMPANY_ID,
            training_record_id=prev_record.id,
            topic_title="Done Topic",
            is_mandatory=True,
            is_completed=True,  # already done
            is_training_debt=False,
            record_type="coverage",
            debt_age=0,
        ))
        db.commit()
        make_curriculum(db, day_number=2, topic_title="Phase 2 Topic")

        inject_curriculum(db, target_date=date.today(), assigned_crews=_build_crews(trainee, trainer), company_id=SEED_COMPANY_ID)

        records = _records_for(db, trainee)
        today_rec = next(r for r in records if r.record_date == date.today())
        debt = [t for t in _tasks_for_record(db, today_rec) if t.is_training_debt]
        assert debt == [], "Completed tasks must not roll over as debt"

    def test_debt_deduplicated_across_multiple_prior_records(self, db):
        """
        ARRANGE: same topic_title appears uncompleted in two different prior records.
        ASSERT: only 1 debt task created (deduplication by topic_title).
        """
        trainee = make_employee(db, role="trainee")
        trainer = make_employee(db, role="trainer")
        two_days_ago = date.today() - timedelta(days=2)
        yesterday = date.today() - timedelta(days=1)

        for record_date in [two_days_ago, yesterday]:
            rec = make_training_record(
                db, trainee, trainer, record_date=record_date, phase=1, phase_closed=False
            )
            db.add(TrainingTask(
                id=uuid.uuid4(),
                company_id=SEED_COMPANY_ID,
                training_record_id=rec.id,
                topic_title="Duplicate Debt",
                is_mandatory=True,
                is_completed=False,
                is_training_debt=True,
                record_type="coverage",
                debt_age=0,
            ))
        db.commit()

        inject_curriculum(db, target_date=date.today(), assigned_crews=_build_crews(trainee, trainer), company_id=SEED_COMPANY_ID)

        records = _records_for(db, trainee)
        today_rec = next(r for r in records if r.record_date == date.today())
        debt = [t for t in _tasks_for_record(db, today_rec) if t.is_training_debt]
        titles = [t.topic_title for t in debt]
        assert titles.count("Duplicate Debt") == 1, "Same debt topic must not appear twice"


# ---------------------------------------------------------------------------
# Continuation requests
# ---------------------------------------------------------------------------

class TestContinuationRequests:
    def _make_continuation(self, db, trainee, trainer, status="accepted"):
        req = TrainerContinuationRequest(
            id=uuid.uuid4(),
            company_id=SEED_COMPANY_ID,
            trainee_id=trainee.id,
            trainer_id=trainer.id,
            status=status,
        )
        db.add(req)
        db.commit()
        db.refresh(req)
        return req

    def test_accepted_request_swaps_trainer_when_available(self, db):
        """
        ARRANGE: accepted continuation request for preferred_trainer.
        preferred_trainer is in today's crews on a different truck.
        ASSERT: today's record has trainer_id = preferred_trainer.id.
        """
        trainee  = make_employee(db, role="trainee")
        original = make_employee(db, role="trainer", name="Original Trainer")
        preferred = make_employee(db, role="trainer", name="Preferred Trainer")
        self._make_continuation(db, trainee, preferred, status="accepted")
        make_curriculum(db, day_number=1, topic_title="Topic")

        # Both trainers in crews, preferred on a different truck
        truck_a = str(uuid.uuid4())
        truck_b = str(uuid.uuid4())
        crews = {
            truck_a: [
                {"id": original.id,  "role": "trainer"},
                {"id": trainee.id,   "role": "trainee"},
            ],
            truck_b: [
                {"id": preferred.id, "role": "trainer"},
            ],
        }

        inject_curriculum(db, target_date=date.today(), assigned_crews=crews, company_id=SEED_COMPANY_ID)

        records = _records_for(db, trainee)
        today_rec = next(r for r in records if r.record_date == date.today())
        assert today_rec.trainer_id == preferred.id

    def test_accepted_request_not_swapped_when_trainer_absent(self, db):
        """
        ARRANGE: accepted continuation request for preferred_trainer, but
        preferred_trainer is NOT in today's crews.
        ASSERT: today's record keeps the original trainer.
        """
        trainee  = make_employee(db, role="trainee")
        original = make_employee(db, role="trainer", name="Original")
        preferred = make_employee(db, role="trainer", name="Absent Preferred")
        self._make_continuation(db, trainee, preferred, status="accepted")
        make_curriculum(db, day_number=1, topic_title="Topic")

        inject_curriculum(db, target_date=date.today(), assigned_crews=_build_crews(trainee, original), company_id=SEED_COMPANY_ID)

        records = _records_for(db, trainee)
        today_rec = next(r for r in records if r.record_date == date.today())
        assert today_rec.trainer_id == original.id

    def test_accepted_request_nullified_after_resolution(self, db):
        """After inject_curriculum runs, the accepted request must be nullified."""
        trainee  = make_employee(db, role="trainee")
        trainer  = make_employee(db, role="trainer")
        req = self._make_continuation(db, trainee, trainer, status="accepted")
        make_curriculum(db, day_number=1, topic_title="Topic")

        inject_curriculum(db, target_date=date.today(), assigned_crews=_build_crews(trainee, trainer), company_id=SEED_COMPANY_ID)

        db.refresh(req)
        assert req.status == "nullified"

    def test_pending_request_nullified(self, db):
        """Pending continuation requests are auto-expired during injection."""
        trainee = make_employee(db, role="trainee")
        trainer = make_employee(db, role="trainer")
        req = self._make_continuation(db, trainee, trainer, status="pending")
        make_curriculum(db, day_number=1, topic_title="Topic")

        inject_curriculum(db, target_date=date.today(), assigned_crews=_build_crews(trainee, trainer), company_id=SEED_COMPANY_ID)

        db.refresh(req)
        assert req.status == "nullified"


# ---------------------------------------------------------------------------
# Past record locking
# ---------------------------------------------------------------------------

class TestPastRecordLocking:
    def test_open_past_records_locked(self, db):
        """
        ARRANGE: trainee has an unlocked record from 2 days ago.
        ASSERT: after inject_curriculum, that record's is_locked=True.
        """
        trainee = make_employee(db, role="trainee")
        trainer = make_employee(db, role="trainer")
        two_days_ago = date.today() - timedelta(days=2)
        old_record = make_training_record(
            db, trainee, trainer, record_date=two_days_ago, phase=1, phase_closed=True
        )
        assert old_record.is_locked is False

        make_curriculum(db, day_number=2, topic_title="Phase 2 Topic")
        inject_curriculum(db, target_date=date.today(), assigned_crews=_build_crews(trainee, trainer), company_id=SEED_COMPANY_ID)

        db.refresh(old_record)
        assert old_record.is_locked is True


# ---------------------------------------------------------------------------
# Idempotency — existing record for today
# ---------------------------------------------------------------------------

class TestIdempotency:
    def test_existing_today_record_recreated_with_new_trainer(self, db):
        """
        ARRANGE: a record for today already exists with original_trainer.
        Inject again with a different trainer in crews.
        ASSERT: still only 1 record for today; new record has updated trainer_id.
        The old record is deleted and recreated — db.refresh(existing) would error.
        """
        trainee  = make_employee(db, role="trainee")
        original = make_employee(db, role="trainer", name="Original")
        updated  = make_employee(db, role="trainer", name="Updated")

        make_training_record(
            db, trainee, original, record_date=date.today(), phase=1, phase_closed=False
        )
        make_curriculum(db, day_number=1, topic_title="Topic")

        inject_curriculum(
            db, target_date=date.today(), assigned_crews=_build_crews(trainee, updated),
            company_id=SEED_COMPANY_ID,
        )

        records = _records_for(db, trainee)
        today_records = [r for r in records if r.record_date == date.today()]
        assert len(today_records) == 1, "Must not create a duplicate record for the same date"
        assert today_records[0].trainer_id == updated.id, "Recreated record must have the new trainer"


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

class TestPersistence:
    def test_records_committed_to_db(self, db):
        """
        Verify inject_curriculum calls db.commit() — records survive a fresh query.
        """
        trainee = make_employee(db, role="trainee")
        trainer = make_employee(db, role="trainer")
        make_curriculum(db, day_number=1, topic_title="Topic")

        inject_curriculum(db, target_date=date.today(), assigned_crews=_build_crews(trainee, trainer), company_id=SEED_COMPANY_ID)

        count = db.query(TrainingRecord).filter(
            TrainingRecord.trainee_id == trainee.id,
            TrainingRecord.record_date == date.today(),
        ).count()
        assert count == 1

    def test_multiple_trainees_each_get_a_record(self, db):
        """
        ARRANGE: 2 trainees on 2 different trucks.
        ASSERT: each gets their own TrainingRecord.
        """
        trainee_a = make_employee(db, role="trainee", name="Trainee A")
        trainee_b = make_employee(db, role="trainee", name="Trainee B")
        trainer_a = make_employee(db, role="trainer", name="Trainer A")
        trainer_b = make_employee(db, role="trainer", name="Trainer B")
        make_curriculum(db, day_number=1, topic_title="Topic")

        truck_a = str(uuid.uuid4())
        truck_b = str(uuid.uuid4())
        crews = {
            truck_a: [{"id": trainer_a.id, "role": "trainer"}, {"id": trainee_a.id, "role": "trainee"}],
            truck_b: [{"id": trainer_b.id, "role": "trainer"}, {"id": trainee_b.id, "role": "trainee"}],
        }

        inject_curriculum(db, target_date=date.today(), assigned_crews=crews, company_id=SEED_COMPANY_ID)

        assert len(_records_for(db, trainee_a)) == 1
        assert len(_records_for(db, trainee_b)) == 1

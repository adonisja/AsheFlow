"""ADR-263 — company and role scoping of dispatch-time curriculum injection.

Two failures this file pins:

1. ROLE LEAK (ADR-263). Without the roles filter a walker trainee receives
   driver vehicle-safety items, and the Phase 4 mirroring promotes them to
   MANDATORY demonstration tasks — a trainer asked to observe a walker
   performing a vehicle pre-trip inspection, blocking graduation until they do.

2. TENANT LEAK (Dimension 1). The curriculum read and the past-record lock were
   both unscoped before this change, so Company A's trainees were injected with
   Company B's curriculum topics. Fixed alongside the role filter.
"""
import uuid
from datetime import date, timedelta

import pytest

from app.services.training_injection import inject_curriculum
from app.models.training import TrainingRecord, TrainingTask
from tests.conftest import SEED_COMPANY_ID, make_employee, make_curriculum


def _crews(trainee, trainer):
    return {
        str(uuid.uuid4()): [
            {"id": trainer.id, "role": "trainer"},
            {"id": trainee.id, "role": "trainee", "paired_trainer_id": trainer.id},
        ]
    }


def _task_titles(db, trainee):
    rec = (
        db.query(TrainingRecord)
        .filter(TrainingRecord.trainee_id == trainee.id)
        .order_by(TrainingRecord.record_date.desc())
        .first()
    )
    assert rec is not None, "expected a training record to have been created"
    tasks = db.query(TrainingTask).filter(
        TrainingTask.training_record_id == rec.id
    ).all()
    return {t.topic_title for t in tasks}


class TestRoleScoping:
    def test_walker_trainee_does_not_receive_driver_items(self, db):
        """ARRANGE: one walker item and one driver item in the same phase.
        ASSERT: the trainee's tasks contain the walker item and NOT the driver one."""
        make_curriculum(db, 1, "Walker: read the delivery note", roles=["walker"])
        make_curriculum(db, 1, "Driver: pre-trip DVIC", roles=["driver"],
                        category="vehicle_safety")

        trainee = make_employee(db, role="trainee")
        trainer = make_employee(db, role="trainer")
        inject_curriculum(db, target_date=date.today(),
                          assigned_crews=_crews(trainee, trainer),
                          company_id=SEED_COMPANY_ID)

        titles = _task_titles(db, trainee)
        assert "Walker: read the delivery note" in titles
        assert "Driver: pre-trip DVIC" not in titles

    def test_shared_items_reach_the_walker_track(self, db):
        """A shared item is ONE row carrying both roles — it must still arrive."""
        make_curriculum(db, 1, "ADP: clock in/out using badge number",
                        roles=["walker", "driver"], category="policy")

        trainee = make_employee(db, role="trainee")
        trainer = make_employee(db, role="trainer")
        inject_curriculum(db, target_date=date.today(),
                          assigned_crews=_crews(trainee, trainer),
                          company_id=SEED_COMPANY_ID)

        assert "ADP: clock in/out using badge number" in _task_titles(db, trainee)

    def test_driver_items_do_not_reach_phase4_demonstrations(self, db):
        """The compounding failure: Phase 4 mirrors mandatory Phase 1-3 items into
        demonstrations. A leaked driver item becomes a MANDATORY task a trainer
        cannot complete for a walker, blocking graduation."""
        make_curriculum(db, 1, "Walker: cart staging", roles=["walker"])
        make_curriculum(db, 2, "Driver: reversing and spotter use", roles=["driver"],
                        category="vehicle_safety")

        trainee = make_employee(db, role="trainee")
        trainer = make_employee(db, role="trainer")

        # Walk the trainee to Phase 4 by closing each earlier phase.
        for day_offset in range(4):
            inject_curriculum(
                db,
                target_date=date.today() - timedelta(days=3 - day_offset),
                assigned_crews=_crews(trainee, trainer),
                company_id=SEED_COMPANY_ID,
            )
            rec = (
                db.query(TrainingRecord)
                .filter(TrainingRecord.trainee_id == trainee.id)
                .order_by(TrainingRecord.record_date.desc())
                .first()
            )
            rec.phase_closed = True
            db.commit()

        all_titles = {
            t.topic_title
            for t in db.query(TrainingTask)
            .join(TrainingRecord, TrainingTask.training_record_id == TrainingRecord.id)
            .filter(TrainingRecord.trainee_id == trainee.id)
            .all()
        }
        assert "Driver: reversing and spotter use" not in all_titles


class TestTenantScoping:
    def test_other_company_curriculum_is_not_injected(self, db):
        """Dimension 1. The curriculum read was unscoped before ADR-263 — Company
        A's trainees were handed Company B's topics."""
        other_company = uuid.uuid4()
        make_curriculum(db, 1, "OTHER CO: proprietary topic", roles=["walker"],
                        company_id=other_company)
        make_curriculum(db, 1, "OUR CO: correct topic", roles=["walker"])

        trainee = make_employee(db, role="trainee")
        trainer = make_employee(db, role="trainer")
        inject_curriculum(db, target_date=date.today(),
                          assigned_crews=_crews(trainee, trainer),
                          company_id=SEED_COMPANY_ID)

        titles = _task_titles(db, trainee)
        assert "OUR CO: correct topic" in titles
        assert "OTHER CO: proprietary topic" not in titles

    def test_past_record_lock_does_not_cross_tenants(self, db):
        """The is_locked sweep was also unscoped — it locked every tenant's open
        past records, not just the caller's."""
        from tests.conftest import make_training_record

        other_company = uuid.uuid4()
        other_trainee = make_employee(db, role="trainee")
        other_rec = make_training_record(
            db, other_trainee, other_trainee, date.today() - timedelta(days=2)
        )
        other_rec.company_id = other_company
        other_rec.is_locked = False
        db.commit()

        make_curriculum(db, 1, "Our topic", roles=["walker"])
        trainee = make_employee(db, role="trainee")
        trainer = make_employee(db, role="trainer")
        inject_curriculum(db, target_date=date.today(),
                          assigned_crews=_crews(trainee, trainer),
                          company_id=SEED_COMPANY_ID)

        db.refresh(other_rec)
        assert other_rec.is_locked is False, (
            "inject_curriculum locked another tenant's training record"
        )

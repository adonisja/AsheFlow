"""ADR-515: the nightly training-deadline check.

It raised UnboundLocalError on every night with nothing to check: `yesterday`
was assigned only inside the loop over unsubmitted records, and the summary read
it after the loop. Found when prod's beat caught up overdue jobs (ADR-514).
The task had no tests before this file.
"""
from datetime import timedelta
from unittest.mock import patch

import pytest

from app.models.notification import Notification
from app.models.training import TrainingRecord
from app.services.local_date import fetch_company_timezones, task_today
from app.tasks import training_deadlines as T
from tests.conftest import (
    SEED_COMPANY_ID, make_assignment, make_employee, make_member, make_training_record, make_truck,
)


@pytest.fixture
def run(db):
    """Run the task against the test session, without real delivery or marks."""
    def _run():
        with patch.object(T, "SessionLocal", return_value=db), \
             patch.object(T, "record_trainer_mark", return_value=None), \
             patch("app.services.notify._enqueue"):
            return T.check_training_submissions.run()
    return _run


@pytest.fixture
def yesterday(db):
    return task_today(fetch_company_timezones(db).get(SEED_COMPANY_ID)) - timedelta(days=1)


@pytest.fixture
def pair(db):
    trainee = make_employee(db, role="trainee", name="Tia Trainee")
    trainer = make_employee(db, role="trainer", name="Tom Trainer")
    make_employee(db, role="management", name="Mia Manager")
    return trainee, trainer


def test_a_night_with_nothing_to_check_returns_a_summary(db, run, yesterday):
    out = run()
    assert out["flagged"] == 0 and out["skipped_not_dispatched"] == 0
    assert str(yesterday) in out["dates_checked"]


def test_yesterdays_unsubmitted_record_is_locked_and_management_told(db, run, pair, yesterday):
    trainee, trainer = pair
    ta = make_assignment(db, make_truck(db, "Truck 4"), yesterday)
    make_member(db, ta, trainee, "trainee")
    db.commit()
    rid = make_training_record(db, trainee, trainer, yesterday).id   # the task closes its session
    out = run()
    assert out["flagged"] == 1
    assert db.get(TrainingRecord, rid).is_locked is True
    assert db.query(Notification).filter_by(type="training_record_unsubmitted").count() == 1


def test_a_trainee_who_was_not_dispatched_is_skipped(db, run, pair, yesterday):
    trainee, trainer = pair
    rid = make_training_record(db, trainee, trainer, yesterday).id   # the task closes its session
    out = run()
    assert (out["flagged"], out["skipped_not_dispatched"]) == (0, 1)
    assert db.get(TrainingRecord, rid).is_locked is False


def test_a_record_from_another_day_is_left_alone(db, run, pair, yesterday):
    trainee, trainer = pair
    rid = make_training_record(db, trainee, trainer, yesterday - timedelta(days=3)).id
    out = run()
    assert (out["flagged"], out["skipped_not_dispatched"]) == (0, 0)
    assert db.get(TrainingRecord, rid).is_locked is False

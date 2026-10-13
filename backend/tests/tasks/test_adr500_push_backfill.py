"""ADR-500 — devices with no SNS endpoint are repaired by an hourly sweep.

Against the suite's in-memory `db`, with the task pointed at it (the
test_adr379_invite_expiry pattern, and the ADR-494 lesson about tests that
follow the code to whatever DATABASE_URL says). `create_endpoint` is replaced:
these tests pin which rows the sweep picks and how it stops, not SNS itself.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.core.config import settings
from app.models.device_token import DeviceToken
from tests.conftest import make_employee, sqlite_mirror_with_defaults

ARN = "arn:aws:sns:us-east-2:000000000000:app/GCM/AsheFlow-Android-test"


@pytest.fixture
def sweep(db, monkeypatch):
    """The task, pointed at the test db, with Android enabled and iOS off."""
    from app.tasks import push_delivery_task as T
    sqlite_mirror_with_defaults(DeviceToken.__table__).create(db.get_bind(), checkfirst=True)
    monkeypatch.setattr(settings, "sns_fcm_platform_arn", ARN)
    monkeypatch.setattr(settings, "sns_apns_platform_arn", " ")   # parked: whitespace = off
    with patch("app.tasks.push_delivery_task.SessionLocal", return_value=db):
        yield T


def _device(db, emp, *, platform="android", endpoint=None, revoked=False, seen_ago_h=0):
    d = DeviceToken(
        id=uuid.uuid4(), company_id=emp.company_id, employee_id=emp.id,
        platform=platform, token=f"tok-{uuid.uuid4().hex}",
        endpoint_arn=endpoint,
        last_seen_at=datetime.now(timezone.utc) - timedelta(hours=seen_ago_h),
        revoked_at=datetime.now(timezone.utc) if revoked else None,
    )
    db.add(d); db.commit()
    return d.id


def _arn(db, device_id):
    db.expire_all()
    return db.query(DeviceToken.endpoint_arn).filter(DeviceToken.id == device_id).scalar()


def _ok(device):
    return f"{ARN.replace(':app/', ':endpoint/')}/{device.id}"


class TestWhichRowsItRepairs:
    def test_a_live_android_row_with_no_endpoint_gets_one(self, db, sweep):
        emp = make_employee(db)
        dev = _device(db, emp)
        with patch.object(sweep, "create_endpoint", side_effect=_ok):
            result = sweep.backfill_endpoints()
        assert result["created"] == 1 and result["remaining"] == 0
        assert _arn(db, dev) is not None

    def test_a_revoked_row_is_left_alone(self, db, sweep):
        emp = make_employee(db)
        dev = _device(db, emp, revoked=True)
        with patch.object(sweep, "create_endpoint", side_effect=_ok) as ce:
            sweep.backfill_endpoints()
        assert ce.call_count == 0, "a signed-out device must not be given an endpoint"
        assert _arn(db, dev) is None

    def test_a_disabled_platform_is_not_attempted(self, db, sweep):
        emp = make_employee(db)
        ios = _device(db, emp, platform="ios")
        with patch.object(sweep, "create_endpoint", side_effect=_ok) as ce:
            sweep.backfill_endpoints()
        assert ce.call_count == 0, (
            "iOS is parked (whitespace ARN): calling create_endpoint for it would "
            "only log 'disabled' every hour"
        )
        assert _arn(db, ios) is None

    def test_an_existing_endpoint_is_not_touched(self, db, sweep):
        emp = make_employee(db)
        _device(db, emp, endpoint="arn:existing")
        with patch.object(sweep, "create_endpoint", side_effect=_ok) as ce:
            sweep.backfill_endpoints()
        assert ce.call_count == 0

    def test_nothing_runs_when_push_is_off_everywhere(self, db, sweep, monkeypatch):
        monkeypatch.setattr(settings, "sns_fcm_platform_arn", "")
        emp = make_employee(db)
        _device(db, emp)
        with patch.object(sweep, "create_endpoint", side_effect=_ok) as ce:
            assert sweep.backfill_endpoints() == {"skipped": "push_not_configured"}
        assert ce.call_count == 0


class TestFailureHandling:
    def test_a_refusal_leaves_the_row_null_and_is_counted(self, db, sweep):
        emp = make_employee(db)
        dev = _device(db, emp)
        with patch.object(sweep, "create_endpoint", return_value=None):
            result = sweep.backfill_endpoints()
        assert result["failed"] == 1 and result["remaining"] == 1
        assert _arn(db, dev) is None, "a failed attempt must leave it for the next run"

    def test_it_stops_after_three_consecutive_refusals(self, db, sweep):
        emp = make_employee(db)
        for _ in range(6):
            _device(db, emp)
        with patch.object(sweep, "create_endpoint", return_value=None) as ce:
            result = sweep.backfill_endpoints()
        assert ce.call_count == 3, (
            "a broken credential fails every call; without the stop, one run "
            "issues the whole batch and buries the cause under its warnings"
        )
        assert result["stopped"] is True

    def test_one_bad_token_does_not_stop_the_batch(self, db, sweep):
        # THREE failures, never two in a row. The first version of this test had
        # only two failures in total, so it could not tell "consecutive" from
        # "total": the probe that removed the reset-on-success passed it.
        emp = make_employee(db)
        for _ in range(6):
            _device(db, emp)
        outcomes = iter([None, "a", None, "b", None, "c"])
        with patch.object(sweep, "create_endpoint", side_effect=lambda d: next(outcomes)) as ce:
            result = sweep.backfill_endpoints()
        assert ce.call_count == 6, "the count is CONSECUTIVE refusals, not total"
        assert result == {"created": 3, "failed": 3, "remaining": 3, "stopped": False}


class TestBatching:
    def test_the_batch_is_bounded(self, db, sweep, monkeypatch):
        monkeypatch.setattr(sweep, "_BACKFILL_BATCH", 2)
        emp = make_employee(db)
        for _ in range(5):
            _device(db, emp)
        with patch.object(sweep, "create_endpoint", side_effect=_ok) as ce:
            result = sweep.backfill_endpoints()
        assert ce.call_count == 2 and result["remaining"] == 3

    def test_most_recently_seen_goes_first(self, db, sweep, monkeypatch):
        monkeypatch.setattr(sweep, "_BACKFILL_BATCH", 1)
        emp = make_employee(db)
        stale = _device(db, emp, seen_ago_h=72)
        fresh = _device(db, emp, seen_ago_h=1)
        with patch.object(sweep, "create_endpoint", side_effect=_ok):
            sweep.backfill_endpoints()
        assert _arn(db, fresh) is not None and _arn(db, stale) is None


class TestItIsWiredAndTheCommentsAreTrue:
    def test_it_is_scheduled_hourly_at_minute_23(self):
        from app.celery_app import celery_app
        entry = celery_app.conf.beat_schedule["backfill-push-endpoints"]
        assert entry["task"] == "app.tasks.push_delivery_task.backfill_endpoints"
        assert entry["schedule"].minute == {23} and len(entry["schedule"].hour) == 24

    def test_the_name_the_code_promises_exists(self):
        """push_delivery.py and the register route both promise
        `backfill_endpoints`. For a release it named nothing (deep dive Part 7.1).
        If the task is renamed, this fails instead of the comment quietly lying."""
        import inspect
        from app.routers import notifications
        from app.services import push_delivery
        from app.tasks import push_delivery_task
        promised = "backfill_endpoints"
        assert promised in inspect.getsource(push_delivery)
        assert promised in inspect.getsource(notifications)
        assert hasattr(push_delivery_task, promised)

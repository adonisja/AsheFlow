"""Package exceptions (ADR-190): pre-route damage reporting + missing queue.

MagicMock DB session pattern (see test_persist_routes.py) — the endpoints are
plain functions; we intercept query/add/flush and inspect behavior. rts.py is
proprietary (AsheFlow-private), so CI skips cleanly when it's absent.
"""
import uuid
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.models.rts import DamagedPackage, MissingPackage
from app.routers.rts import (
    list_missing_queue, report_damaged_package, resolve_damaged_package,
)
from app.schemas.rts import DamagedPackageCreate, DamagedPackageResolveRequest

from fastapi import HTTPException

_COMPANY_ID = uuid.uuid4()


def _caller():
    c = MagicMock()
    c.id = uuid.uuid4()
    c.company_id = _COMPANY_ID
    c.name = "Dispatcher Dana"
    return c


def _create_body(**overrides):
    fields = dict(
        route_date=date(2026, 7, 9), tba_number="TBA111", stage="truck_load",
        damage_notes="crushed corner, contents exposed",
    )
    fields.update(overrides)
    return DamagedPackageCreate(**fields)


class TestReportDamaged:
    def _db(self, duplicate=None):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = duplicate
        added = {}
        db.add.side_effect = lambda obj: added.update(obj=obj)
        def fake_flush():
            o = added["obj"]
            o.id = uuid.uuid4()                              # DB-generated at flush
            o.reported_at = datetime.now(timezone.utc)       # server_default
            o.resolution_status = "open"                     # server_default
        db.flush.side_effect = fake_flush
        return db

    @patch("app.routers.rts.write_audit")
    @patch("app.routers.rts._resolve_address_from_redis", return_value="433 W 32 ST")
    def test_report_creates_open_record_with_reporter_stamp(self, _redis, audit):
        db = self._db()
        resp = report_damaged_package(_create_body(), caller=_caller(), _={}, db=db)
        assert resp.resolution_status == "open"
        assert resp.stage == "truck_load"
        assert resp.reported_by_name == "Dispatcher Dana"
        assert resp.normalised_address == "433 W 32 ST"
        assert audit.called                     # flush → audit → commit
        assert db.commit.called

    @patch("app.routers.rts.write_audit")
    @patch("app.routers.rts._resolve_address_from_redis", return_value=None)
    def test_duplicate_open_report_rejected_409(self, _redis, _audit):
        db = self._db(duplicate=MagicMock())    # existing open report for same tba+date
        with pytest.raises(HTTPException) as exc:
            report_damaged_package(_create_body(), caller=_caller(), _={}, db=db)
        assert exc.value.status_code == 409
        assert not db.add.called

    @patch("app.routers.rts.write_audit")
    @patch("app.routers.rts._resolve_address_from_redis", side_effect=RuntimeError("redis down"))
    def test_redis_failure_does_not_block_report(self, _redis, _audit):
        db = self._db()
        resp = report_damaged_package(_create_body(), caller=_caller(), _={}, db=db)
        assert resp.resolution_status == "open"
        assert resp.normalised_address is None   # address is best-effort only


class TestResolveDamaged:
    def _record(self, status="open"):
        return DamagedPackage(
            id=uuid.uuid4(), company_id=_COMPANY_ID, route_date=date(2026, 7, 9),
            tba_number="TBA111", stage="station_sort", damage_notes="torn open",
            resolution_status=status, reported_at=datetime.now(timezone.utc),
        )

    @patch("app.routers.rts.write_audit")
    def test_resolve_stamps_and_audits(self, audit):
        record = self._record()
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = record
        resp = resolve_damaged_package(
            record.id, DamagedPackageResolveRequest(resolution_notes="returned to Amazon"),
            caller=_caller(), _={}, db=db,
        )
        assert resp.resolution_status == "resolved"
        assert resp.resolution_notes == "returned to Amazon"
        assert resp.resolved_by_name == "Dispatcher Dana"
        assert audit.called

    def test_already_resolved_is_409_idempotency_guard(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = self._record("resolved")
        with pytest.raises(HTTPException) as exc:
            resolve_damaged_package(
                uuid.uuid4(), DamagedPackageResolveRequest(resolution_notes="again"),
                caller=_caller(), _={}, db=db,
            )
        assert exc.value.status_code == 409

    def test_not_found_404(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        with pytest.raises(HTTPException) as exc:
            resolve_damaged_package(
                uuid.uuid4(), DamagedPackageResolveRequest(resolution_notes="x"),
                caller=_caller(), _={}, db=db,
            )
        assert exc.value.status_code == 404


class TestMissingQueue:
    def test_queue_carries_route_context(self):
        m = MissingPackage(
            id=uuid.uuid4(), company_id=_COMPANY_ID, route_id=uuid.uuid4(),
            truck_assignment_id=uuid.uuid4(), tba_number="TBA222",
            reported_at=datetime.now(timezone.utc), resolution_status="unresolved",
        )
        chain = MagicMock()
        for meth in ("join", "filter", "order_by", "limit"):
            getattr(chain, meth).return_value = chain
        chain.all.return_value = [(m, 7, date(2026, 7, 9))]
        db = MagicMock()
        db.query.return_value = chain

        entries = list_missing_queue(caller=_caller(), _={}, db=db)
        assert len(entries) == 1
        assert entries[0].tba_number == "TBA222"
        assert entries[0].route_number == 7
        assert entries[0].route_date == date(2026, 7, 9)

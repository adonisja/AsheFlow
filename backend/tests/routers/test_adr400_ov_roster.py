"""ADR-400 A5a/A5c — the roster's OV half.

Behavioural: a real table, real rows, the real helper. The ordering rule is an
operator decision about how a driver walks a station, so it is pinned rather
than left to whatever the database returns.
"""
import datetime as dt
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.tote_address import ToteAddress
from app.models.workforce_ov import WorkforceOV
import app.routers.workforce_routes as W


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    WorkforceOV.__table__.create(engine)
    ToteAddress.__table__.create(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture()
def ctx():
    return uuid.uuid4(), uuid.uuid4(), dt.date.today()


def _ov(s, cid, tid, day, ov_id, zone=None, source="sheet", confirmed=None):
    s.add(WorkforceOV(company_id=cid, truck_id=tid, entry_date=day, ov_id=ov_id,
                      zone_label=zone, source=source, confirmed_at=confirmed))


class TestOrdering:
    def test_zone_then_id_not_mint_order(self, db, ctx):
        """A5a. The driver's task is spatial: clear B-27.2Y, then B-27.3X.

        Minted deliberately out of zone order — sorting by ov_id alone would
        give OV0001, OV0002, OV0003 and send the driver back and forth between
        shelves.
        """
        cid, tid, day = ctx
        _ov(db, cid, tid, day, "OV0001", "B-27.3X")
        _ov(db, cid, tid, day, "OV0002", "B-27.2Y")
        _ov(db, cid, tid, day, "OV0003", "B-27.2Y")
        db.commit()

        got = [o.ov_id for o in W._ovs_for_truck_day(db, cid, tid, day)]
        assert got == ["OV0002", "OV0003", "OV0001"], (
            "OVs are no longer grouped by zone — the driver walks the station "
            "twice (ADR-400 A5a)"
        )

    def test_a_zoneless_ov_sorts_last(self, db, ctx):
        """A milk-run item never had a station zone.

        It must not head the list the driver reads top-down at 06:00: those are
        the items that ARE on a shelf. An empty-string sort key would do exactly
        that, which is why the key is `(zone is None, zone or "", ov_id)`.
        """
        cid, tid, day = ctx
        _ov(db, cid, tid, day, "OV0001", None, source="milk_run")
        _ov(db, cid, tid, day, "OV0002", "B-27.2Y")
        db.commit()

        got = [o.ov_id for o in W._ovs_for_truck_day(db, cid, tid, day)]
        assert got == ["OV0002", "OV0001"]


class TestScoping:
    def test_another_trucks_ovs_are_not_returned(self, db, ctx):
        cid, tid, day = ctx
        other_truck = uuid.uuid4()
        _ov(db, cid, tid, day, "OV0001", "B-27.2Y")
        _ov(db, cid, other_truck, day, "OV0002", "B-27.2Y")
        db.commit()
        assert [o.ov_id for o in W._ovs_for_truck_day(db, cid, tid, day)] == ["OV0001"]

    def test_another_companys_ovs_are_not_returned(self, db, ctx):
        """Dim 1. Same truck id under a different company must not leak."""
        cid, tid, day = ctx
        _ov(db, cid, tid, day, "OV0001", "B-27.2Y")
        _ov(db, uuid.uuid4(), tid, day, "OV0002", "B-27.2Y")
        db.commit()
        assert [o.ov_id for o in W._ovs_for_truck_day(db, cid, tid, day)] == ["OV0001"]

    def test_yesterdays_ovs_are_not_returned(self, db, ctx):
        cid, tid, day = ctx
        _ov(db, cid, tid, day, "OV0001", "B-27.2Y")
        _ov(db, cid, tid, day - dt.timedelta(days=1), "OV0009", "B-27.2Y")
        db.commit()
        assert [o.ov_id for o in W._ovs_for_truck_day(db, cid, tid, day)] == ["OV0001"]


class TestAddressedFlag:
    def test_addressed_is_true_once_an_address_exists(self, db, ctx):
        """The roster shows what still needs work. `addressed` joins on bag_id,
        which is where an OV's id lives once the captain enters an address."""
        cid, tid, day = ctx
        _ov(db, cid, tid, day, "OV0001", "B-27.2Y")
        _ov(db, cid, tid, day, "OV0002", "B-27.2Y")
        db.add(ToteAddress(company_id=cid, truck_id=tid, entry_date=day,
                           bag_id="OV0001", raw_address="1 Main St", entry_sequence=1))
        db.commit()

        by_id = {o.ov_id: o for o in W._ovs_for_truck_day(db, cid, tid, day)}
        assert by_id["OV0001"].addressed is True
        assert by_id["OV0002"].addressed is False

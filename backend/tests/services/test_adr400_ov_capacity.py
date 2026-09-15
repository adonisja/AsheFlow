"""ADR-400 A2 step 5 — an OV costs what it occupies, not what a tote occupies.

An addressed OV already reached the sort: it has a ToteAddress row keyed by its
OV#### id, so the adapter grouped it as its own bag. What it lacked was a SIZE,
so the sort charged it a tote's flat 2 half-slots — wrong in both directions:

    XS   correct 0   was 2    (-2: routes end early, too many routes)
    S    correct 1   was 2    (-1)
    M    correct 2   was 2    ( 0: accidentally right)
    L    correct 3   was 2    (+1)
    XL   correct 4   was 2    (+2: the BFS overfills and a walker gets a cart
                               that does not physically hold the load)

Capacity is not merely recorded — ADR-400 A3 removed the commit-time REFUSAL,
not the planner. `route_sort.py:1182` breaks the BFS when the next tote would
exceed capacity, so a wrong cost changes how many routes a truck gets.
"""
import datetime as dt
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.btr_sheet import BTRBag, BTRSheet
from app.models.tote_address import ToteAddress
from app.models.workforce_ov import WorkforceOV
from app.schemas.walker_routes import OV_HALF_SLOTS, TOTE_HALF_SLOTS
from app.services.route_sort import _Tote, _pair_ovs
from app.services.workforce_sort_adapter import build_packages


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    for model in (ToteAddress, WorkforceOV, BTRSheet, BTRBag):
        model.__table__.create(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture()
def ctx():
    return uuid.uuid4(), uuid.uuid4(), dt.date.today()


def _add_ov(db, cid, tid, day, ov_id, size):
    db.add(WorkforceOV(company_id=cid, truck_id=tid, entry_date=day,
                       ov_id=ov_id, size=size, source="sheet"))
    db.add(ToteAddress(company_id=cid, truck_id=tid, entry_date=day, bag_id=ov_id,
                       raw_address="2 Main St", block_key="W_36_St_400",
                       entry_sequence=1))


def _cost(result) -> dict[str, int]:
    totes: dict[str, _Tote] = {}
    for p in result.packages:
        totes.setdefault(p.bag_id, _Tote(bag_id=p.bag_id)).packages.append(p)
    _pair_ovs(totes)
    return {bag: t.half_slot_cost for bag, t in totes.items()}


class TestSizeReachesTheSort:
    @pytest.mark.parametrize("size,expected", [
        ("XS", 0), ("S", 1), ("M", 2), ("L", 3), ("XL", 4),
    ])
    def test_each_size_costs_its_own_tier(self, db, ctx, size, expected):
        cid, tid, day = ctx
        _add_ov(db, cid, tid, day, "OV0001", size)
        db.commit()
        assert _cost(build_packages(db, cid, tid, day))["OV0001"] == expected

    def test_an_xs_costs_nothing_and_is_not_floored_to_one(self, db, ctx):
        """ADR-260: an envelope tossed into a tote occupies no cart slot.

        `_Tote.half_slot_cost` floors a standalone OV bag at 1 so a lone item
        does not ride free, and exempts all-XS bags from that floor. Losing the
        exemption charges half a slot for the thing defined as costing nothing.
        """
        cid, tid, day = ctx
        _add_ov(db, cid, tid, day, "OV0001", "XS")
        db.commit()
        assert _cost(build_packages(db, cid, tid, day))["OV0001"] == 0

    def test_a_tote_is_unaffected(self, db, ctx):
        """A captain enters geography, not contents, so a tote still gets no
        package_type and keeps its flat base cost."""
        cid, tid, day = ctx
        db.add(ToteAddress(company_id=cid, truck_id=tid, entry_date=day,
                           bag_id="6800", raw_address="1 Main St",
                           block_key="W_36_St_400", entry_sequence=1))
        db.commit()
        assert _cost(build_packages(db, cid, tid, day))["6800"] == TOTE_HALF_SLOTS


class TestDegradation:
    def test_an_unsized_ov_falls_back_to_a_totes_cost(self, db, ctx):
        """A seeded OV has no size until a captain addresses it, and a seeded-
        but-unaddressed OV never reaches the sort at all. This covers the
        remaining path: a row whose size is somehow absent must not crash and
        must not cost zero — silently free is worse than roughly right.
        """
        cid, tid, day = ctx
        _add_ov(db, cid, tid, day, "OV0001", None)
        db.commit()
        costs = _cost(build_packages(db, cid, tid, day))
        assert costs["OV0001"] == TOTE_HALF_SLOTS

    def test_another_companys_ov_sizes_do_not_leak(self, db, ctx):
        """Dim 1. The size lookup is a second query keyed by company-truck-day.

        Deliberately ANOTHER COMPANY, not another truck: `ov_id` is unique per
        (company, entry_date), so two trucks in one company can never share
        OV0001 and that scenario is unconstructible. A different tenant reusing
        the same id on the same date is both possible and the leak that matters
        — an unscoped lookup would size this company's OV from theirs.
        """
        cid, tid, day = ctx
        _add_ov(db, cid, tid, day, "OV0001", None)
        # SAME truck_id under a different company. Using a different truck too
        # would let the truck filter alone exclude the row, and the test would
        # pass with company_id deleted from the query — confirmed by mutation.
        # Only company_id can separate these two.
        db.add(WorkforceOV(company_id=uuid.uuid4(), truck_id=tid,
                           entry_date=day, ov_id="OV0001", size="XL", source="sheet"))
        db.commit()
        assert _cost(build_packages(db, cid, tid, day))["OV0001"] == TOTE_HALF_SLOTS, (
            "the OV took its size from another tenant's row"
        )

    def test_yesterdays_size_does_not_apply(self, db, ctx):
        """The same ov_id recurs on later days carrying different work — the
        daily reset guarantees it. Without entry_date in the lookup, today's
        OV0001 would inherit yesterday's size."""
        cid, tid, day = ctx
        _add_ov(db, cid, tid, day, "OV0001", None)
        db.add(WorkforceOV(company_id=cid, truck_id=tid,
                           entry_date=day - dt.timedelta(days=1),
                           ov_id="OV0001", size="XL", source="sheet"))
        db.commit()
        assert _cost(build_packages(db, cid, tid, day))["OV0001"] == TOTE_HALF_SLOTS


class TestTierTableAgreement:
    def test_sizes_and_half_slots_have_not_drifted(self):
        """The adapter builds `OV_{size}` strings that route_sort maps back
        through OV_HALF_SLOTS. A size with no tier contributes nothing and the
        route is under-costed."""
        from app.models.workforce_ov import OV_SIZES
        assert set(OV_SIZES) == set(OV_HALF_SLOTS)

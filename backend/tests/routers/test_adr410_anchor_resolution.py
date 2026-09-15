"""ADR-410 — resolving an uploaded BTR sheet to a truck by its anchor point.

The refusals are the load-bearing tests, as in ADR-290's suite:

  - the resolver must be scoped by company_id (dim 1). An anchor is unique
    within a company; two DSPs at one station can legitimately share one, and a
    cross-tenant match would file another company's sheet against our truck.
  - a miss must return None, never a nearest guess. A mis-resolved sheet
    attributes one truck's totes to another and nothing downstream flags it.
"""
import uuid

import pytest

from app.models.truck import Truck
from app.services.resolve_truck_anchor import resolve_truck_by_anchor
from tests.conftest import SEED_COMPANY_ID, make_truck

MORGAN = (40.76066, -73.99086)
TITAN  = (40.76061, -73.99126)   # 34 m from Morgan
VIKING = (40.76352, -73.99244)


def _register(db, name, lat, lng, *, company_id=SEED_COMPANY_ID, active=True):
    truck = make_truck(db, name=name)
    truck.company_id = company_id
    truck.is_active = active
    truck.amazon_anchor_lat = lat
    truck.amazon_anchor_lng = lng
    db.commit()
    db.refresh(truck)
    return truck


def test_resolves_the_registered_truck(db):
    morgan = _register(db, "Morgan", *MORGAN)
    assert resolve_truck_by_anchor(db, SEED_COMPANY_ID, *MORGAN).id == morgan.id


def test_the_34m_neighbour_is_not_returned(db):
    """Morgan and Titan are 34 m apart. A nearest-neighbour resolver would
    answer Morgan for Titan's sheet and file the wrong truck's totes."""
    _register(db, "Morgan", *MORGAN)
    titan = _register(db, "Titan", *TITAN)
    assert resolve_truck_by_anchor(db, SEED_COMPANY_ID, *TITAN).id == titan.id


def test_an_unregistered_anchor_returns_none_not_the_closest(db):
    """D6: a miss is a prompt to create a truck, never a guess."""
    _register(db, "Morgan", *MORGAN)
    assert resolve_truck_by_anchor(db, SEED_COMPANY_ID, *VIKING) is None


def test_another_companys_truck_is_never_matched(db):
    """Dimension 1. The anchor is registered, but to a different tenant."""
    other = uuid.uuid4()
    _register(db, "Foreign", *MORGAN, company_id=other)
    assert resolve_truck_by_anchor(db, SEED_COMPANY_ID, *MORGAN) is None


def test_an_inactive_truck_is_not_matched(db):
    """A retired truck keeps its row; its anchor must stop identifying it, or a
    sheet silently files against a vehicle that no longer runs."""
    _register(db, "Retired", *MORGAN, active=False)
    assert resolve_truck_by_anchor(db, SEED_COMPANY_ID, *MORGAN) is None


def test_a_missing_anchor_on_the_sheet_matches_nothing(db):
    """An unparsed Anchor Point cell must not match the trucks that also have
    none registered."""
    make_truck(db, name="Unregistered")
    assert resolve_truck_by_anchor(db, SEED_COMPANY_ID, None, None) is None


def test_float_noise_still_resolves(db):
    """Stored and parsed values both round to the 5dp key (D3)."""
    morgan = _register(db, "Morgan", *MORGAN)
    lat, lng = MORGAN
    got = resolve_truck_by_anchor(db, SEED_COMPANY_ID, lat + 1e-10, lng - 1e-10)
    assert got is not None and got.id == morgan.id


def test_an_unrounded_stored_anchor_still_resolves(db):
    """A row written outside the endpoint — a seed, a backfill, direct SQL — is
    not rounded to 5dp. It must still resolve, because the resolver compares
    rounded keys on both sides.

    This is also why the registration endpoint's clash check compares rounded
    keys rather than using SQL float equality: `== lat` would miss this row and
    happily register a SECOND truck at the same anchor, leaving both resolvable
    from one sheet.
    """
    truck = make_truck(db, name="Seeded")
    truck.amazon_anchor_lat = 40.760664        # rounds to 40.76066, but != it
    truck.amazon_anchor_lng = -73.990861       # rounds to -73.99086
    db.commit()

    assert truck.amazon_anchor_lat != 40.76066
    got = resolve_truck_by_anchor(db, SEED_COMPANY_ID, *MORGAN)
    assert got is not None and got.id == truck.id


def test_a_35m_neighbour_does_not_steal_a_claimed_anchor(db):
    """The real 2026-09-12 export, which is what D3 exists for.

    BTR29 arrived at 40.75608,-73.99634 — 35 m from Falcon — in the SAME workbook
    where BTR31 claimed Falcon's anchor exactly. So BTR29 is a different truck
    standing 35 m away, not Falcon having moved.

    35 m is TIGHTER than the registered fleet's own minimum separation (34.1 m,
    Morgan<->Titan). A nearest-neighbour resolver with any tolerance able to absorb
    GPS noise would have filed BTR29's totes onto Falcon, whose own sheet was in
    the same upload. Exact matching returns None, which routes it to the D6 offer.
    """
    falcon = _register(db, "Falcon", 40.75603, -73.99675)

    # Falcon's own sheet still resolves.
    assert resolve_truck_by_anchor(db, SEED_COMPANY_ID, 40.75603, -73.99675).id == falcon.id

    # The 35 m neighbour does not.
    assert resolve_truck_by_anchor(db, SEED_COMPANY_ID, 40.75608, -73.99634) is None

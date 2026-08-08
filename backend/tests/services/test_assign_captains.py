"""assign_captains — one captain per truck, familiarisation-steered (ADR-256).

assign_captains.py is proprietary → gitignored (syncs to private).

The invariant worth defending is that a captain lands on EXACTLY one truck and a
truck receives AT MOST one captain. Everything else — pins, familiarisation
weighting, ban handling — is a steering preference layered on top, and each is
tested for the direction it must NOT go as well as the one it should.
"""
import uuid
from datetime import date

import pytest

try:
    from app.services.assign_captains import assign_captains, _familiarisation_weights
    from app.models.captain_truck_familiarity import CaptainTruckFamiliarity
except ImportError:
    pytest.skip("proprietary dispatch deps not available (CI skip)", allow_module_level=True)

from tests.conftest import make_employee, make_truck, make_relationship, SEED_COMPANY_ID


def _crews(*truck_ids):
    return {tid: [] for tid in truck_ids}


def _captains_on(crews, truck_id):
    return [m for m in crews[truck_id] if m["role"] == "captain"]


class TestOnePerTruck:
    def test_each_captain_gets_one_truck(self, db):
        t1, t2 = make_truck(db, "T1"), make_truck(db, "T2")
        caps = [make_employee(db, role="captain", name=f"Cap {i}") for i in range(2)]
        crews = _crews(t1.id, t2.id)
        base = {t1.id: 1.0, t2.id: 1.0}

        assign_captains(caps, crews, base, db, company_id=SEED_COMPANY_ID)

        placed = [m for crew in crews.values() for m in crew if m["role"] == "captain"]
        assert len(placed) == 2
        assert len(_captains_on(crews, t1.id)) == 1
        assert len(_captains_on(crews, t2.id)) == 1

    def test_surplus_captains_are_left_unplaced(self, db):
        """Three captains, two trucks. The third is NOT doubled up onto a truck."""
        t1, t2 = make_truck(db, "T1"), make_truck(db, "T2")
        caps = [make_employee(db, role="captain", name=f"Cap {i}") for i in range(3)]
        crews = _crews(t1.id, t2.id)

        assign_captains(caps, crews, {t1.id: 1.0, t2.id: 1.0}, db, company_id=SEED_COMPANY_ID)

        placed = [m for crew in crews.values() for m in crew if m["role"] == "captain"]
        assert len(placed) == 2, "a third captain must not double up on a truck"

    def test_shortage_warns_and_leaves_truck_empty(self, db):
        t1, t2 = make_truck(db, "T1"), make_truck(db, "T2")
        cap = make_employee(db, role="captain", name="Only Cap")
        crews = _crews(t1.id, t2.id)

        warnings = assign_captains([cap], crews, {t1.id: 1.0, t2.id: 1.0}, db, company_id=SEED_COMPANY_ID)

        assert any(w.get("type") == "understaffed_captains" for w in warnings)
        placed = [m for crew in crews.values() for m in crew if m["role"] == "captain"]
        assert len(placed) == 1

    def test_no_captains_available_is_not_an_error(self, db):
        """ADR-256 D3 is warn-only; zero captains must still produce a dispatch."""
        t1 = make_truck(db, "T1")
        crews = _crews(t1.id)
        warnings = assign_captains([], crews, {t1.id: 1.0}, db, company_id=SEED_COMPANY_ID)
        assert crews[t1.id] == []
        assert warnings == []

    def test_does_not_take_a_truck_that_already_has_a_captain(self, db):
        """Manual assignment may have seated one before the algorithm runs."""
        t1, t2 = make_truck(db, "T1"), make_truck(db, "T2")
        existing = make_employee(db, role="captain", name="Already There")
        newcomer = make_employee(db, role="captain", name="Newcomer")
        crews = {t1.id: [{"id": existing.id, "role": "captain"}], t2.id: []}

        assign_captains([newcomer], crews, {t1.id: 1.0, t2.id: 1.0}, db, company_id=SEED_COMPANY_ID)

        assert len(_captains_on(crews, t1.id)) == 1
        assert _captains_on(crews, t2.id)[0]["id"] == newcomer.id


class TestFamiliarisationWeighting:
    """The penalty is INVERTED during familiarisation, not merely suspended.

    A captain mid-rotation must be pulled BACK to the truck they are learning. If
    this only disabled the penalty, they would drift to a random truck on day 2 and
    learn nothing — the failure the weights exist to prevent.
    """

    def test_current_truck_under_threshold_is_pulled_back(self):
        cap, t_learning, t_other = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        rows = {cap: {t_learning: _row(days_held=2, completed=False)}}
        w = _familiarisation_weights(cap, [t_learning, t_other], rows, rotation_days=5)
        assert w[t_learning] > w[t_other], "must be held on the truck being learned"

    def test_threshold_met_rotates_off(self):
        cap, t_done, t_new = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        rows = {cap: {t_done: _row(days_held=5, completed=False)}}
        w = _familiarisation_weights(cap, [t_done, t_new], rows, rotation_days=5)
        assert w[t_new] > w[t_done], "at threshold, push to an unvisited truck"

    def test_completed_truck_is_discouraged(self):
        cap, t_done, t_new = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        rows = {cap: {t_done: _row(days_held=5, completed=True)}}
        w = _familiarisation_weights(cap, [t_done, t_new], rows, rotation_days=5)
        assert w[t_new] > w[t_done]

    def test_unvisited_trucks_are_equal(self):
        cap, a, b = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        w = _familiarisation_weights(cap, [a, b], {}, rotation_days=5)
        assert w[a] == w[b], "no reason to prefer one unvisited truck over another"


class TestPinning:
    def test_pin_wins_over_everything(self, db):
        t1, t2 = make_truck(db, "T1"), make_truck(db, "T2")
        cap = make_employee(db, role="captain", name="Pinned Cap")
        db.add(CaptainTruckFamiliarity(
            id=uuid.uuid4(), company_id=SEED_COMPANY_ID, employee_id=cap.id,
            truck_id=t2.id, days_held=0, pinned=True,
        ))
        db.commit()

        assign_captains([cap], _c := _crews(t1.id, t2.id), {t1.id: 1.0, t2.id: 1.0},
                        db, company_id=SEED_COMPANY_ID)

        assert _captains_on(_c, t2.id), "pin must place the captain on the pinned truck"
        assert not _captains_on(_c, t1.id)

    def test_pinned_captain_is_placed_before_unpinned(self, db):
        """Otherwise an unpinned captain can take the seat the pin was holding."""
        t1, t2 = make_truck(db, "T1"), make_truck(db, "T2")
        pinned_cap = make_employee(db, role="captain", name="Pinned")
        free_cap = make_employee(db, role="captain", name="Free")
        db.add(CaptainTruckFamiliarity(
            id=uuid.uuid4(), company_id=SEED_COMPANY_ID, employee_id=pinned_cap.id,
            truck_id=t1.id, days_held=0, pinned=True,
        ))
        db.commit()

        crews = _crews(t1.id, t2.id)
        # free_cap first in the list — ordering must not depend on caller order
        assign_captains([free_cap, pinned_cap], crews, {t1.id: 1.0, t2.id: 1.0},
                        db, company_id=SEED_COMPANY_ID)

        assert _captains_on(crews, t1.id)[0]["id"] == pinned_cap.id


class TestBans:
    def test_captain_avoids_a_truck_whose_driver_bans_them(self, db):
        t1, t2 = make_truck(db, "T1"), make_truck(db, "T2")
        driver = make_employee(db, role="driver", name="Banning Driver")
        cap = make_employee(db, role="captain", name="Banned Cap")
        make_relationship(db, driver, cap, rel_type="ban")

        crews = {t1.id: [{"id": driver.id, "role": "driver"}], t2.id: []}
        assign_captains([cap], crews, {t1.id: 1.0, t2.id: 1.0}, db, company_id=SEED_COMPANY_ID)

        assert _captains_on(crews, t2.id), "captain should avoid the banning driver's truck"
        assert not _captains_on(crews, t1.id)

    def test_banned_everywhere_still_places_and_warns(self, db):
        """A ban is a preference; an empty captain seat is an operational gap.

        With only one truck and its driver banning the only captain, the captain is
        placed anyway — leaving the truck with no route lead would be worse — and
        the conflict is surfaced.
        """
        t1 = make_truck(db, "T1")
        driver = make_employee(db, role="driver", name="Banning Driver")
        cap = make_employee(db, role="captain", name="Banned Cap")
        make_relationship(db, driver, cap, rel_type="ban")

        crews = {t1.id: [{"id": driver.id, "role": "driver"}]}
        warnings = assign_captains([cap], crews, {t1.id: 1.0}, db, company_id=SEED_COMPANY_ID)

        assert _captains_on(crews, t1.id), "must not leave the truck captainless over a ban"
        assert any(w.get("type") == "captain_ban_conflict" for w in warnings)


def _row(*, days_held, completed):
    """Minimal stand-in for a CaptainTruckFamiliarity row."""
    from types import SimpleNamespace
    return SimpleNamespace(
        days_held=days_held,
        completed_at=date(2026, 1, 1) if completed else None,
        pinned=False,
    )

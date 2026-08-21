"""PATCH /dispatch/captains/{id}/pin — confirm before displacing (ADR-256 D17a).

dispatch.py is proprietary → gitignored (syncs to private).

A pin is exclusive in both directions, so repointing either side DISPLACES someone
else's pin. The design rule under test: that never happens silently. A conflict is
refused with a 409 that names it, and the caller re-sends with confirm_override to
proceed — the difference between "the system quietly changed something you did not
ask about" and "you were told, and chose".
"""
import uuid
from unittest.mock import patch

import pytest
from fastapi import HTTPException

try:
    from app.routers.dispatch import set_captain_pin
    from app.schemas.dispatch import CaptainPinUpdate
    from app.models.captain_truck_familiarity import CaptainTruckFamiliarity
except ImportError:
    pytest.skip("proprietary dispatch deps not available (CI skip)", allow_module_level=True)

from tests.conftest import make_employee, make_truck, SEED_COMPANY_ID


@pytest.fixture(autouse=True)
def _no_audit():
    """Stub write_audit for this module.

    AuditLog uses a JSONB column, which the SQLite test engine cannot compile — the
    same reason VehicleInspection is excluded from DISPATCH_TABLES. The audit write
    is not what these tests are about; the pin state is.
    """
    with patch("app.routers.dispatch.write_audit"):
        yield


def _caller(db):
    return make_employee(db, role="dispatch", name="Dispatcher")


def _pin(db, captain, truck):
    row = CaptainTruckFamiliarity(
        id=uuid.uuid4(), company_id=SEED_COMPANY_ID, employee_id=captain.id,
        truck_id=truck.id, days_held=0, pinned=True,
    )
    db.add(row)
    db.commit()
    return row


def _pinned_truck_ids(db, captain):
    return {
        r.truck_id for r in db.query(CaptainTruckFamiliarity).filter(
            CaptainTruckFamiliarity.employee_id == captain.id,
            CaptainTruckFamiliarity.pinned == True,  # noqa: E712
        ).all()
    }


class TestHappyPath:
    def test_pins_a_captain_to_a_free_truck(self, db):
        truck = make_truck(db, "Viking")
        cap = make_employee(db, role="captain", name="Cap")

        result = set_captain_pin(
            captain_id=cap.id, payload=CaptainPinUpdate(truck_id=truck.id),
            db=db, caller=_caller(db), _=None,
        )

        assert result["pinned_truck_id"] == str(truck.id)
        assert result["overrode"] is False
        assert _pinned_truck_ids(db, cap) == {truck.id}

    def test_clearing_a_pin_needs_no_confirmation(self, db):
        """Clearing removes nothing anyone else depends on."""
        truck = make_truck(db, "Viking")
        cap = make_employee(db, role="captain", name="Cap")
        _pin(db, cap, truck)

        result = set_captain_pin(
            captain_id=cap.id, payload=CaptainPinUpdate(truck_id=None),
            db=db, caller=_caller(db), _=None,
        )

        assert result["pinned_truck_id"] is None
        assert _pinned_truck_ids(db, cap) == set()

    def test_only_captains_can_be_pinned(self, db):
        truck = make_truck(db, "Viking")
        walker = make_employee(db, role="walker", name="Walker")

        with pytest.raises(HTTPException) as exc:
            set_captain_pin(
                captain_id=walker.id, payload=CaptainPinUpdate(truck_id=truck.id),
                db=db, caller=_caller(db), _=None,
            )
        assert exc.value.status_code == 400
        assert "not a captain" in exc.value.detail.lower()


class TestConfirmationRequired:
    def test_truck_already_pinned_to_someone_else_is_refused(self, db):
        truck = make_truck(db, "Viking")
        incumbent = make_employee(db, role="captain", name="Incumbent")
        newcomer = make_employee(db, role="captain", name="Newcomer")
        _pin(db, incumbent, truck)

        with pytest.raises(HTTPException) as exc:
            set_captain_pin(
                captain_id=newcomer.id, payload=CaptainPinUpdate(truck_id=truck.id),
                db=db, caller=_caller(db), _=None,
            )

        assert exc.value.status_code == 409
        assert "confirm_override" in exc.value.detail
        assert "Incumbent" in exc.value.detail, "the 409 must name who holds the pin"
        assert _pinned_truck_ids(db, incumbent) == {truck.id}, "refusal must not mutate"

    def test_captain_already_pinned_elsewhere_is_refused(self, db):
        t1, t2 = make_truck(db, "Viking"), make_truck(db, "Odin")
        cap = make_employee(db, role="captain", name="Cap")
        _pin(db, cap, t1)

        with pytest.raises(HTTPException) as exc:
            set_captain_pin(
                captain_id=cap.id, payload=CaptainPinUpdate(truck_id=t2.id),
                db=db, caller=_caller(db), _=None,
            )

        assert exc.value.status_code == 409
        assert "Viking" in exc.value.detail, "the 409 must name the existing pin"
        assert _pinned_truck_ids(db, cap) == {t1.id}

    def test_repinning_to_the_same_truck_is_not_a_conflict(self, db):
        """Re-sending an existing pin is idempotent, not a displacement."""
        truck = make_truck(db, "Viking")
        cap = make_employee(db, role="captain", name="Cap")
        _pin(db, cap, truck)

        result = set_captain_pin(
            captain_id=cap.id, payload=CaptainPinUpdate(truck_id=truck.id),
            db=db, caller=_caller(db), _=None,
        )
        assert result["overrode"] is False


class TestConfirmedOverride:
    def test_override_displaces_the_incumbent(self, db):
        truck = make_truck(db, "Viking")
        incumbent = make_employee(db, role="captain", name="Incumbent")
        newcomer = make_employee(db, role="captain", name="Newcomer")
        _pin(db, incumbent, truck)

        result = set_captain_pin(
            captain_id=newcomer.id,
            payload=CaptainPinUpdate(truck_id=truck.id, confirm_override=True,
                                     reason="Incumbent is on leave"),
            db=db, caller=_caller(db), _=None,
        )

        assert result["overrode"] is True
        assert _pinned_truck_ids(db, newcomer) == {truck.id}
        assert _pinned_truck_ids(db, incumbent) == set(), "incumbent must be unpinned"

    def test_override_moves_a_captain_between_trucks(self, db):
        t1, t2 = make_truck(db, "Viking"), make_truck(db, "Odin")
        cap = make_employee(db, role="captain", name="Cap")
        _pin(db, cap, t1)

        set_captain_pin(
            captain_id=cap.id,
            payload=CaptainPinUpdate(truck_id=t2.id, confirm_override=True),
            db=db, caller=_caller(db), _=None,
        )

        assert _pinned_truck_ids(db, cap) == {t2.id}, "exactly one pin survives"

    def test_displaced_row_keeps_its_familiarity_history(self, db):
        """Unpinned, not deleted — the day counter is real history."""
        truck = make_truck(db, "Viking")
        incumbent = make_employee(db, role="captain", name="Incumbent")
        newcomer = make_employee(db, role="captain", name="Newcomer")
        row = _pin(db, incumbent, truck)
        row.days_held = 4
        db.commit()

        set_captain_pin(
            captain_id=newcomer.id,
            payload=CaptainPinUpdate(truck_id=truck.id, confirm_override=True),
            db=db, caller=_caller(db), _=None,
        )

        kept = db.query(CaptainTruckFamiliarity).filter(
            CaptainTruckFamiliarity.employee_id == incumbent.id,
            CaptainTruckFamiliarity.truck_id == truck.id,
        ).first()
        assert kept is not None, "the row must survive, only its pin is cleared"
        assert kept.days_held == 4
        assert kept.pinned is False

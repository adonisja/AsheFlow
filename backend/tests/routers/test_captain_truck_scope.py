"""ADR-256 D11 — a captain's elevation is scoped to their OWN truck.

`rts.py` is proprietary → gitignored (syncs to private), hence the skip guard.

What this guards. The pre-ADR-256 check was a flat membership test:

    is_elevated = caller.role in ("trainer", "driver", "dispatch", "management", "admin")

with no truck condition anywhere in it. Adding "captain" to that tuple — the obvious
edit, and the one this ADR was written to prevent — grants every captain write access
to every truck's RTS in the company. The role gate passes (a captain IS a route lead),
so nothing downstream catches it.

The replacement, `_is_elevated_for_route`, splits elevation in two: station-side roles
stay unscoped; driver and captain must hold an AssignmentMember row on the route's own
truck. These tests pin both halves, because a helper that returns True for everyone
also satisfies "the captain can do their job".
"""
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

try:
    from app.routers.rts import _is_elevated_for_route
except ImportError:
    pytest.skip("proprietary rts deps not available (CI skip)", allow_module_level=True)

_CID = uuid.uuid4()
_OWN_TRUCK = uuid.uuid4()
_OTHER_TRUCK = uuid.uuid4()


def _caller(role):
    return SimpleNamespace(id=uuid.uuid4(), role=role, company_id=_CID)


def _route(truck_assignment_id):
    return SimpleNamespace(truck_assignment_id=truck_assignment_id, company_id=_CID)


def _db(member_found: bool):
    """Mock DB whose AssignmentMember lookup either finds a crew row or does not."""
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = (
        SimpleNamespace(id=uuid.uuid4()) if member_found else None
    )
    return db


class TestTruckScopedRolesAreScoped:
    @pytest.mark.parametrize("role", ["captain", "driver"])
    def test_elevated_on_own_truck(self, role):
        assert _is_elevated_for_route(_caller(role), _route(_OWN_TRUCK), _db(True)) is True

    @pytest.mark.parametrize("role", ["captain", "driver"])
    def test_not_elevated_on_another_truck(self, role):
        """The leak this ADR exists to prevent: no crew row on that truck → no elevation."""
        assert _is_elevated_for_route(_caller(role), _route(_OTHER_TRUCK), _db(False)) is False

    def test_the_truck_lookup_actually_runs(self):
        """A helper that never queries cannot be scoping anything."""
        db = _db(True)
        _is_elevated_for_route(_caller("captain"), _route(_OWN_TRUCK), db)
        assert db.query.called, "no AssignmentMember lookup — the scope check is not firing"


class TestStationRolesAreUnscoped:
    @pytest.mark.parametrize("role", ["dispatch", "management", "admin", "field_supervisor"])
    def test_elevated_regardless_of_truck(self, role):
        """Station-side and road-oversight roles see every truck — no crew row needed."""
        assert _is_elevated_for_route(_caller(role), _route(_OTHER_TRUCK), _db(False)) is True


class TestRolesWithoutElevation:
    @pytest.mark.parametrize("role", ["walker", "trainee"])
    def test_field_staff_are_not_elevated(self, role):
        assert _is_elevated_for_route(_caller(role), _route(_OWN_TRUCK), _db(True)) is False

    def test_trainer_is_not_elevated_even_on_their_own_truck(self):
        """ADR-256 D5: a trainer keeps training supervision, not route-lead authority.

        Being crewed on the truck is not enough — the DB lookup would succeed here,
        and the answer is still False.
        """
        assert _is_elevated_for_route(_caller("trainer"), _route(_OWN_TRUCK), _db(True)) is False

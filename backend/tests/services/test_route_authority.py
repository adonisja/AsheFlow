"""Capability checks for route authority (ADR-212).

route_authority is public (no proprietary imports) — the single source of
who-can-do-what on a route. Covers the three tiers over a participant set:
execute (any participant), supervise (supervisor only), read (participant or
scoped oversight/captain).
"""
import uuid
from types import SimpleNamespace

from app.services.route_authority import can_execute, can_supervise, can_read

_EXEC = uuid.uuid4()
_SUP = uuid.uuid4()
_STRANGER = uuid.uuid4()


def _emp(emp_id, role="walker"):
    return SimpleNamespace(id=emp_id, role=role)


def _route(participants):
    return SimpleNamespace(participants=participants)


def _paired_route():
    return _route([
        SimpleNamespace(role="executor", employee_id=_EXEC),
        SimpleNamespace(role="supervisor", employee_id=_SUP),
    ])


def _solo_route():
    return _route([SimpleNamespace(role="executor", employee_id=_EXEC)])


class TestCanExecute:
    def test_executor_can(self):
        assert can_execute(_emp(_EXEC, "trainee"), _paired_route()) is True

    def test_supervisor_can(self):
        # "either executes" — the supervising trainer may act on the route too.
        assert can_execute(_emp(_SUP, "trainer"), _paired_route()) is True

    def test_stranger_cannot(self):
        assert can_execute(_emp(_STRANGER, "walker"), _paired_route()) is False


class TestCanSupervise:
    def test_supervisor_can(self):
        assert can_supervise(_emp(_SUP, "trainer"), _paired_route()) is True

    def test_executor_cannot(self):
        # the trainee executing the route does NOT hold supervisory control
        assert can_supervise(_emp(_EXEC, "trainee"), _paired_route()) is False

    def test_solo_route_has_no_supervisor(self):
        assert can_supervise(_emp(_EXEC, "walker"), _solo_route()) is False


class TestCanRead:
    def test_oversight_role_always(self):
        assert can_read(_emp(_STRANGER, "dispatch"), _solo_route()) is True

    def test_captain_when_scoped(self):
        assert can_read(_emp(_STRANGER, "trainer"), _solo_route(), scoped_ok=True) is True

    def test_captain_not_scoped_and_not_participant(self):
        assert can_read(_emp(_STRANGER, "trainer"), _solo_route(), scoped_ok=False) is False

    def test_participant_can_read(self):
        assert can_read(_emp(_EXEC, "walker"), _solo_route()) is True

    def test_stranger_walker_cannot(self):
        assert can_read(_emp(_STRANGER, "walker"), _solo_route()) is False

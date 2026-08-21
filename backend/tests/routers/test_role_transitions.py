"""Field-role transitions — walker / trainer / captain (ADR-256).

The transition table is an ALLOW-list, so the tests assert both directions: every
legal move works, and the illegal ones are refused rather than silently permitted.
That matters more than usual here because `Employee.role` is what every role gate in
the application reads — an unintended transition is a privilege change.
"""
import uuid
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.routers.employees import (
    ROLE_TRANSITIONS, _apply_role_transition, _sync_discord_role_for_transition,
)
from app.models.captain_truck_familiarity import CaptainTruckFamiliarity
from tests.conftest import make_employee, make_truck, SEED_COMPANY_ID


@pytest.fixture(autouse=True)
def _no_side_effects():
    """Stub the external calls. write_audit writes JSONB, which SQLite cannot compile."""
    with patch("app.routers.employees.write_audit"), \
         patch("app.routers.employees._fire_discord_dm"), \
         patch("app.routers.employees._fire_role_sync"), \
         patch("app.routers.employees._cognito_client"):
        yield


def _caller(db):
    return make_employee(db, role="management", name="Manager")


class TestLegalTransitions:
    @pytest.mark.parametrize("old,new", [
        ("walker", "trainer"),
        ("walker", "captain"),
        ("trainer", "captain"),
        ("trainer", "walker"),
        ("captain", "trainer"),
        ("captain", "walker"),
    ])
    def test_every_declared_transition_works(self, db, old, new):
        emp = make_employee(db, role=old, name=f"{old} person")
        result = _apply_role_transition(db, emp, new, _caller(db))
        assert result.role == new


class TestIllegalTransitions:
    @pytest.mark.parametrize("old,new", [
        ("walker", "walker"),      # no-op is not a transition
        ("walker", "dispatch"),    # hiring decision, not a field promotion
        ("trainer", "admin"),      # privilege escalation
        ("captain", "driver"),     # driver is a separate track
        ("captain", "trainee"),    # cannot go back into training this way
    ])
    def test_undeclared_transitions_are_refused(self, db, old, new):
        emp = make_employee(db, role=old, name="Person")
        with pytest.raises(HTTPException) as exc:
            _apply_role_transition(db, emp, new, _caller(db))
        assert exc.value.status_code == 400
        assert emp.role == old, "a refused transition must not mutate the role"

    @pytest.mark.parametrize("role", ["driver", "dispatch", "management", "admin", "trainee"])
    def test_roles_outside_the_table_cannot_transition(self, db, role):
        """A role absent from ROLE_TRANSITIONS keys has no field-promotion path.

        Asserted explicitly because the failure of the opposite design — a deny-list —
        is silent: it admits every role added later.
        """
        emp = make_employee(db, role=role, name="Person")
        with pytest.raises(HTTPException) as exc:
            _apply_role_transition(db, emp, "captain", _caller(db))
        assert exc.value.status_code == 400
        assert emp.role == role

    def test_admin_is_not_reachable_from_any_field_role(self):
        """The escalation that would matter most, asserted against the table itself."""
        for old, targets in ROLE_TRANSITIONS.items():
            for privileged in ("admin", "management", "dispatch", "field_supervisor"):
                assert privileged not in targets, (
                    f"{old} -> {privileged} would be a privilege escalation"
                )


class TestCaptainPinsAreReleased:
    def test_demoting_a_captain_clears_their_pin(self, db):
        """A pin left behind steers assign_captains toward a non-captain, and holds
        the truck's pin slot against the partial unique index."""
        truck = make_truck(db, "Viking")
        cap = make_employee(db, role="captain", name="Cap")
        db.add(CaptainTruckFamiliarity(
            id=uuid.uuid4(), company_id=SEED_COMPANY_ID, employee_id=cap.id,
            truck_id=truck.id, days_held=3, pinned=True,
        ))
        db.commit()

        _apply_role_transition(db, cap, "walker", _caller(db))

        row = db.query(CaptainTruckFamiliarity).filter(
            CaptainTruckFamiliarity.employee_id == cap.id,
        ).first()
        assert row.pinned is False

    def test_familiarity_history_survives_demotion(self, db):
        """days_held is real history — it must survive a round trip out of the role."""
        truck = make_truck(db, "Viking")
        cap = make_employee(db, role="captain", name="Cap")
        db.add(CaptainTruckFamiliarity(
            id=uuid.uuid4(), company_id=SEED_COMPANY_ID, employee_id=cap.id,
            truck_id=truck.id, days_held=4, pinned=True,
        ))
        db.commit()

        _apply_role_transition(db, cap, "walker", _caller(db))
        _apply_role_transition(db, cap, "captain", _caller(db))

        row = db.query(CaptainTruckFamiliarity).filter(
            CaptainTruckFamiliarity.employee_id == cap.id,
        ).first()
        assert row is not None, "the row must not be deleted"
        assert row.days_held == 4, "familiarisation progress must not reset"
        assert row.pinned is False, "the pin does not come back on its own"


class TestDiscordRoleSync:
    """Trainer and captain are DIFFERENT guild roles (ADR-256).

    `role_captain` used to hold the trainer role, so sending the wrong action here
    would grant a trainer route-lead channel access.
    """

    def test_promotion_to_captain_grants_captain_not_trainer(self, db):
        emp = make_employee(db, role="walker", name="W")
        emp.discord_id = "123456789012345678"
        with patch("app.routers.employees._fire_role_sync") as sync:
            _sync_discord_role_for_transition(emp, "walker", "captain")
        actions = [c.args[2] for c in sync.call_args_list]
        assert actions == ["grant_captain"]

    def test_trainer_to_captain_revokes_trainer_and_grants_captain(self, db):
        emp = make_employee(db, role="captain", name="C")
        emp.discord_id = "123456789012345678"
        with patch("app.routers.employees._fire_role_sync") as sync:
            _sync_discord_role_for_transition(emp, "trainer", "captain")
        actions = [c.args[2] for c in sync.call_args_list]
        assert actions == ["revoke_trainer", "grant_captain"]

    def test_captain_to_walker_revokes_captain_only(self, db):
        emp = make_employee(db, role="walker", name="W")
        emp.discord_id = "123456789012345678"
        with patch("app.routers.employees._fire_role_sync") as sync:
            _sync_discord_role_for_transition(emp, "captain", "walker")
        actions = [c.args[2] for c in sync.call_args_list]
        assert actions == ["revoke_captain"]

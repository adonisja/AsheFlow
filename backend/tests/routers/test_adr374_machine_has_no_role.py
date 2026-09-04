"""A machine has no role, so privilege must be asked a different question (ADR-374).

The morning confirmations died on:

    File "/app/app/routers/dispatch.py", line 386, in get_daily_dispatch
    AttributeError: 'MachineCaller' object has no attribute 'role'

MachineCaller has no `role` deliberately (ADR-363) -- so that code assuming an
employee identity fails loudly rather than silently granting whatever a default
would imply. It worked. This is the bug it was built to expose: the ADR-364
cutover converted the GATES the bot calls but not the `caller.role` reads inside
the endpoint bodies.

`is_privileged` decides whether each crew member's discord_id is in the response,
so the one caller that most needs the privileged branch is the one that could not
answer the question.
"""
import uuid

import pytest
from fastapi import HTTPException

from app.api.deps import MachineCaller, RoleChecker
from app.routers.dispatch import ConfirmationIn, _is_privileged
from pydantic import ValidationError


def _machine(company_id=None):
    return MachineCaller(
        id="bot-client-id",
        company_id=company_id or uuid.uuid4(),
        name="asheflow.bot",
    )


class _Employee:
    def __init__(self, role):
        self.role = role
        self.id = uuid.uuid4()


class TestPrivilegeIsAskedAsAQuestion:
    def test_a_machine_is_privileged(self, db):
        """The bot needs discord_id to DM people -- that is the whole point."""
        assert _is_privileged(_machine()) is True

    def test_the_crash_is_gone(self, db):
        """`caller.role` on a MachineCaller raised AttributeError, not False."""
        m = _machine()
        with pytest.raises(AttributeError):
            _ = m.role                      # still true, and still deliberate
        assert _is_privileged(m) is True    # but the helper answers anyway

    @pytest.mark.parametrize("role", ["dispatch", "management", "admin"])
    def test_oversight_roles_are_privileged(self, role, db):
        assert _is_privileged(_Employee(role)) is True

    @pytest.mark.parametrize("role", ["walker", "trainer", "trainee", "driver"])
    def test_field_roles_are_not(self, role, db):
        """discord_id must not reach field staff -- this line is the only thing
        that was gating it before the endpoint got a RoleChecker."""
        assert _is_privileged(_Employee(role)) is False

    def test_machine_caller_still_has_no_role_attribute(self, db):
        """The tempting fix was `role: str = "dispatch"` on MachineCaller.

        Rejected: it makes every caller.role comparison silently succeed, which
        turns this class of bug from a loud 500 into a machine quietly holding
        whatever privilege the string implies.
        """
        assert not hasattr(_machine(), "role"), (
            "MachineCaller grew a `role` -- ADR-374 D4 rejected exactly that; "
            "the AttributeError is what found this bug in one traceback"
        )


class TestTheGatesThatMakeItSafe:
    """`_is_privileged` returns True for a machine BECAUSE the gate vetted it.

    Without a scoped gate, "no role" would mean "unknown principal, grant
    privilege" -- the silent wrong answer ADR-363 exists to prevent. These pin
    the gates rather than the helper.
    """

    def test_a_machine_without_the_scope_is_refused(self, db):
        gate = RoleChecker(["dispatch"], machine_scopes=["asheflow.bot/dispatch.read"])
        with pytest.raises(HTTPException) as exc:
            gate(user={"machine_scopes": {"asheflow.bot/something.else"}}, db=db)
        assert exc.value.status_code == 403

    def test_a_machine_is_refused_where_no_scope_is_declared(self, db):
        """An endpoint that did not opt in must not accept a machine at all."""
        gate = RoleChecker(["dispatch"])          # no machine_scopes
        with pytest.raises(HTTPException) as exc:
            gate(user={"machine_scopes": {"asheflow.bot/dispatch.read"}}, db=db)
        assert exc.value.status_code == 403
        assert "not available to machine clients" in exc.value.detail

    def test_a_machine_with_the_right_scope_passes(self, db):
        gate = RoleChecker(["dispatch"], machine_scopes=["asheflow.bot/dispatch.read"])
        out = gate(user={"machine_scopes": {"asheflow.bot/dispatch.read"}}, db=db)
        assert out is not None

    def test_the_board_endpoint_is_gated(self, db):
        """It had NO RoleChecker: any authenticated employee could read the
        whole board, with discord_id gated only by the line that was crashing."""
        import inspect
        from app.routers import dispatch as D

        src = inspect.getsource(D.get_daily_dispatch)
        assert "allow_dispatch_mgmt_bot_read" in src, (
            "GET /dispatch/{date} lost its gate -- a walker can read the board"
        )

    def test_the_confirmations_endpoint_is_gated(self, db):
        """Also had no gate, and get_caller_employee admits a machine on its own
        -- so _is_privileged would have granted confirm-for-anyone to any bot
        token. Field staff confirm here too, so the gate lists field roles."""
        import inspect
        from app.routers import dispatch as D

        src = inspect.getsource(D.record_confirmation)
        assert "allow_confirm_bot_write" in src, (
            "POST /dispatch/{date}/confirmations lost its gate -- _is_privileged "
            "is only safe behind one"
        )

    def test_the_confirm_gate_admits_field_staff_and_the_bot(self, db):
        from app.routers.dispatch import allow_confirm_bot_write as gate

        for role in ("walker", "trainer", "trainee", "driver", "captain"):
            assert role in gate.allowed_roles, (
                f"{role} confirms their own assignment here and must not be locked out"
            )
        assert "asheflow.bot/dispatch.write" in gate.machine_scopes


class TestTheConfirmationBodyIsTyped:
    """Was `payload: dict` -- Dimension 9 on a request body."""

    def test_an_unknown_key_is_rejected(self, db):
        with pytest.raises(ValidationError):
            ConfirmationIn(
                employee_id=uuid.uuid4(), status="confirmed", is_admin=True,
            )

    def test_an_invalid_status_is_rejected(self, db):
        with pytest.raises(ValidationError):
            ConfirmationIn(employee_id=uuid.uuid4(), status="maybe")

    def test_a_malformed_uuid_is_rejected(self, db):
        with pytest.raises(ValidationError):
            ConfirmationIn(employee_id="not-a-uuid", status="confirmed")

    def test_a_valid_body_parses(self, db):
        eid = uuid.uuid4()
        body = ConfirmationIn(employee_id=eid, status="declined")
        assert body.employee_id == eid and body.status == "declined"

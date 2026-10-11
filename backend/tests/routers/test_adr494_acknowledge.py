"""Who may acknowledge a notification, and what the record means (ADR-494 D7).

An acknowledgement is a FIRST-PERSON statement: this person chose this. The
properties below are the ones that make the row admissible as that, and each has
a specific way of silently becoming false.

Source- and AST-level, matching this suite's convention for gate and scoping
properties (see test_confirmation_history_scope.py): what must not regress is
the gate declaration and the scoping filters, and both are visible in the source.
"""
from __future__ import annotations

import ast
import inspect

from app.routers import notifications as N


def _ack_src() -> str:
    return inspect.getsource(N.acknowledge_notification)


class TestOnlyTheRecipientMayAcknowledge:
    """The property that makes the row mean anything.

    `mark_read` deliberately lets dispatch/management/admin mark someone else's
    notification read — reasonable for a render flag. It is NOT reasonable here:
    a manager recording that a walker "confirmed" their hours is precisely the
    forgery this table exists to make impossible, and for `timecard_mismatch`
    that record is what a payroll dispute six weeks later turns on.

    Admins have full access everywhere else in this app. This is a record of who
    clicked, so there is nothing for anyone else to do to it.
    """

    def test_it_requires_the_caller_to_own_the_notification(self):
        src = _ack_src()
        assert "notif.employee_id != caller.id" in src

    def test_it_has_no_oversight_override(self):
        """The inverse of mark_read, asserted explicitly.

        Copying mark_read's shape is the obvious mistake — it is the adjacent
        endpoint and it reads as the house pattern.
        """
        src = _ack_src()
        for role in ("dispatch", "management", "admin"):
            assert f'"{role}"' not in src, (
                f"acknowledge_notification mentions {role!r} — if an oversight "
                f"override was added, the row no longer proves the EMPLOYEE chose "
                f"anything, which is the only reason the table exists"
            )

    def test_it_records_the_caller_not_a_supplied_employee_id(self):
        """`employee_id` must come from the token, never the request.

        A body-supplied employee_id would let anyone file an acknowledgement in
        someone else's name while passing every other check here.
        """
        src = _ack_src()
        assert "employee_id=caller.id" in src

        sig = inspect.signature(N.acknowledge_notification)
        assert "employee_id" not in sig.parameters, (
            "the endpoint takes an employee_id — the caller can name someone else"
        )


class TestMultiTenancy:
    def test_the_notification_lookup_is_company_scoped(self):
        assert "Notification.company_id == caller.company_id" in _ack_src()

    def test_the_duplicate_check_is_company_scoped(self):
        """The inner existence check, which is where Dimension 1 findings hide.

        Unscoped, a notification_id from another tenant would report "already
        acknowledged" — leaking that the id exists at all.
        """
        assert "NotificationAcknowledgement.company_id == caller.company_id" in _ack_src()


class TestIdempotency:
    def test_a_second_acknowledgement_is_a_409(self):
        """First answer stands. Someone who confirmed then skipped has not
        un-confirmed, and a second row would make the column unreadable."""
        src = _ack_src()
        assert "HTTP_409_CONFLICT" in src

    def test_it_checks_before_inserting(self):
        """Order matters: the check must precede the add, or the PK raises an
        IntegrityError and the client gets a 500 for an ordinary double-tap."""
        src = _ack_src()
        assert src.index("HTTP_409_CONFLICT") < src.index("db.add(ack)")


class TestTheAuditSequence:
    """flush -> write_audit -> commit, in that order (CLAUDE.md, ADR-490).

    Parsed, not grepped: this function's docstring and comments both contain the
    word "commit", and a substring search matches the prose. That mistake has
    its own LEARNING_GUIDE entry and has been made more than fifteen times in
    this repo.
    """

    def test_flush_then_audit_then_commit(self):
        tree = ast.parse(inspect.getsource(N.acknowledge_notification).lstrip())
        order = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Attribute) and node.func.attr in ("flush", "commit"):
                order.append((node.lineno, node.func.attr))
            elif isinstance(node.func, ast.Name) and node.func.id == "write_audit":
                order.append((node.lineno, "write_audit"))
        seq = [name for _, name in sorted(order)]
        assert seq == ["flush", "write_audit", "commit"], (
            f"expected flush -> write_audit -> commit, got {seq}. An audit row "
            f"written after the commit is discarded on teardown (ADR-490)."
        )


class TestTheRoleGateCoversEveryRealRole:
    """A gate that misses a role makes the GATE it guards unanswerable.

    `allow_any_auth` sat unused in this router with a hand-typed list missing
    `captain`, `field_supervisor` and `driver_trainee`. Adopting it as written
    would have 403'd a captain trying to answer a `timecard_mismatch` gate —
    which has no exit but its own action, so the app would have been unusable
    for them with no way out.
    """

    def test_every_cognito_role_can_acknowledge(self):
        from app.routers.registration import ROLE_TO_COGNITO_GROUP

        missing = set(ROLE_TO_COGNITO_GROUP) - set(N.allow_any_auth.allowed_roles)
        assert missing == set(), (
            f"roles that cannot acknowledge their own notifications: {missing}. "
            f"A GATE has no exit but its action, so a 403 here is a lockout."
        )

    def test_the_gate_is_derived_not_typed(self):
        """Derived from the canonical map, so a new role cannot be forgotten.

        A hand-written list that happens to be complete today passes the test
        above and goes stale the next time a role is added — which is exactly
        the history of this constant.
        """
        src = inspect.getsource(N)
        assert "RoleChecker(sorted(ROLE_TO_COGNITO_GROUP))" in src


class TestTheRequestSchema:
    """Dimension 9 — the trust boundary."""

    def test_action_is_a_closed_set(self):
        import typing
        ann = N.AcknowledgeIn.model_fields["action"].annotation
        assert set(typing.get_args(ann)) == {"confirmed", "skipped", "unavailable"}

    def test_shown_as_is_a_closed_set(self):
        import typing
        ann = N.AcknowledgeIn.model_fields["shown_as"].annotation
        assert set(typing.get_args(ann)) == {"gate", "prompt"}

    def test_unknown_keys_are_rejected(self):
        assert N.AcknowledgeIn.model_config.get("extra") == "forbid"

    def test_hostile_payloads_are_refused(self):
        """Verified by execution, not by reading the annotation."""
        import pydantic
        import pytest as _pt

        for bad in (
            {"action": "approved", "shown_as": "gate"},       # not in the set
            {"action": "confirmed", "shown_as": "modal"},     # not in the set
            {"action": "confirmed"},                          # missing shown_as
            {"action": "confirmed", "shown_as": "gate", "employee_id": "x"},
        ):
            with _pt.raises(pydantic.ValidationError):
                N.AcknowledgeIn(**bad)

    def test_the_three_values_match_the_model_enum(self):
        """The schema and the column's enum must not drift.

        `action` is a String(12) with a Python-side StrEnum, so nothing in the
        database enforces agreement — a value accepted here and absent from
        AckAction would store fine and read back as an unknown state.
        """
        import typing
        from app.models.role_guide import AckAction

        assert set(typing.get_args(N.AcknowledgeIn.model_fields["action"].annotation)) == {
            a.value for a in AckAction
        }

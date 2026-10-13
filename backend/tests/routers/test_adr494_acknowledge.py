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
import re

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
        """A source check only. The behaviour (which answers 409, and which
        repeat) is pinned by test_adr505_answer_history.py against a real db."""
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

class TestTheRowOutlivesTheNotification:
    """ADR-494 D8 finding — the defect that made D7's whole premise false.

    `notification_id` was the PRIMARY KEY with ON DELETE CASCADE, and
    `prune_notifications` deletes notifications after 3 days (immediately once
    `expires_at` passes). So every acknowledgement was destroyed three days
    after it was made, and D7's justification — *"a dispute six weeks later
    turns on which it was"* — could never have been met.

    Nothing would have reported it. The rows would simply not be there.

    Verified against the real database during the fix: the notification was
    deleted, `notification_id` went NULL, and the row survived carrying the
    type, the exact message shown and the choice. These tests pin the schema
    properties that make that true.
    """

    def test_the_fk_sets_null_rather_than_cascading(self):
        from app.models.role_guide import NotificationAcknowledgement as A

        fks = list(A.__table__.c["notification_id"].foreign_keys)
        assert fks, "notification_id lost its foreign key"
        assert fks[0].ondelete == "SET NULL", (
            f"ondelete is {fks[0].ondelete!r} — CASCADE destroys the evidence "
            f"when prune_notifications runs, which is 3 days after it is made"
        )

    def test_notification_id_is_nullable_and_not_the_primary_key(self):
        """SET NULL is impossible on a primary key, so the swap is load-bearing."""
        from app.models.role_guide import NotificationAcknowledgement as A

        col = A.__table__.c["notification_id"]
        assert col.nullable is True
        assert col.primary_key is False
        assert A.__table__.c["id"].primary_key is True

    def test_one_final_answer_per_notification_still_holds(self):
        """The old PK's real job, narrowed by ADR-505 to FINAL answers.

        ADR-494 kept notification_id UNIQUE, which recorded the first answer
        forever: "Later" then "confirm" stayed "skipped". What must stay unique is
        the final answer, so the guarantee is now a PARTIAL unique index.
        """
        from app.models.role_guide import FINAL_ACK_ACTIONS, NotificationAcknowledgement as A

        idx = {i.name: i for i in A.__table__.indexes}["uq_ack_final_answer"]
        assert idx.unique and [c.name for c in idx.columns] == ["notification_id"]
        where = str(idx.dialect_options["postgresql"]["where"])
        for action in FINAL_ACK_ACTIONS:
            assert f"'{action}'" in where, f"the index WHERE no longer names {action!r}"
        assert "'skipped'" not in where, "skips must be allowed to repeat (ADR-505 D1)"

    def test_the_snapshots_exist_and_are_required(self):
        """After the prune these are the ONLY record of what was shown.

        Nullable snapshots would let a row say "they confirmed something",
        which is not evidence of anything.
        """
        from app.models.role_guide import NotificationAcknowledgement as A

        for name in ("notification_type", "message_snapshot"):
            assert name in A.__table__.c, f"{name} is missing"
            assert A.__table__.c[name].nullable is False, (
                f"{name} is nullable — an acknowledgement that cannot say WHAT "
                f"was acknowledged is not evidence"
            )

    def test_the_endpoint_populates_both_snapshots(self):
        """A snapshot column the write path never fills is a 500 on every call.

        Parsed from the constructor call, not grepped: the surrounding comment
        names both columns, so a substring assertion would match the prose.
        """
        tree = ast.parse(_ack_src().lstrip())
        kwargs: set[str] = set()
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "NotificationAcknowledgement"):
                kwargs = {kw.arg for kw in node.keywords}
        assert {"notification_type", "message_snapshot"} <= kwargs, (
            f"the constructor passes {sorted(kwargs)} — both snapshots are "
            f"NOT NULL, so a missing one is an IntegrityError on every call"
        )

class TestTheSnapshotCannotBecomeAnUnredactedName:
    """`message_snapshot` outlives the notification, so it must not hold a name.

    ADR-494's D8 fix made the acknowledgement survive its notification by
    snapshotting the message. That is correct for evidence and dangerous for
    privacy: **24 notification message f-strings in this repo interpolate an
    employee name**, and a name copied into free text is exactly the
    denormalised copy ADR-221's `redact_employee_names` was built to chase --
    except this one has no `_by_name` column for the paired-FK match to find, so
    the existing redaction registry CANNOT reach it.

    `adp_mismatch_detect._describe` already states the principle in its own
    docstring: *"a name baked into a string is a denormalised copy that drifts
    and escapes redaction."*

    All five interruptive types are name-free today (verified at the call sites,
    plus by tracing the two that pass a variable). This test is what keeps that
    true, because the snapshot is only safe while it is.

    Scoped to the INTERRUPTIVE types deliberately: those are the only messages
    that ever get snapshotted, so a name in `dispatch_assignment` is not this
    test's business.
    """

    #: Attribute accesses that mean "an employee's name reached this string".
    _NAME_HINTS = (".name", "_name", "full_name")

    def _interruptive_types(self) -> set[str]:
        from app.services.notification_spec import SPEC, Channel

        return {
            t for t, spec in SPEC.items()
            if Channel.GATE in spec.channels or Channel.PROMPT in spec.channels
        }

    def test_no_interruptive_message_interpolates_a_name(self):
        """Walks the CALL SITES, not the registry.

        A raise site is where a name enters a message, so that is what must be
        enumerated. Two sites pass a variable rather than an f-string
        (`operating_mode_change` and `graduation`); those are reported as
        needing a manual read rather than silently passing, because this test
        cannot resolve a variable and must not pretend it did.
        """
        import pathlib as _pl

        interruptive = self._interruptive_types()
        offenders: list[str] = []
        indirect: list[str] = []

        for f in _pl.Path("app").rglob("*.py"):
            try:
                tree = ast.parse(f.read_text())
            except Exception:
                continue
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call)
                        and isinstance(node.func, (ast.Name, ast.Attribute))):
                    continue
                fn = (node.func.id if isinstance(node.func, ast.Name)
                      else node.func.attr)
                if fn not in ("write_notification", "fan_out"):
                    continue
                kwargs = {k.arg: k.value for k in node.keywords}
                tv = kwargs.get("type")
                if not (isinstance(tv, ast.Constant) and tv.value in interruptive):
                    continue
                msg = kwargs.get("message")
                if msg is None:
                    continue
                src = ast.unparse(msg)
                if isinstance(msg, ast.Name):
                    # A variable. Recorded, not waved through.
                    indirect.append(f"{f}:{node.lineno} type={tv.value} message={src}")
                    continue
                if any(h in src for h in self._NAME_HINTS):
                    offenders.append(f"{f}:{node.lineno} type={tv.value} -> {src[:90]}")

        assert offenders == [], (
            "an INTERRUPTIVE notification interpolates an employee name into its "
            "message, and that message is snapshotted onto the acknowledgement "
            "row, which outlives both the notification and (on erasure) the "
            "employee:\n  " + "\n  ".join(offenders) +
            "\nResolve the name at read time from employee_id instead "
            "(adp_mismatch_detect._describe is the pattern)."
        )

        # The indirect sites are a known, bounded set. If a new one appears,
        # somebody must read it -- the list is the prompt to do that.
        assert len(indirect) <= 2, (
            f"{len(indirect)} interruptive raise sites pass a message variable "
            f"this test cannot resolve; read each and confirm it is name-free:\n  "
            + "\n  ".join(indirect)
        )

    def test_the_known_variable_messages_are_name_free(self):
        """The two indirect sites, pinned by their actual text.

        `operating_mode_change` builds `message` from two literal branches and
        `graduation` uses `message_self`. Both were read by hand; these
        assertions are what notices if either is rewritten to include a name.
        """
        import inspect

        # `_notify_mode_change`, not `set_operating_mode` -- the endpoint
        # delegates, and asserting against the endpoint's source passed nothing
        # useful (it does not contain the message at all, which is how this
        # assertion failed on its first run and correctly so).
        from app.routers.companies import _notify_mode_change
        from app.services.graduate_trainees import graduate_eligible_trainees

        mode_src = inspect.getsource(_notify_mode_change)
        assert "message = (" in mode_src

        # PARSED, not line-scanned. The line-based version did not fire when
        # probed: the message is a parenthesised multi-line string, so an
        # interpolation on a CONTINUATION line contains neither "message" nor
        # "=" and the filter skipped it entirely. Walking the assignment's
        # value node sees every part of it.
        mode_tree = ast.parse(mode_src.lstrip())
        msg_values = [
            node.value for node in ast.walk(mode_tree)
            if isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "message" for t in node.targets)
        ]
        assert msg_values, "no `message` assignment found in _notify_mode_change"
        for value in msg_values:
            rendered = ast.unparse(value)
            assert ".name" not in rendered and "_name" not in rendered, (
                f"the operating_mode_change message now interpolates a name: "
                f"{rendered[:120]}"
            )
            # An f-string at all is worth noticing here: both branches are
            # plain literals today, so a JoinedStr means someone started
            # interpolating something into a snapshotted message.
            assert not isinstance(value, ast.JoinedStr), (
                f"the operating_mode_change message became an f-string: "
                f"{rendered[:120]}. It is snapshotted onto the acknowledgement "
                f"row, so confirm what is being interpolated."
            )

        grad_src = inspect.getsource(graduate_eligible_trainees)
        m = re.search(r"message_self = \((.*?)\)", grad_src, re.S)
        assert m, "message_self is gone -- graduation's own copy changed shape"
        assert ".name" not in m.group(1), (
            "graduation's message_self now interpolates a name. It is the copy "
            "the TRAINEE acknowledges, so the name would land in message_snapshot "
            "and outlive their erasure."
        )

class TestErasureBeatsEvidence:
    """`employee_id` CASCADEs on purpose, and the asymmetry is the decision.

    `notification_id` is SET NULL so the row outlives the notification;
    `employee_id` is CASCADE so it does NOT outlive the person. Two FKs on one
    table with opposite rules is exactly the shape that gets "tidied" into
    consistency by someone who does not know why, so it is pinned here.

    The reasoning, verified rather than asserted during the decision:

    * A hard employee delete IS on-demand erasure (ADR-221). `delete_employee`
      calls `redact_employee_names` deliberately, and its own ADR-492 409
      message tells the admin to *"deactivate the employee instead of
      deleting"*.
    * The NORMAL departure path preserves the evidence.
      `deactivate_employee` stamps `deactivated_at` and the row survives as a
      tombstone with the FK intact, so `employee_id` stays resolvable
      indefinitely. The 6-month job redacts the NAME; it does not delete the
      row, so nothing here cascades.
    * ADR-492's answer -- refuse the delete -- does not transfer. Its retention
      hold is RELEASABLE and owned by whoever placed it. An acknowledgement has
      no release and no purge covers this table, so refusing on its existence
      would block erasure PERMANENTLY and 409 a GDPR or Amazon erasure request
      with no way to comply.
    """

    def test_employee_id_cascades_with_erasure(self):
        from app.models.role_guide import NotificationAcknowledgement as A

        col = A.__table__.c["employee_id"]
        fks = list(col.foreign_keys)
        assert fks, "employee_id lost its foreign key"
        assert fks[0].ondelete == "CASCADE", (
            f"employee_id ondelete is {fks[0].ondelete!r}. CASCADE is deliberate: "
            f"a hard delete is on-demand erasure (ADR-221), and evidence about an "
            f"erased person must not survive them. SET NULL would leave "
            f"'somebody confirmed a timecard_mismatch' -- evidence of nothing, "
            f"AND a retained trace of someone who asked to be erased."
        )
        assert col.nullable is False, (
            "employee_id became nullable, which only makes sense with SET NULL "
            "-- see above for why that is the wrong answer here"
        )

    def test_the_two_foreign_keys_disagree_on_purpose(self):
        """The asymmetry itself, so 'making them consistent' fails loudly."""
        from app.models.role_guide import NotificationAcknowledgement as A

        notif = list(A.__table__.c["notification_id"].foreign_keys)[0]
        emp = list(A.__table__.c["employee_id"].foreign_keys)[0]
        assert notif.ondelete == "SET NULL" and emp.ondelete == "CASCADE", (
            f"the FK rules changed (notification={notif.ondelete}, "
            f"employee={emp.ondelete}). They are DIFFERENT on purpose: the row "
            f"must outlive the notification it documents (so the evidence "
            f"survives the 3-day prune) and must NOT outlive the person it is "
            f"about (so erasure actually erases)."
        )

    def test_deactivation_is_the_preserving_path(self):
        """The guarantee the CASCADE decision rests on.

        If `deactivate_employee` ever started deleting the row instead of
        stamping it, every acknowledgement for every departed employee would
        cascade away -- and the CASCADE above would stop being defensible,
        because there would no longer be a non-destructive departure path.
        """
        import inspect

        from app.routers.employees import deactivate_employee

        src = inspect.getsource(deactivate_employee)
        assert "deactivated_at" in src, (
            "deactivate_employee no longer stamps deactivated_at -- the "
            "tombstone is what keeps an acknowledgement's subject resolvable"
        )
        tree = ast.parse(src.lstrip())
        deletes = [
            n for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "delete"
        ]
        assert deletes == [], (
            f"deactivate_employee now calls .delete() at line(s) "
            f"{[d.lineno for d in deletes]} -- deactivation must PRESERVE the "
            f"row, or acknowledgements cascade away on an ordinary departure "
            f"and ADR-494's CASCADE decision no longer holds"
        )

"""ADR-505 — every answer is a row, one is final, and a settled notification stops interrupting.

BEHAVIOURAL, against the suite's in-memory db: the endpoint is called directly.
The ADR-494 tests for this endpoint were source checks ("HTTP_409_CONFLICT" in
the source), which pass whatever the endpoint does with a second answer. The
defect this ADR fixes, a skip followed by a confirm recorded as "skipped", was
found on a real device, not by those.

SQLite does not get the partial unique index (the mirror copies columns only),
so the DATABASE half of D1 was proven on Postgres directly (journal
2026-10-13): skip, skip, confirm = 3 rows; a second confirmed or an unavailable
afterwards raised on uq_ack_final_answer. Here the endpoint's own pre-check and
its IntegrityError path are what is pinned.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.models.notification import Notification
from app.models.role_guide import FINAL_ACK_ACTIONS, NotificationAcknowledgement as Ack
from app.routers import notifications as N
from app.schemas.notification import NotificationResponse
from app.services.notification_degrade import drop_if_settled
from tests.conftest import make_employee, sqlite_mirror_with_defaults


@pytest.fixture
def setup(db):
    sqlite_mirror_with_defaults(Ack.__table__).create(db.get_bind(), checkfirst=True)
    emp = make_employee(db, role="walker")
    n = Notification(_via_helper=True, company_id=emp.company_id, employee_id=emp.id,
                     type="graduation", message="Congratulations! You passed.")
    db.add(n); db.commit()
    return emp, n


def _answer(db, emp, n, action, shown_as="prompt"):
    return N.acknowledge_notification(
        notification_id=n.id, payload=N.AcknowledgeIn(action=action, shown_as=shown_as),
        db=db, caller=emp, _={},
    )


def _actions(db, n):
    db.expire_all()
    return [a for (a,) in db.query(Ack.action).filter(Ack.notification_id == n.id)
            .order_by(Ack.acknowledged_at, Ack.id)]


class TestEveryAnswerIsARow:
    def test_skip_skip_confirm_is_three_rows_in_order(self, db, setup):
        emp, n = setup
        for a in ("skipped", "skipped", "confirmed"):
            _answer(db, emp, n, a)
        assert sorted(_actions(db, n)) == ["confirmed", "skipped", "skipped"], (
            "the reproduced defect: under ADR-494 the second answer was a 409 and "
            "the record stayed 'skipped' for someone who confirmed"
        )

    @pytest.mark.parametrize("final", sorted(FINAL_ACK_ACTIONS))
    @pytest.mark.parametrize("then", ["confirmed", "skipped", "unavailable"])
    def test_nothing_is_accepted_after_a_final_answer(self, db, setup, final, then):
        emp, n = setup
        _answer(db, emp, n, final)
        with pytest.raises(HTTPException) as e:
            _answer(db, emp, n, then)
        assert e.value.status_code == 409
        assert _actions(db, n) == [final], "a refused answer must not leave a row"


class TestReadFlag:
    def test_a_skip_leaves_it_unread(self, db, setup):
        emp, n = setup
        _answer(db, emp, n, "skipped")
        db.expire_all()
        assert db.get(Notification, n.id).is_read is False, (
            "a skip means 'not now'; the inbox must still show it pending (D3)"
        )

    def test_a_final_answer_marks_it_read(self, db, setup):
        emp, n = setup
        _answer(db, emp, n, "confirmed")
        db.expire_all()
        assert db.get(Notification, n.id).is_read is True


class TestSettledStopsInterrupting:
    def _channels(self, db, n):
        db.expire_all()
        return NotificationResponse.from_row_scoped(db.get(Notification, n.id), db).channels

    def test_unanswered_and_skipped_still_prompt(self, db, setup):
        emp, n = setup
        assert "prompt" in self._channels(db, n)
        _answer(db, emp, n, "skipped")
        assert "prompt" in self._channels(db, n), "a skipped prompt re-asks (ADR-494)"

    def test_a_final_answer_removes_prompt_and_gate_but_keeps_the_rest(self, db, setup):
        emp, n = setup
        before = set(self._channels(db, n))
        _answer(db, emp, n, "confirmed")
        after = set(self._channels(db, n))
        assert not after & {"gate", "prompt"}, "the reproduced defect: it came back every launch"
        assert after == before - {"gate", "prompt"}, "banner/push/inbox must survive settling"

    def test_without_a_session_nothing_changes(self):
        row = MagicMock()
        assert drop_if_settled(None, row, ["banner", "prompt"]) == ["banner", "prompt"]

    def test_a_non_interruptive_row_costs_no_query(self):
        db = MagicMock()
        db.query.side_effect = AssertionError("queried for a row that cannot interrupt")
        assert drop_if_settled(db, MagicMock(), ["banner", "push"]) == ["banner", "push"]


class TestTheRace:
    def test_an_integrity_error_is_a_409_with_no_audit(self, db, setup):
        """Two confirms passing the pre-check together: the partial index refuses
        the second at flush. That must be a 409, and nothing may be audited after
        the rollback (CLAUDE.md flush-audit-commit exception)."""
        emp, n = setup
        real_flush = db.flush

        def flush_refusing_the_ack(*a, **k):
            # Raise only once the acknowledgement is pending. Raising on every
            # flush also hits the AUTOflush inside the endpoint's earlier
            # queries, which fails before the code under test runs (the first
            # version of this test did exactly that).
            if any(isinstance(o, Ack) for o in db.new):
                raise IntegrityError("INSERT", {}, Exception("uq_ack_final_answer"))
            return real_flush(*a, **k)

        with patch.object(db, "flush", side_effect=flush_refusing_the_ack), \
             patch.object(N, "write_audit") as audit:
            with pytest.raises(HTTPException) as e:
                _answer(db, emp, n, "confirmed")
        assert e.value.status_code == 409
        assert audit.call_count == 0


def test_the_migration_states_the_same_rule_as_the_model():
    import pathlib
    mig = next(pathlib.Path(__file__).resolve().parents[2].glob("alembic/versions/*_ack_answer_history.py"))
    src = mig.read_text()
    assert "uq_ack_final_answer" in src and 'drop_constraint("uq_ack_notification"' in src
    for action in FINAL_ACK_ACTIONS:
        assert f"'{action}'" in src


class TestEveryPromptRenders:
    """ADR-505 D4: the test whose absence let a payroll prompt render nothing.

    Walks the WORLD, not a list: every type whose registry channels include
    `prompt`, plus every `gate` type (the server degrades any gate to a prompt
    when it cannot be honoured). For each, a host must render a component, by
    a dedicated case or by the general ActionPrompt. Before ADR-505 the hosts'
    `default:` returned null, so this set minus {graduation,
    operating_mode_change} rendered nothing.
    """

    import re as _re
    ROOT = __import__("pathlib").Path(__file__).resolve().parents[3]
    HOSTS = {
        "web": ROOT / "frontend/src/components/notifications/InterruptiveHost.tsx",
        "mobile": ROOT / "mobile/src/components/notifications/InterruptiveHost.tsx",
    }

    @staticmethod
    def _code(path):
        import re
        return re.sub(r"//[^\n]*|/\*.*?\*/|\{/\*.*?\*/\}", "", path.read_text(), flags=re.S)

    def _reachable_types(self):
        from app.services.notification_spec import SPEC, Channel
        return sorted(t for t, s in SPEC.items()
                      if s.channels & (Channel.PROMPT | Channel.GATE))

    def test_there_are_prompt_reachable_types_beyond_the_two_with_faces(self):
        types = set(self._reachable_types())
        assert {"graduation", "operating_mode_change"} < types, (
            "if only the two dedicated types can prompt, this class tests nothing"
        )
        assert "timecard_mismatch" in types

    @__import__("pytest").mark.parametrize("surface", ["web", "mobile"])
    def test_the_default_branch_renders_the_general_prompt(self, surface):
        import re
        code = self._code(self.HOSTS[surface])
        m = re.search(r"default:\s*(.*?)(?:\n\s*\}|\n\s*case\s)", code, flags=re.S)
        assert m, f"{surface}: no default branch in the host's switch"
        branch = m.group(1)
        assert "<ActionPrompt" in branch, (
            f"{surface}: the default branch does not render ActionPrompt -- every "
            f"prompt type without a dedicated case renders nothing, and hides the "
            f"prompts queued behind it (ADR-505 D4)"
        )
        assert "return null" not in branch

    @__import__("pytest").mark.parametrize("surface", ["web", "mobile"])
    def test_every_reachable_type_is_covered(self, surface):
        """Each type is rendered by a dedicated case OR falls to the default,
        which renders ActionPrompt. A case that returns null would be a hole."""
        import re
        code = self._code(self.HOSTS[surface])
        for t in self._reachable_types():
            case = re.search(rf"case '{t}':\s*(.*?)(?:\n\s*case\s|\n\s*default:)", code, flags=re.S)
            if case:
                assert "return null" not in case.group(1), f"{surface}: case '{t}' renders nothing"

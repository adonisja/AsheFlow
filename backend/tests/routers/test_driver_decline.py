"""ADR-264 D7 — a supervising driver declines, or the trainee does.

THE FAILURES THIS GUARDS AGAINST
--------------------------------
1. A supervising driver declines and NOTHING happens. Before this, no branch in
   the decline dispatcher matched `driver` at all: the trainee stayed paired to
   someone who was not coming, on a truck that looked staffed.

2. A driver trainee declines and their TrainingRecord stays open, so a phase can
   still be closed for a day they did not work.

3. The system auto-reassigns the trainee to whoever is free. Continuity says a
   new supervising relationship is a human decision (2026-08-22), and D7 says
   solo is an explicit approval, never a fallback.

dispatch.py is proprietary; CI copies it in before pytest, so there is
deliberately NO skip guard.
"""
import inspect

from app.routers import dispatch


def _code_only(obj) -> str:
    src = inspect.getsource(obj)
    lines = [ln for ln in src.splitlines() if not ln.lstrip().startswith("#")]
    code = "\n".join(ln.split("#")[0] for ln in lines)
    parts = code.split('"""')
    return "".join(parts[::2]) if len(parts) > 2 else code


DRIVER = _code_only(dispatch._handle_driver_decline)
TRAINEE = _code_only(dispatch._handle_driver_trainee_decline)
CONFIRM = _code_only(dispatch.record_confirmation)


class TestBothDeclinesAreRouted:
    def test_a_driver_decline_reaches_the_handler(self):
        """No branch matched `driver` before ADR-264."""
        assert "emp.role == ROLE_DRIVER:" in CONFIRM
        assert "_handle_driver_decline(" in CONFIRM

    def test_a_driver_trainee_decline_reaches_its_own_handler(self):
        assert "emp.role == ROLE_DRIVER_TRAINEE:" in CONFIRM
        assert "_handle_driver_trainee_decline(" in CONFIRM

    def test_the_trainee_branch_precedes_the_driver_branch(self):
        """`driver_trainee` must be matched before `driver`; an elif chain
        ordered the other way is fine here only because the comparison is
        exact — but the ordering is load-bearing if it ever becomes a prefix
        or membership test."""
        assert CONFIRM.index("ROLE_DRIVER_TRAINEE:") < CONFIRM.index("ROLE_DRIVER:")

    def test_the_driver_trainee_does_not_fall_into_the_walker_handler(self):
        """_handle_trainee_decline reverts 1.5x route capacity and frees a
        walker TRAINER. A driver trainee has neither."""
        assert "_handle_trainee_decline" not in TRAINEE


class TestSupervisorDecline:
    def test_it_returns_early_when_nobody_was_supervised(self):
        """An ordinary driver decline is already covered by the shortage
        warning; firing a training alert would be noise on most declines."""
        assert "if not supervised:" in DRIVER
        assert "return" in DRIVER

    def test_it_finds_who_they_were_supervising(self):
        assert "AssignmentMember.paired_trainer_id == driver.id" in DRIVER
        assert "AssignmentMember.role == ROLE_DRIVER_TRAINEE" in DRIVER

    def test_it_does_not_move_anyone(self):
        """Suggests a prior supervisor by name; never reassigns. Creating a new
        supervising relationship is a human decision."""
        # `paired_trainer_id =` also matches the `==` filter, so check for an
        # ASSIGNMENT specifically: `= ` not preceded by another `=`.
        import re

        assigns = re.findall(r"paired_trainer_id\s*=(?!=)", DRIVER)
        assert not assigns, f"must not re-pair automatically: {assigns}"
        assert "db.delete(" not in DRIVER

    def test_the_assignment_row_is_left_intact(self):
        """Clearing it would erase the evidence of who declined and make the
        trainee silently vanish from the truck."""
        assert "db.delete(" not in DRIVER
        assert ".role = " not in DRIVER

    def test_it_only_suggests_a_prior_supervisor(self):
        """Not any free driver — continuity."""
        assert "prior_supervisor_ids(" in DRIVER
        assert "pid in todays_driver_ids" in DRIVER

    def test_the_declining_driver_is_excluded_from_suggestions(self):
        assert "todays_driver_ids.discard(driver.id)" in DRIVER

    def test_the_message_names_both_ways_out(self):
        src = inspect.getsource(dispatch._handle_driver_decline)
        assert "supervised them before" in src
        assert "approve a solo day" in src


class TestTraineeDecline:
    def test_it_locks_the_training_record(self):
        """Otherwise a phase can close for a day the trainee did not work —
        the same class of defect as D8's solo-day rule."""
        assert "record.is_locked = True" in TRAINEE

    def test_it_does_not_touch_the_supervisors_assignment(self):
        """The driver is still driving their truck; they just have nobody to
        teach today."""
        assert "paired_trainer_id" not in TRAINEE

    def test_it_notifies_oversight(self):
        assert "OVERSIGHT_ROLES" in TRAINEE
        assert '"driver_trainee_declined"' in TRAINEE


class TestTenancy:
    def test_every_query_in_both_handlers_is_company_scoped(self):
        """ADR-115 dim 1."""
        for name, src in (("driver", DRIVER), ("trainee", TRAINEE)):
            lines = src.splitlines()
            for i, ln in enumerate(lines):
                if "db.query(" in ln:
                    window = "\n".join(lines[i : i + 10])
                    assert "company_id" in window, f"{name}: unscoped query: {ln.strip()}"

    def test_notifications_carry_the_company(self):
        assert DRIVER.count("company_id=company_id") >= 1
        assert TRAINEE.count("company_id=company_id") >= 1

"""ADR-285 — the onboarding window.

THE PROBLEM IT SOLVES
---------------------
`walker`, `trainer`, `driver` and `captain` are refused at hire so a new hire
cannot skip the training that qualifies them. Correct for hiring; unusable for
MIGRATION.

A DSP signing up with 40 existing staff has drivers who have driven for years.
Under the hiring rule they enter as trainees — and `trainee -> walker` is not
even a promotion. It happens only by passing the graduation quiz, so twenty
experienced walkers would sit through a five-phase program before they could
work. That does not inconvenience the customer; it makes the product unusable
for them.
"""
import inspect

from app.routers import employees
from app.services import company_onboarding as co


class _Q:
    """Minimal Session stand-in: `first()` returns whatever it is given."""

    def __init__(self, result):
        self.result = result

    def query(self, *a, **k): return self
    def filter(self, *a, **k): return self
    def first(self): return self.result


class TestTheWindowIsAState:
    def test_open_when_no_active_field_staff(self):
        assert co.is_onboarding(_Q(None), "c1") is True

    def test_closed_once_anyone_is_working(self):
        assert co.is_onboarding(_Q(("emp-1",)), "c1") is False

    def test_it_keys_on_is_active_not_row_existence(self):
        """Employees are created is_active=False and pending_verification, so a
        company mid-import — rows written, nobody registered — is STILL
        onboarding. Otherwise the first imported row closes the window on the
        second, and a 40-person migration imports one person."""
        src = inspect.getsource(co.is_onboarding)
        assert "Employee.is_active == True" in src

    def test_trainees_count_as_operating(self):
        """A company that has started training someone is operating; its next
        hire is a hire, not a migration."""
        assert "trainee" in co.OPERATING_ROLES
        assert "driver_trainee" in co.OPERATING_ROLES

    def test_it_does_not_depend_on_the_shadowed_field_roles_constant(self):
        """constants.FIELD_ROLES has no importers and is shadowed by a
        different set in employees.py. Depending on it would tie this rule to a
        constant nobody maintains."""
        # The module NAMES FIELD_ROLES in the comment explaining why it does
        # not use it, so strip comments first — a raw substring check fails on
        # the documentation. (Fifth time this trap has fired here.)
        src = inspect.getsource(co)
        code = "\n".join(
            ln.split("#")[0] for ln in src.splitlines()
            if not ln.lstrip().startswith("#")
        )
        assert "FIELD_ROLES" not in code
        assert "OPERATING_ROLES" in code


class TestBothCreationPathsHonourIt:
    def test_create_employee_checks_the_window(self):
        src = inspect.getsource(employees.create_employee)
        assert "onboarding = is_onboarding(db, caller.company_id)" in src
        assert "if employee.role in EARNED_ROLES and not onboarding:" in src

    def test_management_restriction_relaxes_too(self):
        """Management does the hiring at most DSPs. If only admins could use
        the window, the feature would not reach the person who needs it."""
        src = inspect.getsource(employees.create_employee)
        assert 'caller.role == "management" and not onboarding' in src

    def test_bulk_import_checks_the_window(self):
        src = inspect.getsource(employees.bulk_import_employees)
        assert "if row.role in EARNED_ROLES and not onboarding:" in src

    def test_bulk_evaluates_the_window_once_before_the_loop(self):
        """THE bug this ordering prevents: evaluated per row, the window closes
        the moment the first row lands, so a 40-person migration imports one
        employee and rejects the other 39. The rows are one migration, not
        forty independent hires."""
        src = inspect.getsource(employees.bulk_import_employees)
        assert src.index("onboarding = is_onboarding(") < src.index("for i, row in enumerate(")


class TestItLeavesATrace:
    def test_create_audits_the_window(self):
        """A migrated captain and a wrongly-created one are indistinguishable
        without this."""
        src = inspect.getsource(employees.create_employee)
        assert '"onboarding_window": True' in src

    def test_bulk_audits_the_window(self):
        src = inspect.getsource(employees.bulk_import_employees)
        assert '"onboarding_window": True' in src

    def test_the_trace_is_only_added_for_earned_roles(self):
        """Stamping every row during onboarding would make the flag noise; it
        marks the ones that would otherwise have been refused."""
        for fn in (employees.create_employee, employees.bulk_import_employees):
            src = inspect.getsource(fn)
            i = src.index('"onboarding_window": True')
            assert "EARNED_ROLES" in src[max(0, i - 120) : i + 120]

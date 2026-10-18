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
    """ADR-538 replaced ADR-285's rule ("no active field staff") with the setup
    window: 10 or fewer sign-in accounts AND within 30 days of company creation.
    The behavioural tests for it live in test_adr538_setup_window.py; this keeps
    the one structural fact that matters here."""

    def test_it_is_the_setup_window(self):
        src = inspect.getsource(co.is_onboarding)
        assert "setup_window(db, company_id)" in src


class TestBothCreationPathsHonourIt:
    def test_create_employee_checks_the_window(self):
        src = inspect.getsource(employees.create_employee)
        assert "onboarding = is_onboarding(db, caller.company_id)" in src
        # ADR-532: the window is honoured inside the one shared grant rule.
        assert "_grant_refusal(caller.role, employee.role, onboarding)" in src

    def test_management_restriction_relaxes_too(self):
        """Management does the hiring at most DSPs. If only admins could use
        the window, the feature would not reach the person who needs it.

        ADR-532 narrows WHAT relaxes, not WHO: during onboarding a manager may
        import every earned field role (the migration this window exists for),
        but never a manager or admin -- that relaxation was an escalation."""
        for earned in employees.EARNED_ROLES:
            assert employees._grant_refusal("management", earned, onboarding=True) is None
            assert employees._grant_refusal("management", earned, onboarding=False) is not None
        for protected in ("management", "admin"):
            assert employees._grant_refusal("management", protected, onboarding=True) is not None

    def test_bulk_import_checks_the_window(self):
        src = inspect.getsource(employees.bulk_import_employees)
        assert "_grant_refusal(caller.role, row.role, onboarding)" in src

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

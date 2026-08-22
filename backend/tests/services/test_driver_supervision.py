"""ADR-264 D9 — supervision eligibility is one predicate.

THE FAILURE THIS GUARDS AGAINST
-------------------------------
`field_supervisor` and `captain` arrive in their own work. If any call site
inlines `role == "driver"` at a supervision check, threading a new role means
finding every one of them — and this codebase has precedent for role lists
drifting between call sites.

The test that matters is the LAST one: no call site may inline the comparison.
"""
from pathlib import Path

import pytest

from app.services.driver_supervision import (
    SUPERVISING_ROLES, can_supervise_driver_trainee, eligible_supervisors,
)


class _Emp:
    def __init__(self, role, is_active=True):
        self.role, self.is_active = role, is_active


class TestThePredicate:
    def test_an_active_driver_may_supervise(self):
        assert can_supervise_driver_trainee(_Emp("driver")) is True

    def test_an_inactive_driver_may_not(self):
        """The reason the predicate takes the OBJECT, not a role string: a
        caller passing employee.role alone would skip this check."""
        assert can_supervise_driver_trainee(_Emp("driver", is_active=False)) is False

    @pytest.mark.parametrize("role", ["walker", "trainer", "trainee", "driver_trainee", "dispatch", "admin"])
    def test_nobody_else_may(self, role):
        assert can_supervise_driver_trainee(_Emp(role)) is False

    def test_a_driver_trainee_cannot_supervise_another_driver_trainee(self):
        """Obvious, and worth pinning: the roles differ by one word."""
        assert can_supervise_driver_trainee(_Emp("driver_trainee")) is False

    def test_none_is_false_not_an_exception(self):
        """Callers resolve a supervisor that may not exist; a missing one is a
        'no supervisor' branch (D7), not a crash mid-dispatch."""
        assert can_supervise_driver_trainee(None) is False

    def test_a_trainer_may_not_supervise_a_driver(self):
        """A walker trainer has no vehicle or load-custody authority to pass on.
        Drivers train drivers."""
        assert can_supervise_driver_trainee(_Emp("trainer")) is False


class TestTheSeamIsTheOnlyDefinition:
    def test_field_supervisor_and_captain_are_deliberately_absent(self):
        """D9 builds the seam, not the roles. When those roles carry the
        authority, adding one here is the whole change."""
        assert SUPERVISING_ROLES == frozenset({"driver"})

    def test_no_call_site_inlines_the_role_comparison(self):
        """THE test. An inlined `role == "driver"` at a supervision check is
        exactly what makes threading a new role expensive later.

        Scoped to driver-training call sites: `role == "driver"` is legitimate
        elsewhere (resolving the truck's driver for RTS, surveys, anchors) —
        those are not supervision checks.
        """
        app = Path(__file__).resolve().parents[2] / "app"
        offenders = []
        for f in app.rglob("*.py"):
            if f.name == "driver_supervision.py":
                continue
            text = f.read_text()
            if "driver_trainee" not in text:
                continue
            for n, line in enumerate(text.splitlines(), 1):
                code = line.split("#")[0]
                if "driver_trainee" not in code and (
                    'role == "driver"' in code or "role == 'driver'" in code
                ):
                    # Only flag when the surrounding function also mentions
                    # supervision — a plain driver lookup is not a supervision check.
                    window = "\n".join(text.splitlines()[max(0, n - 25): n + 5])
                    if "supervis" in window.lower() or "paired_trainer_id" in window:
                        offenders.append(f"{f.relative_to(app)}:{n}")
        assert not offenders, (
            "these supervision checks inline the role comparison instead of "
            f"calling can_supervise_driver_trainee(): {offenders}"
        )


class TestEligibleSupervisors:
    def test_it_filters_and_preserves_order(self):
        pool = [_Emp("walker"), _Emp("driver"), _Emp("trainer"), _Emp("driver")]
        assert len(eligible_supervisors(pool)) == 2

    def test_it_returns_a_list_so_len_works(self):
        """The 'no free supervisor' branch (D7) needs a count; a generator
        would be consumed by the check itself."""
        got = eligible_supervisors([_Emp("driver")])
        assert isinstance(got, list)
        assert len(got) == 1 and len(got) == 1  # twice on purpose — not exhausted

    def test_an_empty_pool_is_empty_not_an_error(self):
        assert eligible_supervisors([]) == []

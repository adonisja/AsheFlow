"""ADR-264 D10 revised — promotion is a dispatch decision, not a quiz result.

THE RULE THAT LOOKS WRONG AND IS NOT
------------------------------------
A closed observation phase with NO recorded verdict is treated as SUCCESSFUL
(operator, 2026-08-22). The likeliest explanation is that observation went fine
and the supervising driver forgot to record it, and withholding a promotion over
another person's missing paperwork punishes the trainee.

Honesty comes from follow-ups, not from blocking: the supervisor is prompted to
document it, and a genuinely bad observation is recorded as a note after which
dispatch assigns someone to observe again — WHILE THE TRAINEE KEEPS THE DRIVER
ROLE.

The inverse — blocking until documented — is the natural implementation and is
wrong here, so it is a planted regression.
"""
import inspect

from app.services import driver_promotion as dp
from app.services.driver_promotion import promotion_warning


class TestVerdictClassification:
    def test_recorded_pass(self):
        w = promotion_warning({"employee_id": "e", "employee_name": "Ada", "verdict": "passed"})
        assert "recorded a pass" in w["message"]
        assert w["verdict"] == "passed"

    def test_recorded_fail_still_offers_promotion(self):
        """A fail does not block: promote and assign an observer, or hold. The
        operator decides, and the note travels with the record."""
        w = promotion_warning({"employee_id": "e", "employee_name": "Ada", "verdict": "failed"})
        assert "recorded a FAIL" in w["message"]
        assert "observe them again" in w["message"]

    def test_unrecorded_is_treated_as_successful(self):
        """THE rule. Not 'blocked pending documentation'."""
        w = promotion_warning({"employee_id": "e", "employee_name": "Ada", "verdict": "unrecorded"})
        assert "Treat as successful and promote" in w["message"]
        assert "still needs to complete the documentation" in w["message"]

    def test_every_verdict_asks_for_the_same_action(self):
        """All three end in 'promote them' — the decision surface is one place."""
        for v in ("passed", "failed", "unrecorded"):
            w = promotion_warning({"employee_id": "e", "employee_name": "A", "verdict": v})
            assert "Promote them to driver from the employee page." in w["message"]


class TestReadiness:
    SRC = inspect.getsource(dp.driver_trainees_awaiting_promotion)

    def test_the_observation_phase_is_derived_not_hardcoded(self):
        """D3 — with N=3 a hardcoded 5 is past the end of the program."""
        assert "plan.observation" in self.SRC
        assert "phase_plan(cfg, TRACK_DRIVER)" in self.SRC
        assert "== 5" not in self.SRC and "== 4" not in self.SRC

    def test_an_open_phase_is_not_reported(self):
        """Still in the program — the crew view already shows them."""
        assert "not obs.phase_closed" in self.SRC
        assert "continue" in self.SRC

    def test_it_never_changes_the_role_itself(self):
        """Promotion is an explicit approval on the employee page. This service
        REPORTS; it must not promote."""
        # `.role =` also matches the `.role ==` filter. Assert on an
        # ASSIGNMENT: `=` not followed by another `=`. (Second time this trap
        # has fired in this ADR's tests.)
        import re

        assert not re.search(r"\.role\s*=(?!=)", self.SRC), "must not change the role"
        assert "_apply_role_transition" not in self.SRC

    def test_it_carries_what_the_approver_needs(self):
        for field in ("supervisor_id", "verdict", "notes", "observation_date"):
            assert f'"{field}"' in self.SRC

    def test_it_is_company_scoped(self):
        assert self.SRC.count("company_id == company_id") == 2


class TestItRepeatsUntilSettled:
    def test_the_dispatch_run_reports_them_every_time(self):
        """'Repeated on the next assignment if it is not settled before that.'
        Nothing marks the warning as seen, so it recurs until the role changes
        and the trainee drops out of the driver_trainee query."""
        src = inspect.getsource(dp.driver_trainees_awaiting_promotion)
        assert "acknowledged" not in src and "dismissed" not in src

    def test_graduate_trainees_emits_it(self):
        from app.services import graduate_trainees

        src = inspect.getsource(graduate_trainees.graduate_eligible_trainees)
        assert "driver_trainees_awaiting_promotion(" in src
        assert "warnings.append(promotion_warning(entry))" in src

    def test_graduate_trainees_does_not_promote_drivers_itself(self):
        """The walker path promotes automatically on a passed quiz. The driver
        path must not — that is the whole revision."""
        from app.services import graduate_trainees

        src = inspect.getsource(graduate_trainees.graduate_eligible_trainees)
        i = src.index("driver_trainees_awaiting_promotion(")
        after = src[i : i + 700]
        assert 'role = "driver"' not in after
        assert "_apply_role_transition" not in after


class TestTheTransitionIsAllowed:
    def test_driver_trainee_can_become_a_driver(self):
        """Without this, /promote 400s: 'A driver_trainee cannot be promoted or
        demoted from this page.'"""
        from app.routers.employees import ROLE_TRANSITIONS

        assert ROLE_TRANSITIONS.get("driver_trainee") == ("driver",)

    def test_it_counts_as_a_promotion_for_the_audit_trail(self):
        from app.routers.employees import _ROLE_RANK

        assert _ROLE_RANK["driver"] > _ROLE_RANK["driver_trainee"]

    def test_a_driver_is_not_demoted_back_on_this_page(self):
        """An unsuccessful observation keeps the driver role and gets an
        observer assigned — a dispatch action, not a role change."""
        from app.routers.employees import ROLE_TRANSITIONS

        assert "driver_trainee" not in ROLE_TRANSITIONS.get("driver", ())

"""Weighted building verification (ADR-276).

WHAT WAS WRONG
--------------
`building_type_agreement_count` claimed to mean "N independent people agree".
It meant no such thing. One person could reach the threshold alone THREE ways:

  1. submit a profile, then verify it themselves — nothing compared the caller
     to `submitted_by`
  2. verify twice — `verified_by` was OVERWRITTEN each time, so no record of
     who had already confirmed
  3. disagree — a differing confirmation overwrote `building_type` and STILL
     incremented, so two people who disagreed produced a `verified` record with
     the losing opinion silently discarded

ADR-276 fixes the count and adds weighting on top: a captain's confirmation is
worth 2, a driver's 1, threshold 2. Walkers submit and never confirm (D1).

Source-reading where the property is structural (who is in which set), and
behavioural over the real functions where the property is arithmetic. Both are
comment-stripped: this file explains the rules at length in prose, and an
assertion that matched a comment would pass against a handler that had lost the
rule entirely.
"""
import re
from pathlib import Path

import pytest

from app.routers.building_profiles import (
    _VERIFY_THRESHOLD, _HEAVY_VERIFIERS, _verify_weight,
)
from app.services.constants import ROUTE_LEAD_ROLES


BACKEND = Path(__file__).resolve().parents[2]
ROUTER = BACKEND / "app" / "routers" / "building_profiles.py"
MODEL = BACKEND / "app" / "models" / "building_profile_verification.py"


def _verify_src() -> str:
    text = ROUTER.read_text(encoding="utf-8")
    start = text.index("def verify_building_profile(")
    body = text[start:text.index("\n@router.", start)]
    if '"""' in body:
        a = body.index('"""'); b = body.index('"""', a + 3) + 3
        body = body[:a] + body[b:]
    return "\n".join(
        l.strip() for l in body.splitlines()
        if l.strip() and not l.strip().startswith("#")
    )


class TestStrippingWorks:
    def test_comments_and_docstring_gone(self):
        src = _verify_src()
        assert "BuildingProfileVerification" in src, "handler body not captured"
        assert "ADR-276 D2" not in src, (
            "comments survived stripping — assertions could match prose"
        )


class TestD1Weighting:
    def test_captain_confirmation_settles_it_alone(self):
        assert _verify_weight("captain") >= _VERIFY_THRESHOLD, (
            "a captain's confirmation no longer reaches the threshold on its "
            "own — the whole point of D1"
        )

    def test_two_drivers_settle_it(self):
        assert _verify_weight("driver") * 2 >= _VERIFY_THRESHOLD

    def test_one_driver_does_not(self):
        assert _verify_weight("driver") < _VERIFY_THRESHOLD, (
            "a single driver confirmation verifies the profile — no second "
            "pair of eyes"
        )

    @pytest.mark.parametrize("role", ["captain", "dispatch", "field_supervisor",
                                      "management", "admin"])
    def test_route_lead_and_oversight_are_heavy(self, role):
        assert _verify_weight(role) == 2

    def test_walkers_cannot_verify_at_all(self):
        # Settled by the operator 2026-08-19. A walker SUBMITS; having them also
        # judge the submission would collapse the two sides of the check.
        assert "walker" not in ROUTE_LEAD_ROLES, (
            "walkers can now verify — ADR-276 D1 states they cannot, and its "
            "weight table has no row for them"
        )

    def test_weight_defaults_safe_for_an_unknown_role(self):
        # A new role must not silently inherit captain-level authority.
        assert _verify_weight("some_new_role") == 1
        assert _verify_weight(None) == 1


class TestD2NoSelfVerification:
    def test_handler_compares_caller_to_submitter(self):
        src = _verify_src()
        assert "profile.submitted_by == caller.id" in src, (
            "the submitter can confirm their own profile — with D1 weighting "
            "that means a captain reaches 'verified' alone in one action"
        )
        assert "HTTP_403_FORBIDDEN" in src

    def test_check_runs_before_any_mutation(self):
        src = _verify_src()
        guard = src.index("profile.submitted_by == caller.id")
        for mutation in ("db.add(", "db.commit()"):
            assert guard < src.index(mutation), (
                f"{mutation} runs before the self-verification check"
            )


class TestD3OnePersonOneVote:
    def test_database_enforces_uniqueness(self):
        # The handler's 409 is for a good error message; THIS is the guarantee.
        src = MODEL.read_text(encoding="utf-8")
        assert 'UniqueConstraint("profile_id", "employee_id"' in src, (
            "nothing stops one person confirming twice to reach the threshold "
            "alone — the constraint is the enforcement, not the handler check"
        )

    def test_handler_returns_409_rather_than_an_integrity_error(self):
        src = _verify_src()
        assert "HTTP_409_CONFLICT" in src

    def test_weight_is_stored_not_derived(self):
        # Recomputing from Employee.role later would re-score history: a
        # driver's old confirmation becomes a captain's when they are promoted.
        src = MODEL.read_text(encoding="utf-8")
        assert "weight        = Column(Integer, nullable=False)" in src

    def test_employee_delete_does_not_drop_the_confirmation(self):
        # SET NULL, not CASCADE: a departed employee's confirmation still
        # counted, and removing it would silently drop a verified profile below
        # its threshold.
        src = MODEL.read_text(encoding="utf-8")
        assert 'ondelete="SET NULL"' in src


class TestD4DisagreementResets:
    def test_a_differing_confirmation_resets_to_one(self):
        src = _verify_src()
        assert "profile.building_type_agreement_count = 1" in src, (
            "a disagreement still accumulates, so two people who DISAGREE "
            "produce a verified record"
        )

    def test_reset_is_to_one_not_to_the_verifier_weight(self):
        # The subtle half. Resetting to the disagreeing verifier's weight would
        # put a captain's correction straight on 2 — self-verifying their own
        # correction and reopening the hole D2 closes.
        src = _verify_src()
        assert "profile.building_type_agreement_count = weight" not in src, (
            "a captain's disagreement self-verifies their correction"
        )
        assert "row_weight = 1" in src, (
            "the disagreeing verifier's own row must be weight 1"
        )

    def test_reset_clears_nomination_and_status(self):
        src = _verify_src()
        assert 'profile.building_type_status          = "pending"' in src, (
            "a disputed profile stays 'verified' and remains lockable"
        )
        assert "profile.nomination_status             = None" in src, (
            "a disputed profile stays nominated and can be promoted to "
            "PlaceType on a contested fact"
        )

    def test_prior_rows_are_discarded(self):
        # They attested to a different building_type and are not evidence for
        # the new one.
        src = _verify_src()
        assert "BuildingProfileVerification.profile_id == profile.id," in src
        assert ".delete(synchronize_session=False)" in src

    def test_the_disagreeing_verifier_still_gets_a_row(self):
        # So D3 bars them from confirming their own correction a second time.
        src = _verify_src()
        add = src.index("db.add(BuildingProfileVerification(")
        assert "row_weight" in src[add:add + 400]


class TestD6UiFields:
    def test_response_exposes_remaining_weight_and_can_verify(self):
        src = (BACKEND / "app" / "schemas" / "location_profile.py").read_text(encoding="utf-8")
        for field in ("remaining_weight", "can_verify", "verify_blocked_reason"):
            assert f"{field}:" in src, f"{field} missing — the UI must not re-derive the rule"

    def test_blocked_reasons_cover_every_disabled_state(self):
        src = (BACKEND / "app" / "schemas" / "location_profile.py").read_text(encoding="utf-8")
        for reason in ("own_submission", "already_verified", "not_a_route_lead"):
            assert f'"{reason}"' in src, (
                f"{reason} is not distinguishable, so the UI shows a live "
                "button that 403s instead of explaining itself"
            )

    def test_fields_are_optional_so_read_paths_are_unaffected(self):
        # Endpoints that do not resolve per-caller state leave them None and the
        # client falls back to a plain count.
        src = (BACKEND / "app" / "schemas" / "location_profile.py").read_text(encoding="utf-8")
        assert "remaining_weight:   Optional[int] = None" in src

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
    _REVIEW_THRESHOLD, _FIELD_VERIFIERS, _SIGNOFF_ROLES, _verify_weight,
)


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


class TestD1TwoStages:
    """Field agreement and route-lead sign-off are different facts.

    The first implementation of this ADR got the roles backwards: it reused
    ROUTE_LEAD_ROLES as the verify gate, so DRIVERS could confirm and WALKERS
    could not. `_allow_delivery` in walker_routes already recorded why a driver
    must not — "logistics role, does not walk blocks or assess difficulty" — and
    the operator's framing was that walkers are the walking banks for this data.
    """

    def test_walkers_can_contribute_field_agreement(self):
        assert "walker" in _FIELD_VERIFIERS, (
            "walkers cannot confirm — they walk the blocks and are the largest "
            "source of this data; excluding them was the original bug"
        )

    @pytest.mark.parametrize("role", ["walker", "trainer", "trainee"])
    def test_delivery_staff_weigh_one(self, role):
        assert _verify_weight(role) == 1

    def test_two_walkers_reach_the_review_threshold(self):
        assert _verify_weight("walker") * 2 >= _REVIEW_THRESHOLD

    def test_one_walker_does_not(self):
        assert _verify_weight("walker") < _REVIEW_THRESHOLD, (
            "a single walker surfaces the record for review with no second "
            "observation"
        )

    def test_a_captain_carries_the_two_walkers(self):
        assert _verify_weight("captain") >= _REVIEW_THRESHOLD, (
            "a captain's observation no longer replaces the two walkers it is "
            "meant to be worth"
        )

    def test_drivers_are_in_neither_stage(self):
        # The correction that prompted this rewrite.
        assert "driver" not in _FIELD_VERIFIERS, (
            "a driver can contribute field agreement — but they do not walk "
            "the block, which is the whole basis for assessing a building "
            "(_allow_delivery says so)"
        )
        assert "driver" not in _SIGNOFF_ROLES, (
            "a driver can sign off a building type"
        )

    def test_signoff_is_route_lead_or_oversight(self):
        assert _SIGNOFF_ROLES == {
            "captain", "dispatch", "field_supervisor", "management", "admin",
        }

    def test_walkers_cannot_sign_off(self):
        # They supply evidence; they do not rule on it.
        assert "walker" not in _SIGNOFF_ROLES

    def test_weight_defaults_safe_for_an_unknown_role(self):
        # A new role must not silently inherit captain-level weight.
        assert _verify_weight("some_new_role") == 1
        assert _verify_weight(None) == 1


class TestStateMachine:
    """pending → review → verified, and what each transition means."""

    def test_field_agreement_reaches_review_not_verified(self):
        src = _verify_src()
        assert 'profile.building_type_status = "review"' in src, (
            "two walkers agreeing verifies the record outright — it should "
            "SURFACE it for a captain or dispatch to sign off"
        )

    def test_only_a_signoff_reaches_verified(self):
        src = _verify_src()
        i = src.index("if is_signoff:")
        assert 'profile.building_type_status = "verified"' in src[i:i + 200], (
            "`verified` is set outside the sign-off branch, so field agreement "
            "alone can produce it"
        )

    def test_signoff_does_not_inflate_the_field_count(self):
        # Sign-off is a different STAGE, not more agreement. Letting it add
        # leaves walker+walker+captain at 4, which reads as "four people
        # agreed" — a number a later reader would reasonably trust.
        src = _verify_src()
        i = src.index("if is_signoff:")
        assert "profile.building_type_agreement_count = _REVIEW_THRESHOLD" in src[i:i+400], (
            "the sign-off adds its weight to the field count, so the total "
            "drifts past the threshold and stops meaning anything"
        )

    def test_signoff_requires_the_review_state(self):
        src = _verify_src()
        assert 'profile.building_type_status == "review"' in src, (
            "a route lead can sign off a record the field has not agreed on"
        )

    def test_a_captain_submission_lands_in_review(self):
        src = (BACKEND / "app" / "routers" / "building_profiles.py").read_text(encoding="utf-8")
        i = src.index("def submit_building_profile(")
        body = src[i:src.index("\n@router.", i)]
        assert '"review" if _verify_weight(caller.role) >= _REVIEW_THRESHOLD' in body, (
            "a captain's own submission does not reach review, so their "
            "observation is worth less on submit than on confirm"
        )

    def test_submission_records_its_own_verification_row(self):
        # Or the counter and the rows disagree: count=1 with no row explaining
        # where it came from, and D3 cannot see the submitter.
        src = (BACKEND / "app" / "routers" / "building_profiles.py").read_text(encoding="utf-8")
        i = src.index("def submit_building_profile(")
        body = src[i:src.index("\n@router.", i)]
        assert "BuildingProfileVerification(" in body


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
        for reason in ("own_submission", "already_verified",
                       "not_a_field_verifier", "awaiting_signoff"):
            assert f'"{reason}"' in src, (
                f"{reason} is not distinguishable, so the UI shows a live "
                "button that 403s instead of explaining itself"
            )

    def test_fields_are_optional_so_read_paths_are_unaffected(self):
        # Endpoints that do not resolve per-caller state leave them None and the
        # client falls back to a plain count.
        src = (BACKEND / "app" / "schemas" / "location_profile.py").read_text(encoding="utf-8")
        assert "remaining_weight:   Optional[int] = None" in src


class TestReviewQueueIsReachable:
    """A `review` state nobody can see is a state that does not exist.

    ADR-276 D1 made two walkers agreeing produce `review` and asked a captain
    to sign it off — but `GET /building-profiles/` was gated `_allow_dispatch`,
    so a captain could not list profiles at all. They could sign off only a
    record whose id someone handed them. The queue lived in the data and
    nowhere in the product.
    """

    def _list_src(self) -> str:
        text = (BACKEND / "app" / "routers" / "building_profiles.py").read_text(encoding="utf-8")
        i = text.index("def list_building_profiles(")
        return text[i:text.index("\n@router.", i)]

    def test_the_list_is_readable_by_anyone_who_may_verify(self):
        src = self._list_src()
        assert "Depends(_allow_verify)" in src, (
            "the profile list is not readable by the people asked to sign "
            "records off — a captain cannot find their own queue"
        )

    def test_status_filter_exists(self):
        src = self._list_src()
        assert 'alias="status"' in src, "no way to ask for just the review queue"
        assert 'BuildingProfile.building_type_status == status_filter' in src

    def test_unknown_status_is_rejected(self):
        # A typo'd filter silently returning everything would look like an
        # empty queue is a full one.
        src = self._list_src()
        assert '"pending", "review", "verified", "locked"' in src
        assert "HTTP_422_UNPROCESSABLE_CONTENT" in src

    def test_web_surfaces_the_queue(self):
        page = (BACKEND.parent / "frontend" / "src" / "pages"
                / "BuildingProfiles.tsx").read_text(encoding="utf-8")
        assert "reviewCount" in page, "no count of records awaiting sign-off"
        assert "Needs sign-off" in page, "the queue has no visible tile"

    def test_a_captain_lands_on_the_queue(self):
        # That queue IS their job on this page; making them find it is friction
        # with no upside.
        page = (BACKEND.parent / "frontend" / "src" / "pages"
                / "BuildingProfiles.tsx").read_text(encoding="utf-8")
        assert "isCaptain ? 'review' : 'all'" in page, (
            "a captain opens the page on 'all' and must hunt for the records "
            "waiting on them"
        )

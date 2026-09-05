"""The MFA grace clock and the tiers that use it (ADR-377 D2).

The deadline rule is a pure function on purpose: it is consulted from the /me
payload, the enrolment nudge, and eventually the PreAuthentication trigger, and
three copies of a deadline drift into three different deadlines.

Two findings from the ADR-377 scratch-pool probe shape what is tested here:

  - `UserMFASettingList` reads None on an account Cognito still challenges under
    MfaConfiguration=ON, because the associated token (not the preference flag)
    is what ON enforces. So this signal answers "should we nudge" and NOT "are
    they protected".
  - Cognito holds exactly one software token per user, so the "2-3 devices"
    requirement is about REMEMBERED DEVICES, not multiple factors.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.services.mfa_status import (
    DEFAULT_MFA_GRACE_DAYS,
    MFA_FIELD_ROLES,
    MFA_PRIVILEGED_ROLES,
    evaluate,
    is_enrolled,
    tier_for,
)

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)


class TestTiers:
    @pytest.mark.parametrize("role", sorted(MFA_PRIVILEGED_ROLES))
    def test_privileged_roles_have_no_grace_period(self, role):
        s = evaluate(role=role, enrolled=False, grace_started_at=None, now=NOW)
        assert s.tier == "privileged"
        assert s.blocked is True, f"{role} must enrol before first use"
        assert s.grace_days_total == 0

    @pytest.mark.parametrize("role", sorted(MFA_FIELD_ROLES))
    def test_field_roles_get_the_full_window_on_day_zero(self, role):
        s = evaluate(role=role, enrolled=False, grace_started_at=None, now=NOW)
        assert s.tier == "field"
        assert s.blocked is False
        assert s.days_remaining == DEFAULT_MFA_GRACE_DAYS

    def test_super_admin_is_privileged(self):
        """employees.PRIVILEGED_ROLES omits super_admin; borrowing it would have
        put the highest-privilege account on the FIELD grace period."""
        assert "super_admin" in MFA_PRIVILEGED_ROLES
        assert tier_for("super_admin") == "privileged"

    def test_captain_and_field_supervisor_are_field(self):
        """employees.FIELD_ROLES omits both -- they would have fallen to 'none'
        and never been asked for a factor at all."""
        for r in ("captain", "field_supervisor", "driver_trainee"):
            assert tier_for(r) == "field", f"{r} fell out of both tiers"

    def test_an_unknown_role_is_not_silently_required(self):
        s = evaluate(role="contractor", enrolled=False, grace_started_at=None, now=NOW)
        assert s.tier == "none" and s.required is False and s.blocked is False


class TestTheDeadline:
    def test_the_day_before_expiry_still_works(self):
        s = evaluate(role="walker", enrolled=False,
                     grace_started_at=NOW - timedelta(days=13), now=NOW)
        assert s.blocked is False
        assert s.days_remaining == 1

    def test_the_day_after_expiry_blocks(self):
        s = evaluate(role="walker", enrolled=False,
                     grace_started_at=NOW - timedelta(days=15), now=NOW)
        assert s.blocked is True
        assert s.days_remaining == 0

    def test_exactly_at_the_boundary_blocks(self):
        s = evaluate(role="walker", enrolled=False,
                     grace_started_at=NOW - timedelta(days=DEFAULT_MFA_GRACE_DAYS), now=NOW)
        assert s.blocked is True, "the deadline is inclusive; 14 days means 14"

    def test_a_partial_day_rounds_up(self):
        """0.2 days left must read '1 day', not '0' on an account that works --
        showing 0 while letting them in is what makes people ignore the banner."""
        s = evaluate(role="walker", enrolled=False,
                     grace_started_at=NOW - timedelta(days=13, hours=20), now=NOW)
        assert s.days_remaining == 1 and s.blocked is False

    def test_a_naive_timestamp_does_not_raise(self):
        """A DB that drops tzinfo must not throw inside a sign-in path."""
        naive = (NOW - timedelta(days=3)).replace(tzinfo=None)
        s = evaluate(role="walker", enrolled=False, grace_started_at=naive, now=NOW)
        assert s.days_remaining == 11 and s.blocked is False

    def test_enrolling_clears_the_deadline_entirely(self):
        s = evaluate(role="walker", enrolled=True,
                     grace_started_at=NOW - timedelta(days=99), now=NOW)
        assert s.blocked is False and s.days_remaining is None

    def test_an_enrolled_privileged_user_is_not_blocked(self):
        s = evaluate(role="admin", enrolled=True, grace_started_at=None, now=NOW)
        assert s.blocked is False

    def test_the_window_is_configurable(self):
        s = evaluate(role="walker", enrolled=False,
                     grace_started_at=NOW - timedelta(days=8), grace_days=7, now=NOW)
        assert s.blocked is True, "a tenant-configured shorter window must apply"


class TestFailureIsNotLockout:
    def test_unreadable_enrolment_returns_none_not_false(self):
        """False means 'not enrolled' and, past the deadline, BLOCKS. An AWS
        hiccup must not be able to lock out the whole company."""
        assert is_enrolled(None, None) is None


class TestAMachineIsNotAUser:
    """ADR-374: a MachineCaller has no role, no cognito_sub, no grace column.

    Reaching for any of them is the AttributeError that 500'd the bot's morning
    fetch. This endpoint takes `get_caller_employee`, which admits machines, so
    it needs the guard even though a bot has no reason to call it.
    """

    def test_a_machine_gets_403_not_a_500(self):
        import uuid

        from fastapi import HTTPException

        from app.api.deps import MachineCaller
        from app.routers.employees import get_my_mfa_status

        machine = MachineCaller(id="bot", company_id=uuid.uuid4(), name="asheflow.bot")
        with pytest.raises(HTTPException) as exc:
            get_my_mfa_status(
                db=None, caller=machine,
                # A machine token carries scopes, never cognito_groups.
                current_user={"machine_scopes": {"asheflow.bot/dispatch.read"}},
            )
        assert exc.value.status_code == 403
        assert "machine" in exc.value.detail.lower()


class TestCognitoGroupsOutrankTheEmployeeRole:
    """`super_admin` and `platform_support` are NOT in Employee.VALID_ROLES.

    A DB constraint rejects them, so they can only ever arrive as Cognito
    groups. Classifying by `Employee.role` alone makes two of the five
    privileged roles unreachable.

    Found on PROD: `adon` is `super_admin` in Cognito and `trainee` on its
    Employee row. Role-only classification put the platform's highest-privilege
    account on the FIELD tier with a 14-day grace period -- the exact inversion
    the tiering exists to prevent.
    """

    def test_super_admin_is_not_a_valid_employee_role(self):
        """The premise. If this ever changes, the precedence below can be
        revisited -- but until then the group is the only signal."""
        from app.models.employee import VALID_ROLES

        assert "super_admin" not in VALID_ROLES
        assert "platform_support" not in VALID_ROLES

    def test_the_group_promotes_a_field_role_to_privileged(self):
        assert tier_for("trainee", {"super_admin"}) == "privileged"
        assert tier_for("walker", {"platform_support"}) == "privileged"

    def test_the_prod_adon_case_end_to_end(self):
        """super_admin group + trainee row must get NO grace period."""
        s = evaluate(role="trainee", enrolled=False, grace_started_at=None,
                     groups={"super_admin"}, now=NOW)
        assert s.tier == "privileged"
        assert s.grace_days_total == 0
        assert s.blocked is True, (
            "a super_admin must enrol before first use, not get 14 days"
        )

    def test_a_missing_group_never_demotes(self):
        """Escalation only. A dispatch employee whose groups did not come
        through keeps the tier their role implies."""
        assert tier_for("dispatch", set()) == "privileged"
        assert tier_for("dispatch", None) == "privileged"

    def test_an_unrelated_group_changes_nothing(self):
        assert tier_for("walker", {"some_other_group"}) == "field"

    def test_the_endpoint_passes_groups_not_just_the_role(self):
        import inspect

        from app.routers.employees import get_my_mfa_status

        src = inspect.getsource(get_my_mfa_status)
        assert 'current_user.get("cognito_groups", [])' in src, (
            "the endpoint must read Cognito groups, or super_admin lands on "
            "the field tier"
        )
        # Every evaluate() call must classify the same way. Counting `groups=`
        # rather than a literal, because the value is now a local -- an earlier
        # version of this test asserted on the inlined expression and broke on a
        # refactor that changed nothing about the behaviour.
        # EVERY evaluate() call must be classified the same way. Counting
        # `groups=groups` rather than an inlined expression: an earlier version
        # asserted on the literal and broke on a refactor that hoisted it to a
        # local, changing nothing about behaviour.
        assert src.count("evaluate(") == src.count("groups=groups"), (
            f"{src.count('evaluate(')} evaluate() call(s) but only "
            f"{src.count('groups=groups')} pass groups= -- one path classifies "
            f"by role alone, which puts super_admin on the field tier"
        )


class TestAPlatformAccountHasNoEmployeeRow:
    """super_admin and platform_support are NOT staff.

    They have no Employee row by design -- putting one in the roster adds a
    fake person to headcount and to every name lookup. But the endpoint used
    `get_caller_employee`, which 403s without a row, so it refused exactly the
    accounts the privileged tier exists to protect.

    Found on prod: deleting `adon`'s stray roster row made /me/mfa-status
    refuse the platform owner.
    """

    def _call(self, groups, enrolled=True):
        from unittest.mock import patch

        from app.routers.employees import get_my_mfa_status

        with patch("app.services.mfa_status.is_enrolled", return_value=enrolled):
            return get_my_mfa_status(
                db=None, caller=None,
                current_user={"cognito_groups": groups, "id": "s", "username": "u"},
            )

    def test_a_super_admin_with_no_row_is_served(self):
        out = self._call(["super_admin"])
        assert out["tier"] == "privileged"
        assert out["blocked"] is False, "an enrolled super_admin must not be blocked"

    def test_platform_support_with_no_row_is_served(self):
        assert self._call(["platform_support"])["tier"] == "privileged"

    def test_an_unenrolled_super_admin_with_no_row_is_blocked(self):
        """No grace period for the privileged tier, row or no row."""
        out = self._call(["super_admin"], enrolled=False)
        assert out["blocked"] is True and out["grace_days_total"] == 0

    def test_a_non_privileged_caller_with_no_row_still_403s(self):
        """The 403 protects against a ghost account submitting as real staff.
        Only platform groups may skip the roster."""
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            self._call(["walker"])
        assert exc.value.status_code == 403

    def test_unreachable_cognito_does_not_block_a_platform_account(self):
        """is_enrolled returns None when AWS cannot be read. That must not read
        as 'not enrolled' and lock the platform owner out."""
        out = self._call(["super_admin"], enrolled=None)
        assert out["blocked"] is False


class TestBothClientsCallItAndAgreeOnTheShape:
    """The endpoint has SIDE EFFECTS, so a client that never calls it silently
    disables the feature: the grace clock is never stamped and device eviction
    never runs. That is how this shipped and sat inert until 2026-09-05.

    Mobile matters more than web for the clock -- a walker may never open the
    web app, so their 14-day window would otherwise start the day someone
    finally signs them in on a desktop.
    """

    import re
    from pathlib import Path

    ROOT = Path(__file__).resolve().parents[3]
    WEB = ROOT / "frontend" / "src" / "contexts" / "AuthContext.tsx"
    MOBILE = ROOT / "mobile" / "src" / "contexts" / "AuthContext.tsx"
    TYPES = ROOT / "frontend" / "src" / "api" / "types.ts"

    def test_the_web_client_calls_it_after_sign_in(self):
        assert "/employees/me/mfa-status" in self.WEB.read_text(), (
            "the web client stopped calling it -- the grace clock and device "
            "eviction are side effects of that GET"
        )

    def test_the_mobile_client_calls_it_after_sign_in(self):
        assert "/employees/me/mfa-status" in self.MOBILE.read_text(), (
            "mobile stopped calling it -- a walker who never opens the web app "
            "would never start their grace window"
        )

    def test_neither_client_blocks_sign_in_on_it(self):
        """A status banner is worth nothing if failing to fetch it stops a
        walker starting their shift at 05:00."""
        for path in (self.WEB, self.MOBILE):
            src = path.read_text()
            # The LAST occurrence, not the first. Mobile documents the endpoint
            # in a docstring above the call, so `.index()` found the comment and
            # searched around prose instead of code -- the same trap as
            # ADR-378's watch-list test.
            i = src.rindex("/employees/me/mfa-status")
            window = src[max(0, i - 700): i + 400]
            # Strip comments first. A mutant that replaced the handler with
            # `finally { /* no catch */ }` survived because the WORD catch was
            # still there -- in a comment saying it had been removed.
            code = self.re.sub(r"/\*.*?\*/", "", window, flags=self.re.S)
            code = self.re.sub(r"//.*", "", code)
            assert (".catch(" in code) or ("} catch" in code), (
                f"{path.name} does not swallow a failed MFA status fetch -- a "
                f"walker must not be blocked from their shift by a status call"
            )

    def test_the_two_client_type_declarations_agree(self):
        """Mobile has no shared types file, so it declares its own copy. Two
        copies drift; this fails when they do."""
        def fields(text, marker):
            body = text.split(marker)[1].split("};")[0]
            return set(self.re.findall(r"^\s*(\w+)\??:", body, self.re.M))

        web = fields(self.TYPES.read_text(), "export interface MfaStatus {")
        mob = fields(self.MOBILE.read_text(), "export type MfaStatus = {")
        assert web == mob, f"client MfaStatus types drifted: web-only={web - mob}, mobile-only={mob - web}"

    def test_the_client_types_match_the_endpoint_response(self):
        from unittest.mock import patch

        from app.routers.employees import get_my_mfa_status

        def fields(text, marker):
            body = text.split(marker)[1].split("};")[0]
            return set(self.re.findall(r"^\s*(\w+)\??:", body, self.re.M))

        with patch("app.services.mfa_status.is_enrolled", return_value=True):
            out = get_my_mfa_status(
                db=None, caller=None,
                current_user={"cognito_groups": ["super_admin"], "id": "s", "username": "u"},
            )
        assert set(out.keys()) == fields(self.TYPES.read_text(), "export interface MfaStatus {")

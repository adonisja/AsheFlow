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
            get_my_mfa_status(db=None, caller=machine)
        assert exc.value.status_code == 403
        assert "machine" in exc.value.detail.lower()

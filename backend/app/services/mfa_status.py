"""Who must have MFA, and by when (ADR-377 D2).

One place answers "is this person enrolled, and how long do they have", because
the question is asked from three surfaces -- the /me payload, the enrolment
nudge, and eventually the PreAuthentication trigger -- and three copies of a
deadline rule drift into three different deadlines.

The tiers are spelled out here rather than imported from employees.py: that
module's PRIVILEGED_ROLES is {management, admin, dispatch}, which omits
super_admin and platform_support, and its FIELD_ROLES omits captain,
driver_trainee and field_supervisor. Borrowing an incomplete set would silently
put a super_admin on the field tier's grace period -- the opposite of intended.
"""
from __future__ import annotations

import math

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

# Enrol before first use. No grace period: these accounts are salaried, sign in
# daily, and hold the access worth protecting.
MFA_PRIVILEGED_ROLES = frozenset({
    "super_admin", "admin", "management", "dispatch", "platform_support",
})

# Nudged from first sign-in, blocked when the window closes.
MFA_FIELD_ROLES = frozenset({
    "walker", "driver", "trainer", "captain", "trainee",
    "driver_trainee", "field_supervisor",
})

# 14, not 7. Matches Microsoft's security-defaults window, and survives a
# part-time roster: a 7-day clock can expire BETWEEN two shifts for someone
# working four shifts a fortnight, so they meet the wall on a morning they were
# trying to work.
DEFAULT_MFA_GRACE_DAYS = 14


@dataclass(frozen=True)
class MfaStatus:
    """What a client needs to render the nudge, and nothing more."""

    required: bool          # does this role need a factor at all
    enrolled: bool          # do they have one now
    tier: str               # "privileged" | "field" | "none"
    grace_days_total: int    # 0 for privileged
    days_remaining: Optional[int]   # None when not applicable
    blocked: bool           # must enrol before continuing

    def as_dict(self) -> dict:
        return {
            "required": self.required,
            "enrolled": self.enrolled,
            "tier": self.tier,
            "grace_days_total": self.grace_days_total,
            "days_remaining": self.days_remaining,
            "blocked": self.blocked,
        }


def tier_for(role: str, groups: Optional[set[str]] = None) -> str:
    """Which tier this caller is in.

    `groups` are the Cognito groups, and they take PRECEDENCE over the Employee
    role. That is not a nicety -- `super_admin` and `platform_support` are NOT
    in Employee.VALID_ROLES and a DB constraint rejects them, so they can only
    ever arrive as groups. Reading `Employee.role` alone makes two of the five
    privileged roles unreachable.

    Measured on prod: `adon` is `super_admin` in Cognito and `trainee` on its
    Employee row. Role-only classification put the platform's highest-privilege
    account on the FIELD tier with a 14-day grace period -- the exact inversion
    this tiering exists to prevent.

    Escalation only. A group can promote a caller to privileged; it never
    demotes one, so a dispatch employee whose groups are missing keeps their
    tier from the role.
    """
    if groups and (groups & MFA_PRIVILEGED_ROLES):
        return "privileged"
    if role in MFA_PRIVILEGED_ROLES:
        return "privileged"
    if role in MFA_FIELD_ROLES:
        return "field"
    return "none"


def evaluate(
    *,
    role: str,
    enrolled: bool,
    grace_started_at: Optional[datetime],
    grace_days: int = DEFAULT_MFA_GRACE_DAYS,
    now: Optional[datetime] = None,
    groups: Optional[set[str]] = None,
) -> MfaStatus:
    """Pure function -- no DB, no Cognito -- so the deadline rule is testable.

    `enrolled` comes from Cognito, not from our tables. We do not mirror
    enrolment state locally: a mirror goes stale the moment someone enrols on
    another device, and a stale "not enrolled" locks out a person who did
    everything right.
    """
    now = now or datetime.now(timezone.utc)
    t = tier_for(role, groups)

    if t == "none":
        return MfaStatus(False, enrolled, t, 0, None, False)

    if enrolled:
        return MfaStatus(True, True, t, 0 if t == "privileged" else grace_days,
                         None, False)

    if t == "privileged":
        # No window. Blocked until enrolled.
        return MfaStatus(True, False, t, 0, 0, True)

    # Field, not yet enrolled.
    if grace_started_at is None:
        # The clock has not started -- this sign-in starts it. Full window.
        return MfaStatus(True, False, t, grace_days, grace_days, False)

    # Compare in UTC. A naive value read back from a DB that dropped the tzinfo
    # would otherwise raise on subtraction, and an exception here fails a
    # sign-in path.
    started = (grace_started_at.replace(tzinfo=timezone.utc)
               if grace_started_at.tzinfo is None else grace_started_at)
    deadline = started + timedelta(days=grace_days)
    remaining = (deadline - now).total_seconds() / 86400.0

    if remaining <= 0:
        return MfaStatus(True, False, t, grace_days, 0, True)

    # Round UP: with 0.2 days left a user should read "1 day", not "0 days" on
    # an account that still works. Showing 0 while letting them in is the
    # contradiction that makes people ignore the banner.
    return MfaStatus(True, False, t, grace_days, math.ceil(remaining), False)


def is_enrolled(cognito_sub: Optional[str], username: Optional[str]) -> Optional[bool]:
    """Ask Cognito whether this user has a factor. None means "could not tell".

    Returns None rather than False on any failure. False means "not enrolled"
    and, past the deadline, that BLOCKS a sign-in -- so an AWS hiccup must not
    be able to lock out the whole company. Callers treat None as "do not block".

    Reads `UserMFASettingList`, but note what the ADR-377 probe found: under
    MfaConfiguration=ON that list can read None on an account Cognito still
    challenges, because the associated token -- not the preference flag -- is
    what ON enforces. So this is the right signal for "should we nudge them",
    and the WRONG signal for "are they protected". Do not repurpose it.
    """
    import logging

    import boto3
    from botocore.exceptions import BotoCoreError, ClientError

    from app.core.config import settings

    logger = logging.getLogger(__name__)
    if not (username or cognito_sub):
        return None
    try:
        client = boto3.client("cognito-idp", region_name=settings.aws_region)
        resp = client.admin_get_user(
            UserPoolId=settings.aws_cognito_user_pool_id,
            Username=username or cognito_sub,
        )
    except (ClientError, BotoCoreError) as exc:
        # No detail in any user-facing surface; the caller degrades to "unknown".
        logger.warning("mfa_status: could not read enrolment: %s", type(exc).__name__)
        return None
    return bool(resp.get("UserMFASettingList"))

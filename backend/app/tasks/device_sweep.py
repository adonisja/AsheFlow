"""Bound how long a remembered device may skip the MFA challenge (ADR-385).

Registered in celery_app.py beat_schedule — runs 01:37 Eastern for every tier,
and hourly for the privileged tier only (ADR-539 D2), so "24 hours since last
use" holds within an hour rather than up to ~48. ADR-540 then changed the
rule to "since the device last passed MFA" (DeviceCreateDate) for both tiers
-- 12h privileged, 7 days field -- so a device in daily use is re-challenged.

WHO IS SWEPT (ADR-539 D1)
Employee rows, AND the members of the platform groups (super_admin,
platform_support) in Cognito. A platform account has NO Employee row --
those roles are not valid Employee.role values -- so a sweep that walks only
Employee rows never sees the platform's highest-privilege accounts. That is
exactly what happened: adon's remembered devices outlived the 24h limit by
weeks on both pools until 2026-10-18.

WHY THIS EXISTS AND `MfaConfiguration: ON` DOES NOT
ADR-377 planned to flip the pool to `ON`. That is mutually exclusive with the
field grace period: under `ON`, Cognito returns MFA_SETUP to an unenrolled user
BEFORE any of our code runs, so the 14-day window, the banner and evaluate() all
become unreachable behind a token Cognito refuses to issue. `MfaConfiguration`
has no per-group dimension and cannot express "daily for admins, weekly for
field". Device tracking can, so cadence lives here instead.

Forgetting a device does not sign anyone out. It means the NEXT sign-in from
that device is challenged — which is exactly an interval.

TIMEZONE: EASTERN IS ASSUMED, DELIBERATELY
Celery Beat runs a single timezone (`America/New_York`), while Company.timezone
is per-company. sort_rollup handles the general case by ticking hourly and acting
when it is the right local hour for each company. That was rejected here as
premature: the operation is NYC-only and the hourly tick buys correctness for a
tenant that does not exist.

The assumption is checked rather than hidden. Any company not on Eastern time is
logged as a warning, because the failure is silent and unpleasant: a Pacific DSP
would have devices forgotten at 22:00 local, mid-evening, with drivers still
working — the exact tedium the 7-day window exists to prevent. Migrating means
changing the schedule to hourly and this guard to a comparison; the tier logic
and the TTLs do not move.
"""
from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from app.celery_app import celery_app
from app.database import SessionLocal
from app.core.config import settings
from app.models.company import Company
from app.models.employee import Employee
from app.services import device_fleet, mfa_status
from app.services.integration_alerts import raise_platform_alert

logger = logging.getLogger(__name__)

SWEEP_TIMEZONE = "America/New_York"

#: Cognito-only groups whose members have no Employee row (ADR-539 D1).
PLATFORM_GROUPS = ("super_admin", "platform_support")

#: ADR-549 D1. Also no Employee row, but swept on the FIELD timing (7 days
#: since the last MFA): surveyors enrol before use like platform staff, yet
#: re-challenging a phone every 12 h fights an outdoor walking job.
SURVEYOR_GROUP = "surveyor"


def _cognito_username(employee: Employee) -> str | None:
    """The Username this employee's Cognito account actually has (ADR-380 F7).

    Mirrors routers.employees.cognito_username_for. Imported rather than
    duplicated would be better, but that module pulls the FastAPI dependency
    graph; this rule is two lines and the ADR names both sites.

    NOT the Discord id and NOT the cognito_sub — passing either produces
    UserNotFoundException, and device_fleet fails soft, so the sweep would report
    success while forgetting nothing. That is precisely how eviction stayed
    broken in production until 756c96e4.
    """
    return employee.username or employee.email


def _groups_for(username: str) -> set[str] | None:
    """This user's Cognito groups, or None if they cannot be read.

    None rather than an empty set on failure: tier_for treats groups as
    ESCALATION ONLY, so None falls back to the Employee role and a privileged
    user keeps their tier from `role` where it is present. An empty set would say
    the same thing, but None records that we did not know rather than that there
    were none.
    """
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError

    try:
        client = boto3.client("cognito-idp", region_name=settings.aws_region)
        resp = client.admin_list_groups_for_user(
            UserPoolId=settings.aws_cognito_user_pool_id,
            Username=username,
            Limit=60,
        )
        return {g["GroupName"] for g in resp.get("Groups", [])}
    except (ClientError, BotoCoreError) as exc:
        logger.warning(
            "device sweep: could not read groups: %s", type(exc).__name__,
        )
        return None


def _platform_usernames(groups: tuple[str, ...] = PLATFORM_GROUPS) -> set[str] | None:
    """Usernames in the platform groups, or None if they cannot be listed.

    None, not an empty set: "could not read" must be distinguishable in the
    task result from "the platform has no such accounts".
    """
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError

    names: set[str] = set()
    try:
        client = boto3.client("cognito-idp", region_name=settings.aws_region)
        paginator = client.get_paginator("list_users_in_group")
        for group in groups:
            for page in paginator.paginate(
                UserPoolId=settings.aws_cognito_user_pool_id, GroupName=group,
            ):
                names.update(u["Username"] for u in page.get("Users", []))
    except (ClientError, BotoCoreError) as exc:
        logger.warning(
            "device sweep: could not list platform groups: %s", type(exc).__name__,
        )
        return None
    return names


@celery_app.task(name="app.tasks.device_sweep.sweep_stale_devices")
def sweep_stale_devices(privileged_only: bool = False) -> dict:
    """Forget remembered devices past their tier's TTL.

    Privileged: 12h, field: 7 days, both since the last MFA (ADR-540). `privileged_only` is the hourly run
    (ADR-539 D2): same code, field accounts skipped, so the two schedules
    cannot drift apart. Returns a summary for the task result so a run that
    forgot nothing is distinguishable from one that never ran.
    """
    db = SessionLocal()
    checked = forgotten = skipped = unprotected = 0
    platform_checked = 0
    seen: set[str] = set()
    try:
        # The timezone assumption, surfaced. Cheap, and it is the difference
        # between a future incident and a log line that already explains itself.
        for company in db.query(Company).filter(Company.is_active.is_(True)).all():
            if company.timezone and company.timezone != SWEEP_TIMEZONE:
                logger.warning(
                    "device sweep: company %s is on %s but the sweep is fixed to "
                    "%s (ADR-385) — its devices are being forgotten at the wrong "
                    "local hour; move the schedule to hourly per-company",
                    company.id, company.timezone, SWEEP_TIMEZONE,
                )

        # DELIBERATELY NOT company-scoped. ADR-115 D1 governs REQUEST paths,
        # where a caller must never see another tenant's rows. This is a
        # platform-wide scheduled job against a single shared Cognito pool, and
        # it must sweep every tenant -- the same shape as cleanup.py's expiry
        # jobs. There is no caller and therefore no caller.company_id to scope to.
        employees = (
            db.query(Employee)
            .filter(Employee.is_active.is_(True))
            .filter(Employee.cognito_sub.isnot(None))
            .all()
        )

        for emp in employees:
            username = _cognito_username(emp)
            if not username:
                # No resolvable Cognito Username: never registered, or an
                # employee row that predates onboarding. Nothing to sweep.
                skipped += 1
                continue

            seen.add(username)

            # Groups, not the role alone. `super_admin` and `platform_support`
            # are NOT in Employee.VALID_ROLES -- a DB constraint rejects them --
            # so they arrive ONLY as Cognito groups. A platform account that
            # also holds an Employee row (adon once did, as `trainee`) would get
            # the 7-day FIELD ttl from its role alone (ADR-377 D2). One with no
            # row at all is covered by the platform-group pass below (ADR-539).
            tier = mfa_status.tier_for(emp.role, groups=_groups_for(username))
            if tier == "none" or (privileged_only and tier != "privileged"):
                skipped += 1
                continue

            # ADR-386 layer 2 — the BACKSTOP, not the mechanism. Unenrolment
            # cannot be refused (ADR-377 D1: the client calls Cognito directly
            # with a scope that cannot be stripped), so a privileged account
            # sitting with no factor is either an unenrolment we did not catch
            # or an enrolment that never happened. Both want a human.
            #
            # ADR-387 responds to the SetUserMFAPreference event in seconds; this
            # catches whatever that path missed, within a day.
            #
            # `is False`, not `not`: is_enrolled returns None for "could not
            # tell", and an AWS hiccup is not an unprotected account (ADR-539 D3).
            if tier == "privileged" and mfa_status.is_enrolled(
                emp.cognito_sub, username,
            ) is False:
                unprotected += 1
                raise_platform_alert(
                    db,
                    alert_type="mfa.privileged_unprotected",
                    company_id=emp.company_id,
                    # ADR-543 D2: name the account, one alert each.
                    subject_kind="employee",
                    subject_ref=username,
                    subject_role=emp.role,
                    message=(
                        "A privileged account has no MFA factor. If this was an "
                        "unenrolment it may indicate a compromised session "
                        "(ADR-386)."
                    ),
                    severity="critical",
                )

            # ADR-540: both tiers measured from the last MFA (DeviceCreateDate).
            privileged = tier == "privileged"
            ttl = (device_fleet.PRIVILEGED_CHALLENGE_TTL if privileged
                   else device_fleet.FIELD_DEVICE_TTL)

            checked += 1
            forgotten += device_fleet.forget_stale(
                username=username,
                pool_id=settings.aws_cognito_user_pool_id,
                region=settings.aws_region,
                ttl=ttl,
            )

        # ADR-539 D1 — platform accounts with no Employee row. Privileged by
        # definition (membership of a platform group IS the escalation).
        platform = _platform_usernames()
        for username in sorted((platform or set()) - seen):
            if mfa_status.is_enrolled(None, username) is False:
                unprotected += 1
                raise_platform_alert(
                    db,
                    alert_type="mfa.privileged_unprotected",
                    company_id=None,   # belongs to no tenant
                    subject_kind="platform",
                    subject_ref=username,
                    subject_role=next((g for g in PLATFORM_GROUPS
                                       if g in (_groups_for(username) or set())), "platform staff"),
                    message=(
                        "A platform account has no MFA factor. If this was an "
                        "unenrolment it may indicate a compromised session "
                        "(ADR-386)."
                    ),
                    severity="critical",
                )
            platform_checked += 1
            forgotten += device_fleet.forget_stale(
                username=username,
                pool_id=settings.aws_cognito_user_pool_id,
                region=settings.aws_region,
                ttl=device_fleet.PRIVILEGED_CHALLENGE_TTL,
            )

        # ADR-549 D1 — surveyors: field timing, so the daily run only. No
        # unprotected alert here: a newly invited surveyor is legitimately
        # unenrolled inside ADR-548's window, and the Lambda refuses them after
        # it, so an alert would be noise that trains people to ignore the
        # critical platform one above.
        surveyor_checked = 0
        surveyors = None
        if not privileged_only:
            surveyors = _platform_usernames((SURVEYOR_GROUP,))
            for username in sorted((surveyors or set()) - seen - (platform or set())):
                surveyor_checked += 1
                forgotten += device_fleet.forget_stale(
                    username=username,
                    pool_id=settings.aws_cognito_user_pool_id,
                    region=settings.aws_region,
                    ttl=device_fleet.FIELD_DEVICE_TTL,
                )

        if unprotected:
            db.commit()  # persist the alerts raised above

        logger.info(
            "device sweep%s: checked %d employee(s) and %d platform account(s), "
            "forgot %d stale device(s), skipped %d, %d privileged unprotected",
            " (privileged only)" if privileged_only else "",
            checked, platform_checked, forgotten, skipped, unprotected,
        )
        return {"checked": checked, "platform_checked": platform_checked,
                "surveyor_checked": surveyor_checked,
                "surveyor_group_read": None if privileged_only else surveyors is not None,
                "platform_groups_read": platform is not None,
                "privileged_only": privileged_only,
                "forgotten": forgotten, "skipped": skipped,
                "privileged_unprotected": unprotected,
                "ran_at": datetime.now(ZoneInfo(SWEEP_TIMEZONE)).isoformat()}
    finally:
        db.close()

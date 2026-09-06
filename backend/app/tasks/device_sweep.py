"""Bound how long a remembered device may skip the MFA challenge (ADR-385).

Registered in celery_app.py beat_schedule — runs 01:00 Eastern, when no DSP is
operating.

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

logger = logging.getLogger(__name__)

SWEEP_TIMEZONE = "America/New_York"


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


@celery_app.task(name="app.tasks.device_sweep.sweep_stale_devices")
def sweep_stale_devices() -> dict:
    """Forget remembered devices past their tier's TTL.

    Privileged: 24h. Field: 7 days. Returns a summary for the task result so a
    run that forgot nothing is distinguishable from one that never ran.
    """
    db = SessionLocal()
    checked = forgotten = skipped = 0
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

            # Groups, not the role alone. `super_admin` and `platform_support`
            # are NOT in Employee.VALID_ROLES -- a DB constraint rejects them --
            # so they arrive ONLY as Cognito groups. Measured on prod: `adon` is
            # `super_admin` in Cognito and `trainee` on its Employee row, so
            # role-only classification would hand the platform's highest-privilege
            # account the 7-day FIELD ttl instead of 24h (ADR-377 D2).
            tier = mfa_status.tier_for(emp.role, groups=_groups_for(username))
            if tier == "none":
                skipped += 1
                continue

            ttl = (device_fleet.PRIVILEGED_DEVICE_TTL if tier == "privileged"
                   else device_fleet.FIELD_DEVICE_TTL)

            checked += 1
            forgotten += device_fleet.forget_stale(
                username=username,
                pool_id=settings.aws_cognito_user_pool_id,
                region=settings.aws_region,
                ttl=ttl,
            )

        logger.info(
            "device sweep: checked %d employee(s), forgot %d stale device(s), "
            "skipped %d", checked, forgotten, skipped,
        )
        return {"checked": checked, "forgotten": forgotten, "skipped": skipped,
                "ran_at": datetime.now(ZoneInfo(SWEEP_TIMEZONE)).isoformat()}
    finally:
        db.close()

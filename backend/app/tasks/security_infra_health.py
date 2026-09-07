"""Is the containment infrastructure actually working? (ADR-388)

Registered in celery_app.py beat_schedule — hourly at :07.

WHY THIS EXISTS
ADR-387's containment depends on a chain nothing was watching:

    Cognito -> CloudTrail trail -> EventBridge -> Lambda -> SNS -> a human

Break any link and unenrolments stop being contained, SILENTLY. That is not
hypothetical: the account's previous trail (TruEval-cloudTrail) reported
`IsLogging: true` for TWELVE MONTHS while writing to a bucket that had been
deleted. Anyone auditing "do we have CloudTrail coverage" would have seen a trail,
seen it logging, and said yes.

WHAT IT CHECKS, AND WHY EACH ONE
Reading `IsLogging` alone would have missed exactly that failure, so each check
looks at the EFFECT, not the status field:

  trail exists       a deleted trail is the loudest possible failure
  trail is logging   the status field, necessary but NOT sufficient
  no delivery error  LatestDeliveryError is where NoSuchBucket actually appeared
  delivery is recent a trail that last delivered a year ago is not working
  rule exists+enabled a disabled rule drops events with no error anywhere
  lambda exists      the target of that rule
  topic exists       where the alert goes
  topic has a subscriber  a topic with none publishes into the void
  we can CALL the containment APIs  a permission can be revoked, and the
                     application would not find out until a human clicks Reset

That last one matters more than it looks. The SNS topic was created and confirmed,
but an unconfirmed or deleted subscription leaves publishing "successful" and
nobody notified — the same green-while-blind shape as the trail.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from app.celery_app import celery_app
from app.core.config import settings
from app.database import SessionLocal
from app.services.integration_alerts import raise_platform_alert

logger = logging.getLogger(__name__)

SECURITY_INFRA_DEGRADED = "security_infra_degraded"

TRAIL_NAME = "AsheFlow-Trail"
RULE_NAME = "AsheFlow-MfaUnenrol"
FUNCTION_NAME = "AsheFlow-MfaUnenrolResponder"
TOPIC_NAME = "AsheFlow-SecurityAlerts"

# A trail delivers in batches, typically within ~15 minutes. Six hours is well
# past "slow" and comfortably short of "broken for a year", which is the failure
# this exists to catch.
MAX_DELIVERY_AGE = timedelta(hours=6)


def _check_trail(region: str) -> list[str]:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError

    problems: list[str] = []
    try:
        ct = boto3.client("cloudtrail", region_name=region)
        status = ct.get_trail_status(Name=TRAIL_NAME)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "ClientError")
        # TrailNotFoundException is the loudest case: containment is fully blind.
        problems.append(f"trail {TRAIL_NAME}: {code}")
        return problems
    except BotoCoreError as exc:
        problems.append(f"trail {TRAIL_NAME}: {type(exc).__name__}")
        return problems

    if not status.get("IsLogging"):
        problems.append(f"trail {TRAIL_NAME} is not logging")

    # THE check. `IsLogging: true` was true for the whole year TruEval's trail
    # was writing to a deleted bucket; this field is where NoSuchBucket appeared.
    err = status.get("LatestDeliveryError")
    if err:
        problems.append(f"trail {TRAIL_NAME} delivery error: {err}")

    last = status.get("LatestDeliveryTime")
    if last is None:
        problems.append(f"trail {TRAIL_NAME} has never delivered")
    else:
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - last
        if age > MAX_DELIVERY_AGE:
            problems.append(
                f"trail {TRAIL_NAME} last delivered {int(age.total_seconds() // 3600)}h ago"
            )
    return problems


def _check_rule_and_lambda(region: str) -> list[str]:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError

    problems: list[str] = []
    try:
        ev = boto3.client("events", region_name=region)
        rule = ev.describe_rule(Name=RULE_NAME)
        if rule.get("State") != "ENABLED":
            # A disabled rule drops every event and reports nothing anywhere.
            problems.append(f"rule {RULE_NAME} is {rule.get('State')}")
        targets = ev.list_targets_by_rule(Rule=RULE_NAME).get("Targets", [])
        if not targets:
            problems.append(f"rule {RULE_NAME} has no targets")
    except (ClientError, BotoCoreError) as exc:
        problems.append(f"rule {RULE_NAME}: {type(exc).__name__}")

    try:
        boto3.client("lambda", region_name=region).get_function_configuration(
            FunctionName=FUNCTION_NAME,
        )
    except (ClientError, BotoCoreError) as exc:
        problems.append(f"function {FUNCTION_NAME}: {type(exc).__name__}")
    return problems


def _check_topic(region: str) -> list[str]:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError

    problems: list[str] = []
    try:
        sns = boto3.client("sns", region_name=region)
        arn = None
        paginator = sns.get_paginator("list_topics")
        for page in paginator.paginate():
            for t in page.get("Topics", []):
                if t["TopicArn"].rsplit(":", 1)[-1] == TOPIC_NAME:
                    arn = t["TopicArn"]
                    break
            if arn:
                break
        if not arn:
            problems.append(f"topic {TOPIC_NAME} not found")
            return problems

        subs = sns.list_subscriptions_by_topic(TopicArn=arn).get("Subscriptions", [])
        # "PendingConfirmation" is a real subscription that delivers NOTHING.
        confirmed = [s for s in subs
                     if s.get("SubscriptionArn", "").startswith("arn:")]
        if not confirmed:
            problems.append(
                f"topic {TOPIC_NAME} has no confirmed subscribers — alerts go nowhere"
            )
    except (ClientError, BotoCoreError) as exc:
        problems.append(f"topic {TOPIC_NAME}: {type(exc).__name__}")
    return problems


def _check_containment_permissions(region: str, pool_id: str) -> list[str]:
    """Can this role actually PERFORM containment? (ADR-390)

    Every other check here verifies infrastructure EXISTS. This one verifies we
    are still ALLOWED to use it, which is a different failure and one that
    already happened: `admin_set_user_mfa_preference` shipped in application code
    without the matching IAM grant, and the gap surfaced only when a human clicked
    Reset and got a 502 (ADR-389).

    Nothing in CI can catch that. Every mock returns success for a call the
    production role cannot make.

    NON-MUTATING BY CONSTRUCTION. Each call targets a username that cannot exist,
    because IAM is evaluated BEFORE the user lookup:

        AccessDeniedException  -> the permission is gone            (a problem)
        UserNotFoundException  -> permitted, user absent as expected (fine)

    Verified against live Cognito before this was written. A probe that mutated a
    real account to test a permission would be a worse cure than the disease.
    """
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError

    # A name no real account can hold: Cognito usernames in this pool are
    # firstname.lastname or an email, and neither contains this sentinel.
    PROBE_USER = "asheflow-permission-probe-does-not-exist"

    problems: list[str] = []
    client = boto3.client("cognito-idp", region_name=region)

    probes = [
        ("AdminSetUserMFAPreference", lambda: client.admin_set_user_mfa_preference(
            UserPoolId=pool_id, Username=PROBE_USER,
            SoftwareTokenMfaSettings={"Enabled": False, "PreferredMfa": False})),
        ("AdminUserGlobalSignOut", lambda: client.admin_user_global_sign_out(
            UserPoolId=pool_id, Username=PROBE_USER)),
        ("AdminListDevices", lambda: client.admin_list_devices(
            UserPoolId=pool_id, Username=PROBE_USER, Limit=1)),
    ]

    for action, call in probes:
        try:
            call()
            # Reaching here would mean the sentinel user EXISTS, which is a
            # different problem worth surfacing rather than ignoring.
            problems.append(f"{action}: probe user unexpectedly exists")
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code == "UserNotFoundException":
                continue  # permitted, and nothing was changed
            if code in ("AccessDeniedException", "NotAuthorizedException"):
                problems.append(
                    f"{action}: {code} — containment cannot run (ADR-389)")
            else:
                problems.append(f"{action}: {code}")
        except BotoCoreError as exc:
            problems.append(f"{action}: {type(exc).__name__}")

    return problems


@celery_app.task(name="app.tasks.security_infra_health.check_security_infra")
def check_security_infra() -> dict:
    """Verify the ADR-387 containment chain, and alert super admins if it is broken.

    Returns a summary so a run that found nothing is distinguishable from one that
    never ran — the same reason the device sweep returns counts.
    """
    region = settings.aws_region
    problems: list[str] = []
    problems += _check_trail(region)
    problems += _check_rule_and_lambda(region)
    problems += _check_topic(region)
    problems += _check_containment_permissions(
        region, settings.aws_cognito_user_pool_id)

    if not problems:
        logger.info("security infra health: all checks passed")
        return {"healthy": True, "problems": []}

    db = SessionLocal()
    try:
        raise_platform_alert(
            db,
            alert_type=SECURITY_INFRA_DEGRADED,
            company_id=None,  # platform-wide: this is not one tenant's problem
            message=(
                "MFA unenrolment containment is degraded (ADR-387). "
                + "; ".join(problems)
            ),
            severity="critical",
        )
        db.commit()
    finally:
        db.close()

    logger.error("security infra health: %d problem(s): %s",
                 len(problems), "; ".join(problems))
    return {"healthy": False, "problems": problems}

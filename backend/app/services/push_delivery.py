"""Send a notification to a device, via SNS mobile push (ADR-487 D5).

WHY SNS AND NOT APNs/FCM DIRECTLY
=================================
Not for cost -- SNS charges per message where APNs and FCM are free. The
deciding factor is that **this repo already holds AWS credentials and nothing
else**: boto3 is in use for SES, Cognito, S3, Secrets Manager, CloudTrail,
EventBridge and Lambda. Calling APNs and FCM directly means two new credential
types, two new rotation stories, and two new ways for an integration to be
silently dead -- which is the failure ADR-323/324/337 spent three ADRs learning
to detect. SNS folds push into the one credential surface that already has a
health probe and an alerting path.

Verified rather than assumed: every SNS operation this needs is present in the
installed boto3 (1.43.72), so push adds **no Python dependency at all**.

DISABLED IS NOT BROKEN
======================
An empty platform ARN means "not set up yet" and is reported once, not per-send.
Registration still succeeds and stores the token with a NULL `endpoint_arn`, so
the day the ARN appears, `backfill_endpoints` can give every already-registered
device an endpoint without anyone re-installing the app.

Push is ADDITIVE. Everyone receives every notification in-app regardless; this
only decides whether a closed phone also buzzes. So every failure here is
logged and swallowed rather than raised into the caller's transaction -- a
broken push must never roll back the notification it was announcing.

THE ONLY RELIABLE INVALIDATION SIGNAL
=====================================
A user who deletes the app never tells us. APNs reports it on the next send, as
an SNS `EndpointDisabled` exception, and that is when the row is revoked. Age
alone is not a signal: a walker on holiday for three weeks has a perfectly good
token.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.device_token import DevicePlatform, DeviceToken

logger = logging.getLogger(__name__)

#: The Android notification channel every push is shown in.
#:
#: A CONTRACT with the app: mobile/android MainApplication.PUSH_CHANNEL_ID
#: creates a channel with this id, and mobile/firebase.json names it as FCM's
#: default. A mismatch does not error -- Android silently falls back to the
#: "Miscellaneous" channel, which a walker may have muted, so an injury alert
#: would arrive silently. test_adr487_d5_android_channel checks all three agree.
ANDROID_CHANNEL_ID = "alerts"

#: Reported once per process, not per send. An empty ARN is a configuration
#: state, and a log line per notification would bury the one that matters.
_warned_disabled: set[str] = set()


def platform_arn(platform: str) -> str:
    """The SNS platform application ARN for `platform`, or "" if disabled.

    STRIPPED, and that is not cosmetic. SSM Parameter Store refuses a genuinely
    empty `String` value, and `check_param_store_parity.py` requires the same
    parameter NAMES under /asheflow/staging/ and /asheflow/prod/ -- so the only
    way to have the parameter present but the feature off is a whitespace
    value. Unstripped, " " is truthy: `push_enabled()` would report True and
    every send would attempt a publish to a nonsense ARN, failing per
    notification instead of being cleanly disabled.

    That is the exact "disabled is not broken" posture this module is built on,
    defeated by one space. Found while writing the setup runbook, which had
    recommended a space for precisely this purpose.
    """
    if platform == DevicePlatform.IOS:
        return settings.sns_apns_platform_arn.strip()
    if platform == DevicePlatform.ANDROID:
        return settings.sns_fcm_platform_arn.strip()
    return ""


def push_enabled(platform: str | None = None) -> bool:
    """Is push configured -- for one platform, or for either?

    Used by the register endpoint to decide whether to attempt an SNS endpoint,
    and by the health probe. Deliberately a function rather than a module
    constant: settings are read at call time so a deploy that adds the ARN does
    not need a restart to be noticed by anything that asks.
    """
    if platform is not None:
        return bool(platform_arn(platform))
    # Via platform_arn so both paths strip. Reading the settings directly here
    # was the bug: " " is truthy.
    return bool(
        platform_arn(DevicePlatform.IOS) or platform_arn(DevicePlatform.ANDROID)
    )


def _sns():
    return boto3.client("sns", region_name=settings.aws_region)


def _note_disabled(platform: str) -> None:
    if platform in _warned_disabled:
        return
    _warned_disabled.add(platform)
    logger.info(
        "push: %s is not configured (sns_%s_platform_arn is empty), so devices "
        "register without an SNS endpoint and no push is sent. In-app delivery "
        "is unaffected.",
        platform, "apns" if platform == DevicePlatform.IOS else "fcm",
    )


def create_endpoint(device: DeviceToken) -> str | None:
    """Create or fetch this device's SNS platform endpoint.

    Returns the ARN, or None when the platform is disabled or SNS refuses.
    Never raises: a registration must succeed even with push unconfigured, or a
    sign-in would fail on an optional feature.
    """
    arn = platform_arn(device.platform)
    if not arn:
        _note_disabled(device.platform)
        return None

    try:
        resp = _sns().create_platform_endpoint(
            PlatformApplicationArn=arn,
            Token=device.token,
            # So an endpoint found in the SNS console can be traced back without
            # a database lookup. NOT the employee's name -- an SNS attribute is
            # outside every retention and redaction path this repo has
            # (ADR-221/499), and a name there would be a copy nothing can reach.
            CustomUserData=f"employee={device.employee_id} company={device.company_id}",
        )
        return resp["EndpointArn"]
    except (ClientError, BotoCoreError) as e:
        # type(e).__name__ only: a boto error's str() can echo the token, which
        # is a credential for delivering this person's notifications.
        logger.warning(
            "push: could not create an SNS endpoint for device %s (%s): %s",
            device.id, device.platform, type(e).__name__,
        )
        return None


def _payload(platform: str, title: str, body: str, data: dict) -> str:
    """The platform-specific envelope SNS expects.

    SNS requires a JSON string whose keys are platform names and whose values
    are themselves JSON strings -- a double encoding that is easy to get wrong
    and silently delivers nothing.
    """
    if platform == DevicePlatform.IOS:
        inner = {"aps": {"alert": {"title": title, "body": body}, "sound": "default"}}
        inner.update(data)
        return json.dumps({"default": body, "APNS": json.dumps(inner)})

    # The LEGACY payload shape, which SNS still accepts and converts to FCM HTTP
    # v1 itself (AWS docs, "Using the legacy payload structure to send messages
    # to the FCM v1 API", checked 2026-10-12). `android_channel_id` maps to v1's
    # android.notification.channel_id. The v1 shape (`fcmV1Message`) is only
    # needed for APNs headers or fcm_options, neither of which Android uses.
    #
    # FCM v1 requires every `data` value to be a STRING; a number or a nested
    # object is rejected as INVALID_ARGUMENT. Coerced here so a caller passing an
    # int id cannot silently fail delivery.
    inner = {
        "notification": {
            "title": title,
            "body": body,
            "android_channel_id": ANDROID_CHANNEL_ID,
        },
        "data": {k: str(v) for k, v in data.items()},
    }
    return json.dumps({"default": body, "GCM": json.dumps(inner)})


def send_to_device(db: Session, device: DeviceToken, *, title: str, body: str,
                   data: dict | None = None) -> bool:
    """Push one notification to one device. Returns whether it was sent.

    Revokes the row when SNS reports the endpoint disabled -- the only reliable
    signal that an app was deleted. Everything else is logged and swallowed:
    push is additive and must never fail the caller.
    """
    if device.revoked_at is not None or not device.endpoint_arn:
        return False

    try:
        _sns().publish(
            TargetArn=device.endpoint_arn,
            MessageStructure="json",
            Message=_payload(device.platform, title, body, data or {}),
        )
        return True
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code == "EndpointDisabled":
            # The app was deleted or the token rotated. Revoke rather than
            # delete, so "signed out" stays distinguishable from "never
            # registered" (ADR-443).
            device.revoked_at = datetime.now(timezone.utc)
            db.flush()
            logger.info(
                "push: SNS reports endpoint disabled for device %s; revoked",
                device.id,
            )
            return False
        logger.warning(
            "push: publish failed for device %s: %s", device.id, code or type(e).__name__,
        )
        return False
    except BotoCoreError as e:
        logger.warning(
            "push: publish failed for device %s: %s", device.id, type(e).__name__,
        )
        return False


def live_devices(db: Session, company_id, employee_id) -> list[DeviceToken]:
    """Every un-revoked device for one employee.

    Dimension 1: scoped on company_id as well as employee_id. The employee FK
    implies the company, and filtering on both is what the partial index is for
    -- and a token is a delivery address for tenant data, so the belt and the
    braces are both wanted here.
    """
    return (
        db.query(DeviceToken)
        .filter(
            DeviceToken.company_id == company_id,
            DeviceToken.employee_id == employee_id,
            DeviceToken.revoked_at.is_(None),
        )
        .all()
    )

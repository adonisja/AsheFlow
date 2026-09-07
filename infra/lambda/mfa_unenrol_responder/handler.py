"""Contain an MFA unenrolment within seconds of it happening (ADR-387).

Triggered by EventBridge on SetUserMFAPreference / AdminSetUserMFAPreference.
ADR-386 established that unenrolment cannot be PREVENTED -- the client calls
Cognito directly with a scope that cannot be stripped (ADR-377 D1) -- so the
control is detect-and-contain. The nightly sweep is the backstop; this is the
fast path.

WHY THIS DUPLICATES app/services/mfa_containment.py
This runs as a standalone Lambda with no VPC access to the app or its database,
so it cannot import that module. The two must stay in step: sign out FIRST (a
compromised session is live while devices are forgotten one call at a time), then
forget every device (a remembered device skips the MFA challenge, so leaving one
lets the actor back in on old trust). Any change to one belongs in both.

WHAT THE EVENT DOES AND DOES NOT CARRY -- measured, not assumed:

  requestParameters.username   HIDDEN_DUE_TO_SECURITY_REASONS
  userIdentity                 {"type": "Unknown", "principalId": "Anonymous"}
                               for the USER-initiated call
  additionalEventData.sub      the Cognito sub    <-- the ONLY identifier

So an event we cannot attribute is ALERTED, never silently dropped. That is both
the case a human most needs to see and how this breaks if AWS changes the payload.
"""
import json
import logging
import os

import boto3
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

POOL_IDS = [p for p in os.environ.get("USER_POOL_IDS", "").split(",") if p]
ALERT_TOPIC_ARN = os.environ.get("ALERT_TOPIC_ARN", "")


def _alert(subject: str, detail: dict) -> None:
    """Best-effort operator alert. Never raises: a failed alert must not stop
    containment, and containment is the part that matters."""
    logger.warning("MFA UNENROL ALERT: %s %s", subject, json.dumps(detail))
    if not ALERT_TOPIC_ARN:
        return
    try:
        boto3.client("sns").publish(
            TopicArn=ALERT_TOPIC_ARN,
            Subject=subject[:100],
            Message=json.dumps(detail, indent=2),
        )
    except (ClientError, BotoCoreError) as exc:
        logger.error("alert publish failed: %s", type(exc).__name__)


def _is_disable(params: dict) -> bool:
    """True when this call REMOVED a factor.

    A preference change that ENABLES a factor is not a security event, and the
    same API sets both. Checking every known settings block rather than only the
    software token: an email-only account disabling email is equally unprotected.
    """
    for key in ("softwareTokenMfaSettings", "smsMfaSettings", "emailMfaSettings"):
        block = params.get(key)
        if isinstance(block, dict) and block.get("enabled") is False:
            return True
    return False


def _username_for_sub(client, pool_id: str, sub: str) -> str | None:
    """Resolve a Cognito sub to a Username, which every admin API needs.

    The event gives us a sub; admin_user_global_sign_out and admin_forget_device
    take a Username. ListUsers with a sub filter is the documented mapping.
    """
    try:
        resp = client.list_users(
            UserPoolId=pool_id, Filter=f'sub = "{sub}"', Limit=1,
        )
    except (ClientError, BotoCoreError) as exc:
        logger.error("list_users failed for pool %s: %s", pool_id, type(exc).__name__)
        return None
    users = resp.get("Users", [])
    return users[0]["Username"] if users else None


def _contain(client, pool_id: str, username: str) -> dict:
    """Sign out, then forget every device. Mirrors mfa_containment.contain().

    Order matters: the session is live while devices are forgotten one API call
    at a time, so ending it first shrinks that window to a single call.
    """
    result = {"signed_out": False, "devices_forgotten": 0, "errors": []}

    try:
        client.admin_user_global_sign_out(UserPoolId=pool_id, Username=username)
        result["signed_out"] = True
    except (ClientError, BotoCoreError) as exc:
        result["errors"].append(f"sign_out: {type(exc).__name__}")
        logger.error("global sign-out failed: %s", type(exc).__name__)

    try:
        devices = client.admin_list_devices(
            UserPoolId=pool_id, Username=username, Limit=60,
        ).get("Devices", [])
    except (ClientError, BotoCoreError) as exc:
        result["errors"].append(f"list_devices: {type(exc).__name__}")
        logger.error("list devices failed: %s", type(exc).__name__)
        devices = []

    for d in devices:
        key = d.get("DeviceKey")
        if not key:
            continue
        try:
            client.admin_forget_device(
                UserPoolId=pool_id, Username=username, DeviceKey=key,
            )
            result["devices_forgotten"] += 1
        except (ClientError, BotoCoreError) as exc:
            # Keep going: forgetting 2 of 3 leaves a smaller hole than aborting.
            result["errors"].append(f"forget_device: {type(exc).__name__}")
            logger.error("forget device failed: %s", type(exc).__name__)

    return result


def handler(event, context):
    """EventBridge entry point. Never raises -- a crash here loses the event."""
    detail = event.get("detail", {}) or {}
    event_name = detail.get("eventName", "")
    event_id = detail.get("eventID", "")
    params = detail.get("requestParameters", {}) or {}

    if not _is_disable(params):
        # An ENABLE is the happy path: someone enrolling. Nothing to contain.
        logger.info("ignoring %s: not a disable", event_name)
        return {"action": "ignored", "reason": "not_a_disable"}

    sub = (detail.get("additionalEventData") or {}).get("sub")
    if not sub:
        # The ONLY identifier is missing. Alert -- this is both the case a human
        # most needs, and the signal that the payload shape changed.
        _alert(
            "MFA unenrolment could not be attributed",
            {"eventName": event_name, "eventID": event_id,
             "reason": "additionalEventData.sub absent"},
        )
        return {"action": "alerted", "reason": "no_sub"}

    pool_id = params.get("userPoolId")
    pools = [pool_id] if pool_id else POOL_IDS
    if not pools:
        _alert("MFA unenrolment: no pool to search",
               {"eventID": event_id, "sub": sub})
        return {"action": "alerted", "reason": "no_pool"}

    client = boto3.client("cognito-idp")
    for pid in pools:
        username = _username_for_sub(client, pid, sub)
        if not username:
            continue

        result = _contain(client, pid, username)
        # No username in the alert body -- ADR-115 D7. The sub is an opaque id
        # and is what an operator needs to look the account up deliberately.
        _alert(
            "MFA factor removed: account contained",
            {"eventName": event_name, "eventID": event_id, "sub": sub,
             "userPoolId": pid, **result},
        )
        logger.warning(
            "contained sub=%s signed_out=%s devices=%d errors=%d",
            sub, result["signed_out"], result["devices_forgotten"],
            len(result["errors"]),
        )
        return {"action": "contained", **result}

    _alert("MFA unenrolment: sub not found in any pool",
           {"eventID": event_id, "sub": sub, "poolsSearched": pools})
    return {"action": "alerted", "reason": "sub_not_found"}

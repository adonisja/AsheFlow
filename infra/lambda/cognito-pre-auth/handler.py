"""PreAuthentication: refuse a privileged sign-in with no MFA factor (ADR-362 D4).

Cognito has no native "require MFA for this group". `MfaConfiguration: ON` is
all-or-nothing and would lock out every un-enrolled user the moment it is set;
OPTIONAL enforces nothing. This trigger is the middle: the pool stays OPTIONAL,
and privileged accounts are refused until they enrol.

Fails OPEN on an unexpected error, and that is deliberate. This runs on EVERY
sign-in: a bug here that fails closed locks the whole company out of a system
people depend on at 04:00, including the admin who would fix it. A privileged
account signing in without MFA for the minutes that takes to notice is the
smaller harm. The one case it fails CLOSED on is an explicit refusal below.
"""
import logging
import os

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Who must hold a factor. Mirrors _allow_dispatch plus the platform roles —
# every group that can read across tenants, run dispatch, or export PII.
PRIVILEGED_GROUPS = {
    "super_admin",
    "admin",
    "management",
    "dispatch",
    "platform_support",
}

ENROL_HINT = (
    "This account needs two-factor authentication before you can sign in. "
    "Open AsheFlow on the web and go to Account > Security to set it up."
)

_client = None


def _cognito():
    global _client
    if _client is None:
        _client = boto3.client("cognito-idp", region_name=os.environ.get("AWS_REGION", "us-east-2"))
    return _client


def _groups(event) -> set:
    """Groups from the event, falling back to a lookup.

    PreAuthentication does not reliably carry group membership, so the event is
    only a fast path — the AdminListGroupsForUser call is the real answer.
    """
    claims = event.get("request", {}).get("userAttributes", {})
    raw = claims.get("cognito:groups")
    if raw:
        return {g.strip() for g in raw.split(",") if g.strip()}
    return set()


def handler(event, context):
    # The invoking pool, never an env var: this function is attached to BOTH
    # pools, and a hardcoded id checks the wrong one (ADR-362).
    pool_id = event.get("userPoolId")
    username = event.get("userName")

    if not pool_id or not username:
        logger.warning("pre-auth: no pool or user in event; allowing")
        return event

    try:
        groups = _groups(event)
        if not groups:
            resp = _cognito().admin_list_groups_for_user(
                UserPoolId=pool_id, Username=username, Limit=60
            )
            groups = {g["GroupName"] for g in resp.get("Groups", [])}

        if not (groups & PRIVILEGED_GROUPS):
            return event  # field role: a factor is encouraged, not gated

        user = _cognito().admin_get_user(UserPoolId=pool_id, Username=username)
        # A user with any factor enrolled has a non-empty UserMFASettingList.
        # Absent entirely for someone who has never enrolled.
        if user.get("UserMFASettingList"):
            return event

        logger.info("pre-auth: refusing %s — privileged with no MFA factor", username)
        # Raising is how a Cognito trigger denies; the message reaches the user.
        raise Exception(ENROL_HINT)

    except Exception as exc:
        # Re-raise our own refusal; swallow anything else. Distinguished by the
        # message rather than the type, because Cognito flattens exceptions.
        if str(exc) == ENROL_HINT:
            raise
        logger.exception("pre-auth: allowing sign-in after an unexpected error")
        return event

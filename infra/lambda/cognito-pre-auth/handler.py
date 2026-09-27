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
from datetime import datetime, timezone

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

# ADR-459 D3. Stamped on the one sign-in this trigger lets through unenrolled.
# Its ONLY job is to record that the one-time exemption has been spent, so the
# window cannot be replayed. Never read for authorisation: a forged value can
# only make an account MORE restricted (immediate refusal), never less.
FIRST_SEEN_ATTR = "custom:mfa_first_seen"

_client = None


def _cognito():
    global _client
    if _client is None:
        _client = boto3.client("cognito-idp", region_name=os.environ.get("AWS_REGION", "us-east-2"))
    return _client


def _stamp_first_seen(pool_id: str, username: str) -> None:
    """Spend the one-time exemption (ADR-459 D3).

    Fails SOFT and deliberately. If this write fails the user still signs in --
    they simply keep the exemption, and the next attempt retries the stamp. The
    alternative is refusing a sign-in because a bookkeeping write failed, which
    reintroduces the lockout this whole change exists to remove.
    """
    try:
        _cognito().admin_update_user_attributes(
            UserPoolId=pool_id,
            Username=username,
            UserAttributes=[{
                "Name": FIRST_SEEN_ATTR,
                "Value": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }],
        )
    except Exception:
        logger.exception("pre-auth: could not stamp %s; exemption not spent", username)


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

        # UserMFASettingList, and ONLY that -- but the reason is subtler than it
        # looks, and worth writing down because the obvious reading is wrong.
        #
        # ADR-377 D1 measured that this field is a false negative UNDER
        # MfaConfiguration: ON -- a user who clears their preference reads None
        # here while Cognito still challenges them, because the associated token
        # is what ON enforces. That suggests this check could lock out a
        # protected account.
        #
        # It cannot, because of which pool mode the trigger matters in.
        # Measured on a scratch pool, same user, preference cleared:
        #
        #     sign-in under OPTIONAL -> TOKENS (no challenge)
        #     sign-in under ON       -> SOFTWARE_TOKEN_MFA
        #
        # Under OPTIONAL the preference DOES gate, so None means genuinely
        # unprotected and refusing is correct -- this trigger is the only thing
        # standing there. Under ON every sign-in is challenged anyway, so the
        # trigger is redundant and a false refusal is the only harm it can do.
        #
        # Checked for a replacement signal that survives a cleared preference:
        # MFAOptions and PreferredMfaSetting both go None too. There is no such
        # field. So this is the best available signal, and it is correct where
        # it is load-bearing.
        if user.get("UserMFASettingList"):
            return event

        # ADR-459 D1. A privileged account with no factor AND no prior sign-in
        # is let through exactly once.
        #
        # The refusal below is a dead end for them: it says "go to Account >
        # Security", which is INSIDE the app they are being kept out of.
        # PreAuthentication fires before Cognito validates credentials and so
        # before any MFA challenge, which means this trigger pre-empts the
        # enrolment-during-sign-in flow rather than coexisting with it. Every
        # Owner of every new tenant met this wall.
        #
        # Signal chosen after measuring the alternatives on the live pool:
        # UserStatus reads CONFIRMED for everyone including the locked-out
        # account, and remembered-device count is inverted (the locked-out user
        # had 1, both enrolled users had 0). The lambda has no database, by
        # design -- it runs in the auth path and must not need the app to be up
        # -- so it records the fact itself.
        attrs = {a["Name"]: a.get("Value") for a in user.get("UserAttributes", [])}
        if not attrs.get(FIRST_SEEN_ATTR):
            _stamp_first_seen(pool_id, username)
            logger.info(
                "pre-auth: allowing %s once to enrol — privileged, no factor, "
                "no prior sign-in (ADR-459)", username,
            )
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

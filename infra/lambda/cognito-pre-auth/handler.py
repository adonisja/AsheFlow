"""PreAuthentication: refuse a privileged sign-in with no MFA factor (ADR-362 D4).

Also attached as PostAuthentication (ADR-530), where it does one thing: start
the enrolment window by stamping the first completed sign-in. Since ADR-548
the window is 24 hours, not one sign-in. The handler branches on event["triggerSource"].

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
from datetime import datetime, timedelta, timezone

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
    # ADR-549 D1: enrols at first sign-in (with ADR-548's 24-hour window).
    # Their survey records carry their name and the ADR-504 attestation.
    "surveyor",
}

# ADR-466 D2. Cognito wraps this in "PreAuthentication failed with error {msg}",
# which is AWS's and not configurable -- so the user always sees our sentence
# inside theirs. ADR-548 D5: both clients recognise the wrapper and render a
# designed panel, so this sentence is what an OLD client shows raw.
#
# ADR-548. It now says the window closed and names the one way out. The
# previous text told the reader to "sign in on the web to finish setup" --
# but anyone refused here has a closed window, so signing in cannot help.
#
# No trailing period: the wrapper supplies its own, and two in a row was the
# visible seam between AWS's sentence and ours.
ENROL_HINT = (
    "Your 24-hour window to set up two-factor authentication has closed. "
    "Ask your administrator to reset your two-factor setup"
)

# ADR-548 D1. The pass is a WINDOW from the first completed sign-in, not one
# sign-in. ADR-465's wall offers Sign out as its only exit, and with a single
# pass that exit led straight into this refusal (manager.test on prod,
# 2026-10-20: allowed 12:45:05, spent 12:45:06, refused 12:46:27).
# Mirrors app.services.mfa_status.PRIVILEGED_SETUP_WINDOW; a test pins parity.
SETUP_WINDOW_HOURS = 24

# A stamp dated further ahead than this is not trusted (ADR-548 D1): the
# attribute is user-writable today (WriteAttributes: null), and a future date
# would otherwise hold the window open for ever.
FUTURE_SKEW = timedelta(minutes=5)

# ADR-459 D3. Stamped on the first completed sign-in this trigger lets through
# unenrolled. It records WHEN the enrolment window opened; ADR-548 closes the
# window 24 hours later, so the stamp cannot be replayed into a fresh one. ADR-530: written by the PostAuthentication run,
# i.e. only once a sign-in has COMPLETED. PreAuthentication fires before the
# password is even checked, so stamping there let a typo, a Back button, a
# closed tab -- or anyone who knew the username -- spend a new owner's pass. Never read for authorisation: a forged value can
# only make an account MORE restricted (immediate refusal), never less.
FIRST_SEEN_ATTR = "custom:mfa_first_seen"

# ADR-533. Account states in which a password has been CHECKED but the user has
# not yet replaced it -- PostAuthentication fires here, the sign-in has not
# completed. RESET_REQUIRED is the admin-forced reset, same shape.
PRE_PASSWORD_STATES = {"FORCE_CHANGE_PASSWORD", "RESET_REQUIRED"}

def _make_client():
    return boto3.client("cognito-idp", region_name=os.environ.get("AWS_REGION", "us-east-2"))


# ADR-534. Built at import -- Lambda's init phase, which runs with burst CPU --
# instead of on the first call. Built lazily, the client construction and
# first TLS handshake landed inside the timed invocation: ~2.7 s of a 3 s cold
# sign-in at 128 MB, against Cognito's hard 5 s trigger limit. A timeout there
# is NOT caught by the fail-open below; Cognito just fails the sign-in.
# Fail-soft: if this cannot be built at import, _cognito() builds it later.
try:
    _client = _make_client()
except Exception:  # pragma: no cover -- init must never stop the function loading
    _client = None


def _now() -> datetime:
    """The clock, as a seam the tests can set."""
    return datetime.now(timezone.utc)


def _window_open(stamp: str, now: datetime) -> bool:
    """Is the 24-hour enrolment window that `stamp` opened still open?

    Anything it cannot trust reads as CLOSED: an unparseable value, a naive
    one, or one dated in the future. ADR-459's property was "a forged value can
    only make an account more restricted"; a time window could break that, so
    this keeps it (ADR-548 D1).
    """
    try:
        first = datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return False
    if first.tzinfo is None or first > now + FUTURE_SKEW:
        return False
    return now < first + timedelta(hours=SETUP_WINDOW_HOURS)


def _cognito():
    global _client
    if _client is None:
        _client = _make_client()
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
                "Value": _now().isoformat(timespec="seconds"),
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


def _unenrolled_privileged(event, pool_id: str, username: str):
    """The user's attributes if they are privileged with no MFA factor, else None.

    The one place the "who is gated" decision lives, so the pre and post
    branches cannot drift apart (ADR-530, rejected: a separate function).
    """
    groups = _groups(event)
    if not groups:
        resp = _cognito().admin_list_groups_for_user(
            UserPoolId=pool_id, Username=username, Limit=60
        )
        groups = {g["GroupName"] for g in resp.get("Groups", [])}

    if not (groups & PRIVILEGED_GROUPS):
        return None  # field role: a factor is encouraged, not gated

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
        return None
    attrs = {a["Name"]: a.get("Value") for a in user.get("UserAttributes", [])}
    # ADR-533. Carried for the post branch; prefixed so it cannot collide with
    # a real attribute name.
    attrs["_user_status"] = user.get("UserStatus")
    return attrs


def _post_authentication(event, pool_id: str, username: str):
    """Spend the pass, now that a sign-in has actually completed (ADR-530 D1).

    NEVER raises (D2): an exception in PostAuthentication fails the sign-in
    that just succeeded -- a lockout caused by bookkeeping, which is the harm
    _stamp_first_seen's fail-soft already exists to prevent.
    """
    try:
        attrs = _unenrolled_privileged(event, pool_id, username)
        if attrs is None or attrs.get(FIRST_SEEN_ATTR):
            return event
        # ADR-533. Measured on staging 2026-10-17: Cognito runs PostAuthentication
        # as soon as a TEMPORARY password checks out -- 0.6 s after PreAuth, while
        # the user was still on "Update Password" and before they pressed Back.
        # ADR-530 assumed it waited for every challenge. So a temporary-password
        # sign-in is not a completed one: the user has not chosen a password and
        # has no session yet. Do not spend the pass on it.
        event_status = (event.get("request", {}).get("userAttributes", {})
                        .get("cognito:user_status"))
        status = event_status or attrs.get("_user_status")
        logger.info("post-auth: %s status event=%s user=%s", username,
                    event_status, attrs.get("_user_status"))
        if status in PRE_PASSWORD_STATES:
            logger.info("post-auth: %s still on a temporary password; pass NOT "
                        "spent (ADR-533)", username)
            return event
        _stamp_first_seen(pool_id, username)
        logger.info(
            "post-auth: %s completed its one unenrolled sign-in; pass spent "
            "(ADR-459/530)", username,
        )
    except Exception:
        logger.exception("post-auth: could not evaluate %s; pass not spent", username)
    return event


def handler(event, context):
    # The invoking pool, never an env var: this function is attached to BOTH
    # pools, and a hardcoded id checks the wrong one (ADR-362).
    pool_id = event.get("userPoolId")
    username = event.get("userName")

    if not pool_id or not username:
        logger.warning("pre-auth: no pool or user in event; allowing")
        return event

    # ADR-530. Anything that is not PostAuthentication takes the PreAuth path,
    # which is the historical behaviour for an event with no triggerSource.
    if event.get("triggerSource", "").startswith("PostAuthentication"):
        return _post_authentication(event, pool_id, username)

    try:
        attrs = _unenrolled_privileged(event, pool_id, username)
        if attrs is None:
            return event

        # ADR-459 D1. A privileged account with no factor AND no completed
        # sign-in is let through, so it can reach enrolment.
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
        #
        # ADR-530: allowed, NOT stamped. This attempt may yet fail its password
        # or be abandoned on a challenge; only PostAuthentication knows it
        # completed. Allowing an unfinished attempt grants nothing -- there are
        # no tokens until it finishes.
        if not attrs.get(FIRST_SEEN_ATTR):
            logger.info(
                "pre-auth: allowing %s to enrol -- privileged, no factor, "
                "no completed sign-in (ADR-459/530)", username,
            )
            return event

        # ADR-548 D1. Stamped, but the window it opened may still be open:
        # signing out of /mfa-setup to fetch a phone must not be a lockout.
        if _window_open(attrs[FIRST_SEEN_ATTR], _now()):
            logger.info(
                "pre-auth: allowing %s -- privileged, no factor, inside the "
                "%dh enrolment window (ADR-548)", username, SETUP_WINDOW_HOURS,
            )
            return event

        logger.info("pre-auth: refusing %s — privileged with no MFA factor, "
                    "enrolment window closed", username)
        # Raising is how a Cognito trigger denies; the message reaches the user.
        raise Exception(ENROL_HINT)

    except Exception as exc:
        # Re-raise our own refusal; swallow anything else. Distinguished by the
        # message rather than the type, because Cognito flattens exceptions.
        if str(exc) == ENROL_HINT:
            raise
        logger.exception("pre-auth: allowing sign-in after an unexpected error")
        return event

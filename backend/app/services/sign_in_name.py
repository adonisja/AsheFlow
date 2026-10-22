"""A person's own sign-in name: a Cognito alias beside their username (ADR-566 D4).

The username stays firstname.lastname. The sign-in name is `preferred_username`,
which pools created by ADR-566 accept at sign-in as an alias. Cognito enforces
uniqueness itself, case-insensitively, against every username AND every other
alias (AliasExistsException, measured 2026-10-22), so the only rules here are
the shape and who may change it:
  - only the person sets it; an admin may clear one, never choose it (owner);
  - written with the admin API: a user token can write only `locale` (ADR-558).

On a pool without the alias (the pools before ADR-566) the feature reports
itself unavailable rather than storing a name nobody can sign in with.
"""
from __future__ import annotations

import logging
import re

from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import settings
from app.services import account_security

logger = logging.getLogger(__name__)

ATTR = "preferred_username"
MIN_LEN, MAX_LEN = 3, 30
# Starts with a letter; letters, digits, dot, dash, underscore. No "@": Cognito
# would accept an email-shaped alias, and a sign-in name that looks like an
# address invites people to type someone's email at the sign-in screen.
_SHAPE = re.compile(r"^[a-z][a-z0-9._-]*$")
RULES = (f"{MIN_LEN}–{MAX_LEN} characters: letters, numbers, dots, dashes or underscores, "
         "starting with a letter.")

_alias_pools: dict[str, bool] = {}


class SignInNameError(Exception):
    """`.status` and `.detail` are safe to show."""

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


def normalise(raw: str) -> str:
    name = (raw or "").strip().lower()
    if not (MIN_LEN <= len(name) <= MAX_LEN) or not _SHAPE.match(name):
        raise SignInNameError(422, f"A sign-in name is {RULES}")
    return name


def available() -> bool:
    """Does this environment's pool accept the alias at sign-in? Cached per pool:
    AliasAttributes can't change on a live pool, so the answer never changes."""
    pool = settings.aws_cognito_user_pool_id
    if pool not in _alias_pools:
        try:
            p = account_security._cognito().describe_user_pool(UserPoolId=pool)["UserPool"]
        except (ClientError, BotoCoreError) as exc:
            logger.warning("sign-in name: could not read the pool: %s", type(exc).__name__)
            return False   # not cached: a transient failure must not stick
        _alias_pools[pool] = ATTR in (p.get("AliasAttributes") or [])
    return _alias_pools[pool]


def current(username: str) -> str | None:
    try:
        u = account_security._cognito().admin_get_user(
            UserPoolId=settings.aws_cognito_user_pool_id, Username=username)
    except (ClientError, BotoCoreError) as exc:
        logger.warning("sign-in name: could not read the account: %s", type(exc).__name__)
        return None
    return next((a.get("Value") for a in u.get("UserAttributes", []) if a["Name"] == ATTR), None)


def _require_available() -> None:
    if not available():
        raise SignInNameError(409, "Sign-in names aren't available yet.")


def apply_sign_in_name(db, *, username: str, raw: str, rate_key, audit: dict) -> str:
    """Set the caller's own sign-in name. Commits. `audit` carries
    company_id / actor_id / target_table / target_id for the audit row."""
    from app.services.audit import write_audit
    _require_available()
    name = normalise(raw)
    if name == username.lower():
        raise SignInNameError(400, "That's already your username. Choose something different.")
    if not account_security.allow_request(rate_key, "sign_in_name"):
        raise SignInNameError(429, "Too many changes. Try again in an hour.")
    old = current(username)
    try:
        account_security._cognito().admin_update_user_attributes(
            UserPoolId=settings.aws_cognito_user_pool_id, Username=username,
            UserAttributes=[{"Name": ATTR, "Value": name}])
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "AliasExistsException":
            raise SignInNameError(409, "That sign-in name is taken. Try another.")
        logger.error("sign-in name: update failed: %s", exc.response["Error"]["Code"])
        raise SignInNameError(502, "Couldn't save your sign-in name. Try again.")
    except BotoCoreError as exc:
        logger.error("sign-in name: update failed: %s", type(exc).__name__)
        raise SignInNameError(502, "Couldn't save your sign-in name. Try again.")
    db.flush()
    write_audit(db, action_type="account.sign_in_name_set", **audit,
                detail={"from": old, "to": name})
    db.commit()
    return name


def remove_sign_in_name(db, *, username: str, by: str, audit: dict) -> bool:
    """Remove a sign-in name; `by` is "self" or the admin kind. Commits.
    Returns False when there was none to clear."""
    from app.services.audit import write_audit
    old = current(username)
    if not old:
        return False
    try:
        account_security._cognito().admin_delete_user_attributes(
            UserPoolId=settings.aws_cognito_user_pool_id, Username=username, UserAttributeNames=[ATTR])
    except (ClientError, BotoCoreError) as exc:
        code = exc.response["Error"]["Code"] if isinstance(exc, ClientError) else type(exc).__name__
        logger.error("sign-in name: clear failed: %s", code)
        raise SignInNameError(502, "Couldn't remove the sign-in name. Try again.")
    db.flush()
    write_audit(db, action_type="account.sign_in_name_cleared", **audit,
                detail={"was": old, "cleared_by": by})
    db.commit()
    return True

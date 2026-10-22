"""Credential changes that are confirmed out of band and end every session (ADR-541).

Two primitives the password and email flows share:

  end_all_sessions   AdminUserGlobalSignOut + the tokens_valid_after stamp.
  issue / check      one-time 6-digit codes held server-side, for the email
                     change (the password change uses Cognito's own
                     ForgotPassword code -- ADR-541 R1).

WHY THE SERVER HOLDS EMAIL-CHANGE CODES INSTEAD OF COGNITO
Cognito's own email-change path is the USER-level UpdateUserAttributes /
VerifyUserAttribute pair, called with the user's access token. ADR-541 D4
treats exactly those calls, seen in CloudTrail, as someone going around the
app. Our flow therefore never makes them: codes live here, and the final write
is the server's AdminUpdateUserAttributes.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timezone
from uuid import UUID

from app.core.config import settings

logger = logging.getLogger(__name__)

CODE_TTL_SECONDS = 10 * 60
#: Wrong guesses allowed per code before it is destroyed. A 6-digit code with
#: 5 guesses is a 1-in-200,000 chance, and the request side is rate limited.
MAX_CODE_ATTEMPTS = 5
#: Code requests per account per hour. Each one emails a real inbox.
MAX_CODE_REQUESTS_PER_HOUR = 5


def _cognito():
    import boto3
    return boto3.client("cognito-idp", region_name=settings.aws_region)


def _redis():
    from app.core.security import _get_redis
    return _get_redis()


# ── Ending sessions ───────────────────────────────────────────────────────────

def end_all_sessions(employee, username: str) -> bool:
    """Sign the account out everywhere (ADR-541 D2). Returns True if Cognito did.

    Order and failure: the stamp is set FIRST and unconditionally -- it is the
    half this API enforces itself, so a Cognito outage cannot leave an old
    session working here. The caller commits it. A failed global sign-out is
    logged and reported, not raised: the change itself has already happened,
    and refusing to say so would invite the user to do it twice.
    """
    employee.tokens_valid_after = datetime.now(timezone.utc)
    try:
        _cognito().admin_user_global_sign_out(
            UserPoolId=settings.aws_cognito_user_pool_id, Username=username,
        )
        return True
    except Exception as exc:  # boto raises ClientError/BotoCoreError; neither is user-facing
        logger.warning("account_security: global sign-out failed: %s", type(exc).__name__)
        return False


def end_platform_sessions(db, sub: str, username: str) -> bool:
    """end_all_sessions for an account with no Employee row (ADR-549 D3).

    Same order and the same failure rule: the stamp this API enforces itself
    goes first and unconditionally (caller commits), then Cognito's global
    sign-out, whose failure is logged and reported rather than raised.
    """
    from app.models.platform_session import PlatformSessionStamp
    now = datetime.now(timezone.utc)
    row = db.get(PlatformSessionStamp, sub)
    if row is None:
        db.add(PlatformSessionStamp(cognito_sub=sub, tokens_valid_after=now, updated_at=now))
    else:
        row.tokens_valid_after = now
        row.updated_at = now
    try:
        _cognito().admin_user_global_sign_out(
            UserPoolId=settings.aws_cognito_user_pool_id, Username=username,
        )
        return True
    except Exception as exc:  # boto raises ClientError/BotoCoreError; neither is user-facing
        logger.warning("account_security: platform global sign-out failed: %s", type(exc).__name__)
        return False


def mark_sessions_ended(db, sub: str) -> str:
    """Write the session stamp this API enforces, for whichever kind of account
    `sub` is (ADR-550 D4). Returns "employee" or "platform".

    An MFA reset signs the account out at Cognito, which revokes REFRESH tokens
    only; access tokens are verified locally here and kept working for up to an
    hour. When the reset is because a phone was stolen, that hour is the thief's.
    A tenant employee is stamped on their row (ADR-541), any other account in
    platform_session_stamps (ADR-549). The caller commits.
    """
    from app.models.employee import Employee
    from app.models.platform_session import PlatformSessionStamp
    now = datetime.now(timezone.utc)
    emp = db.query(Employee).filter(Employee.cognito_sub == sub).first()
    if emp is not None:
        emp.tokens_valid_after = now
        return "employee"
    row = db.get(PlatformSessionStamp, sub)
    if row is None:
        db.add(PlatformSessionStamp(cognito_sub=sub, tokens_valid_after=now, updated_at=now))
    else:
        row.tokens_valid_after = now
        row.updated_at = now
    return "platform"


# ── One-time codes ────────────────────────────────────────────────────────────

def _digest(employee_id: UUID, purpose: str, code: str) -> str:
    """Bind the code to the account AND the purpose before hashing.

    A code minted for one account, or for the new-address half of an email
    change, must not satisfy any other check.
    """
    key = (settings.aws_cognito_user_pool_id or "asheflow").encode()
    msg = f"{employee_id}:{purpose}:{code}".encode()
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def _code_key(employee_id: UUID, purpose: str) -> str:
    return f"acctsec:code:{purpose}:{employee_id}"


def _tries_key(employee_id: UUID, purpose: str) -> str:
    return f"acctsec:tries:{purpose}:{employee_id}"


def _requests_key(employee_id: UUID, flow: str) -> str:
    return f"acctsec:requests:{flow}:{employee_id}"


def allow_request(employee_id: UUID, flow: str) -> bool:
    """Count one code request; False once the hourly cap is passed."""
    r = _redis()
    key = _requests_key(employee_id, flow)
    n = r.incr(key)
    if n == 1:
        r.expire(key, 3600)
    return n <= MAX_CODE_REQUESTS_PER_HOUR


def issue_code(employee_id: UUID, purpose: str) -> str:
    """Mint a code, store only its digest, reset its attempt counter."""
    code = f"{secrets.randbelow(1_000_000):06d}"
    r = _redis()
    r.setex(_code_key(employee_id, purpose), CODE_TTL_SECONDS, _digest(employee_id, purpose, code))
    r.delete(_tries_key(employee_id, purpose))
    return code


def check_code(employee_id: UUID, purpose: str, code: str) -> str:
    """'ok', 'wrong' or 'expired'. A correct code is consumed; so is a code
    that has used up its attempts (it becomes 'expired')."""
    r = _redis()
    stored = r.get(_code_key(employee_id, purpose))
    if stored is None:
        return "expired"
    if isinstance(stored, bytes):
        stored = stored.decode()
    if hmac.compare_digest(stored, _digest(employee_id, purpose, code.strip())):
        r.delete(_code_key(employee_id, purpose), _tries_key(employee_id, purpose))
        return "ok"
    tries = r.incr(_tries_key(employee_id, purpose))
    if tries == 1:
        r.expire(_tries_key(employee_id, purpose), CODE_TTL_SECONDS)
    if tries >= MAX_CODE_ATTEMPTS:
        r.delete(_code_key(employee_id, purpose), _tries_key(employee_id, purpose))
        return "expired"
    return "wrong"


def discard_codes(employee_id: UUID, *purposes: str) -> None:
    r = _redis()
    for p in purposes:
        r.delete(_code_key(employee_id, p), _tries_key(employee_id, p))


# ── Display ───────────────────────────────────────────────────────────────────

def mask_email(address: str) -> str:
    """j•••@example.com -- enough to recognise, not enough to harvest."""
    local, _, domain = (address or "").partition("@")
    if not domain:
        return "•••"
    return f"{local[:1]}•••@{domain}"


def notify_mfa_reset(username: str, *, reset_by: str, account: str, if_not_you: str,
                     account_ref: str, reason: str | None = None) -> bool:
    """Tell the account holder their second factor was reset (ADR-561). True if emailed.

    Sent to the address Cognito sends this account's codes to, and only when
    Cognito marks it verified -- never Employee.email, which can differ from the
    recovery address (staging: walker.test@asheflow.internal vs walker@test.com).
    Never raises: the reset already happened, and a failed notice must not turn
    it into an error. Logged by error type only.
    """
    from botocore.exceptions import BotoCoreError, ClientError
    from app.services.email import send_mfa_reset_notice
    try:
        u = _cognito().admin_get_user(UserPoolId=settings.aws_cognito_user_pool_id, Username=username)
    except (ClientError, BotoCoreError) as exc:
        code = exc.response.get("Error", {}).get("Code") if isinstance(exc, ClientError) else type(exc).__name__
        logger.warning("mfa reset notice: account lookup failed: %s", code)
        return False
    attrs = {a["Name"]: a.get("Value") for a in u.get("UserAttributes", [])}
    email = attrs.get("email")
    if not email or attrs.get("email_verified") != "true":
        return False
    try:
        send_mfa_reset_notice(to_email=email, name=attrs.get("name") or u.get("Username", ""),
                              reset_by=reset_by, account=account, if_not_you=if_not_you,
                              account_ref=account_ref, reason=reason)
    except Exception as exc:  # the reset stands whatever the mailer did
        logger.warning("mfa reset notice: send failed: %s", type(exc).__name__)
        return False
    return True

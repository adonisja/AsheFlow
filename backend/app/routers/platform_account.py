"""A platform account's own sign-in settings (ADR-549 D4).

Platform accounts -- super_admin, platform_support, surveyor -- have no
Employee row (ADR-394), and every /employees/me/* credential endpoint is built
on that row, so before this none of them could change a password and nothing
could end their sessions inside this API. These endpoints are keyed on the
Cognito identity instead, and serve only the caller's OWN account.

Mirrors ADR-541's tenant flow deliberately: Cognito's ForgotPassword code to
the verified inbox (no user-level ChangePassword call, ADR-541 D4), then every
session ends. Email change (ADR-563 D2) uses ADR-541's two inboxes: a code to
the current verified address and one to the new, which is exactly the guard an
account rewriting its own recovery address needs. With no verified address,
a super admin changes it (D3).
"""
import logging

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy.orm import Session

from app.api.deps import PLATFORM_ACCOUNT_GROUPS, get_db, get_platform_user
from app.core.config import settings
from app.services import account_security
from app.services.audit import write_audit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/platform/me", tags=["platform-account"])

# Most-privileged first: the label shown is the strongest group held.
_ROLE_LABELS = (
    ("super_admin", "Super admin"),
    ("platform_support", "Platform support"),
    ("surveyor", "Surveyor"),
)

_NO_EMAIL = (
    "Your account has no verified email address, so a code can't be sent. "
    "Ask a super admin to change your email."
)


def _cognito():
    return boto3.client("cognito-idp", region_name=settings.aws_region)


def get_platform_account(current_user: dict = Depends(get_platform_user)) -> dict:
    """A caller in a platform group, with its session stamp already checked."""
    if not (set(current_user.get("cognito_groups", [])) & PLATFORM_ACCOUNT_GROUPS):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="These settings are for platform accounts.")
    return current_user


def _username_or_409(caller: dict) -> str:
    username = caller.get("username")
    if not username:
        raise HTTPException(status_code=409, detail="Your account isn't set up to sign in yet.")
    return username


def _rate_key(caller: dict) -> str:
    # Namespaced: a Cognito sub is itself a UUID, so an unprefixed key could in
    # principle share a counter with an Employee id in account_security.
    return f"platform:{caller.get('id')}"


class PlatformMeOut(BaseModel):
    # ADR-550 D1: the account's permanent IDs. account_id is the Cognito sub
    # (every platform account); surveyor_id is the contributor row's id.
    account_id: str
    surveyor_id: UUID | None = None
    username: str
    name: str | None
    email: str | None
    email_verified: bool
    groups: list[str]
    role_label: str
    mfa_enrolled: bool | None


class _PasswordConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(..., min_length=4, max_length=10)
    new_password: str = Field(..., min_length=8, max_length=256)


@router.get("", response_model=PlatformMeOut)
def get_me(caller: dict = Depends(get_platform_account), db: Session = Depends(get_db)):
    """The caller's own profile, from Cognito (there is no other record)."""
    username = _username_or_409(caller)
    groups = sorted(set(caller.get("cognito_groups", [])) & PLATFORM_ACCOUNT_GROUPS)
    label = next((l for g, l in _ROLE_LABELS if g in groups), "Platform")
    attrs: dict = {}
    enrolled: bool | None = None
    try:
        resp = _cognito().admin_get_user(
            UserPoolId=settings.aws_cognito_user_pool_id, Username=username)
        attrs = {a["Name"]: a.get("Value") for a in resp.get("UserAttributes", [])}
        enrolled = bool(resp.get("UserMFASettingList"))
    except (ClientError, BotoCoreError) as exc:
        # Degrade to what the token says; "could not read" is never "not enrolled".
        logger.warning("platform me: could not read %s: %s", username, type(exc).__name__)
    from app.models.survey_register import SurveyContributor
    surveyor_id = (db.query(SurveyContributor.id)
                   .filter(SurveyContributor.cognito_sub == caller["id"]).scalar())
    return PlatformMeOut(
        account_id=caller["id"],
        surveyor_id=surveyor_id,
        username=username,
        name=attrs.get("name"),
        email=attrs.get("email") or caller.get("email"),
        email_verified=attrs.get("email_verified") == "true",
        groups=groups,
        role_label=label,
        mfa_enrolled=enrolled,
    )


@router.get("/session", status_code=status.HTTP_200_OK)
def check_session(caller: dict = Depends(get_platform_account)):
    """The platform twin of /employees/me/session (ADR-541 D2 amendment).

    Reaching the body means the session is still good; the refusal is
    get_platform_user's coded 401, which both clients already route on."""
    return {"ok": True}


@router.post("/password/request-code", status_code=status.HTTP_200_OK)
def request_password_code(caller: dict = Depends(get_platform_account)):
    """Step 1: Cognito emails a code to the verified address."""
    username = _username_or_409(caller)
    if not account_security.allow_request(_rate_key(caller), "password"):
        raise HTTPException(status_code=429, detail="Too many code requests. Try again in an hour.")
    try:
        resp = _cognito().forgot_password(
            ClientId=settings.aws_cognito_app_client_id, Username=username)
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code == "InvalidParameterException":
            raise HTTPException(status_code=409, detail=_NO_EMAIL)
        if code in ("LimitExceededException", "TooManyRequestsException"):
            raise HTTPException(status_code=429, detail="Too many code requests. Try again later.")
        logger.error("platform forgot_password failed: %s", code)
        raise HTTPException(status_code=500, detail="Couldn't send the code. Try again.")
    # Cognito returns the masked destination itself; never echo the full address.
    sent_to = (resp or {}).get("CodeDeliveryDetails", {}).get("Destination")
    return {"detail": "Code sent.", "sent_to": sent_to}


@router.post("/password/confirm", status_code=status.HTTP_200_OK)
def confirm_password_change(
    payload: _PasswordConfirmRequest,
    caller: dict = Depends(get_platform_account),
    db: Session = Depends(get_db),
):
    """Step 2: the code and the new password; then every session ends (D3)."""
    username = _username_or_409(caller)
    try:
        _cognito().confirm_forgot_password(
            ClientId=settings.aws_cognito_app_client_id,
            Username=username,
            ConfirmationCode=payload.code.strip(),
            Password=payload.new_password,
        )
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code == "CodeMismatchException":
            raise HTTPException(status_code=400, detail="That code isn't right. Check the email and try again.")
        if code == "ExpiredCodeException":
            raise HTTPException(status_code=400, detail="That code has expired. Send a new one.")
        if code == "InvalidPasswordException":
            raise HTTPException(
                status_code=400,
                detail="That password doesn't meet the rules: at least 8 characters, with upper and lower case letters, a number and a symbol.",
            )
        if code in ("LimitExceededException", "TooManyFailedAttemptsException", "TooManyRequestsException"):
            raise HTTPException(status_code=429, detail="Too many attempts. Wait a few minutes and try again.")
        logger.error("platform confirm_forgot_password failed: %s", code)
        raise HTTPException(status_code=500, detail="Couldn't change your password. Try again.")

    sub = caller["id"]
    signed_out = account_security.end_platform_sessions(db, sub, username)
    db.flush()
    groups = sorted(set(caller.get("cognito_groups", [])) & PLATFORM_ACCOUNT_GROUPS)
    write_audit(
        db=db,
        company_id=None,            # a platform account belongs to no tenant
        actor_id=None,              # FK to employees; the identity is in detail (ADR-394)
        action_type="account.password_changed",
        target_table="platform_session_stamps",
        target_id=sub,
        detail={"actor_kind": groups[0] if groups else "platform",
                "actor_cognito_sub": sub,
                "confirmed_by": "email_code",
                "signed_out_everywhere": signed_out},
    )
    db.commit()
    return {"detail": "Password changed. Sign in with your new password.", "signed_out": True}


# ── ADR-563 D2: a platform account changes its own email ──────────────────
# The same two codes as the tenant flow (ADR-541 R2): one to the CURRENT
# verified address (proves the owner), one to the NEW (proves the inbox). The
# write itself is email_change.apply_change, shared with every other path.

class _EmailChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    new_email: EmailStr


class _EmailConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_code: str = Field(..., min_length=4, max_length=10)
    new_code: str = Field(..., min_length=4, max_length=10)


_PENDING_KEY = "acctsec:platform_pending_email:{}"
_NO_CURRENT = ("Your account has no verified email address to confirm the change from. "
               "Ask a super admin to change it for you.")


@router.post("/email/request-change", status_code=status.HTTP_200_OK)
def request_email_change(payload: _EmailChangeRequest, caller: dict = Depends(get_platform_account)):
    from app.core.security import _get_redis
    from app.services import email_change
    from app.services.email import send_email_change_code

    username = _username_or_409(caller)
    acct = email_change.cognito_account(username)
    if not acct or not acct["email"] or not acct["verified"]:
        raise HTTPException(status_code=409, detail=_NO_CURRENT)
    new_email = payload.new_email.strip().lower()
    if new_email == acct["email"]:
        raise HTTPException(status_code=400, detail="That's already your email address.")
    try:
        if email_change.address_taken(new_email, acct["sub"]):
            raise HTTPException(status_code=409, detail="That email is already used by another account.")
    except email_change.EmailChangeError as e:
        raise HTTPException(status_code=e.status, detail=e.detail)
    key = _rate_key(caller)
    if not account_security.allow_request(key, "email"):
        raise HTTPException(status_code=429, detail="Too many code requests. Try again in an hour.")

    current_code = account_security.issue_code(key, "email_current")
    new_code = account_security.issue_code(key, "email_new")
    _get_redis().setex(_PENDING_KEY.format(acct["sub"]), account_security.CODE_TTL_SECONDS, new_email)
    masked_new = account_security.mask_email(new_email)
    try:
        send_email_change_code(to_email=acct["email"], employee_name=acct["name"], code=current_code,
                               which="current", new_email_masked=masked_new, account_ref=acct["sub"])
        send_email_change_code(to_email=new_email, employee_name=acct["name"], code=new_code,
                               which="new", new_email_masked=masked_new, account_ref=acct["sub"])
    except ClientError:
        account_security.discard_codes(key, "email_current", "email_new")
        raise HTTPException(status_code=502, detail="Couldn't send the codes. Try again.")
    return {"detail": "Codes sent.", "current_masked": account_security.mask_email(acct["email"]),
            "new_masked": masked_new}


@router.post("/email/confirm-change", status_code=status.HTTP_200_OK)
def confirm_email_change(payload: _EmailConfirmRequest, caller: dict = Depends(get_platform_account),
                         db: Session = Depends(get_db)):
    from app.core.security import _get_redis
    from app.services import email_change

    username = _username_or_409(caller)
    sub = caller["id"]
    raw = _get_redis().get(_PENDING_KEY.format(sub))
    if raw is None:
        raise HTTPException(status_code=400, detail="Those codes have expired. Start the change again.")
    new_email = raw.decode() if isinstance(raw, bytes) else raw
    key = _rate_key(caller)
    for purpose, given, where in (("email_current", payload.current_code, "your current email"),
                                  ("email_new", payload.new_code, "your new email")):
        verdict = account_security.check_code(key, purpose, given)
        if verdict == "expired":
            account_security.discard_codes(key, "email_current", "email_new")
            raise HTTPException(status_code=400, detail="Those codes have expired. Start the change again.")
        if verdict == "wrong":
            raise HTTPException(status_code=400, detail=f"The code sent to {where} isn't right.")
    try:
        result = email_change.apply_change(db, username=username, new_email=new_email,
                                           actor={"kind": "self", "ref": sub},
                                           confirmed_by="codes_to_both_addresses")
    except email_change.EmailChangeError as e:
        raise HTTPException(status_code=e.status, detail=e.detail)
    _get_redis().delete(_PENDING_KEY.format(sub))
    return {"detail": "Email updated. Sign in again.", "email": result["email"], "signed_out": True}

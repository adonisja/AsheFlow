"""A locked-out person asks for a two-factor reset (ADR-551).

PUBLIC: the person has no session -- that is what being locked out means. So
the request is proved by a code to the account's verified inbox (D2), bounded
on the real client IP and per account, and never changes the account itself:
it only puts a flag beside the reset button of whoever can act (D3).

The first step answers the same way whether or not the account exists, and
sends its email after the response, so neither the body nor the timing tells a
caller which usernames are real.
"""
import logging

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.ratelimit import limiter
from app.core.config import settings
from app.models.employee import Employee
from app.services import account_security, mfa_reset_requests, reset_request_token
from app.services.audit import write_audit
from app.services.email import send_mfa_reset_request_code

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/mfa-reset", tags=["auth"])

_PURPOSE = "mfa_reset_request"
_SENT = {"detail": "If that account exists and has a verified email, we've sent it a code."}


def _cognito():
    return boto3.client("cognito-idp", region_name=settings.aws_region)


class _RequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(..., min_length=1, max_length=128)


class _ConfirmIn(BaseModel):
    """Step 2: the ticket from step 1 and the emailed code. No username --
    the account was fixed at step 1 (ADR-551 D2b)."""
    model_config = ConfigDict(extra="forbid")
    request_token: str = Field(..., min_length=20, max_length=1024)
    code: str = Field(..., min_length=4, max_length=10)


# One answer for a wrong code, an expired code, a decoy ticket and a bad
# ticket: distinguishing "expired" from "wrong" would tell a caller holding a
# decoy that the account isn't real (a decoy's code never existed).
_BAD_CODE = "That code isn't right or has expired. Check the email, or ask for a new code."


def _account(username: str) -> dict | None:
    """Cognito's record for `username`: sub, verified email, name, groups. None if unusable."""
    pool = settings.aws_cognito_user_pool_id
    client = _cognito()
    try:
        u = client.admin_get_user(UserPoolId=pool, Username=username)
        attrs = {a["Name"]: a.get("Value") for a in u.get("UserAttributes", [])}
        groups = {g["GroupName"] for g in client.admin_list_groups_for_user(
            UserPoolId=pool, Username=u["Username"], Limit=60).get("Groups", [])}
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "UserNotFoundException":
            logger.warning("mfa reset request: lookup failed: %s", exc.response.get("Error", {}).get("Code"))
        return None
    except BotoCoreError as exc:
        logger.warning("mfa reset request: lookup failed: %s", type(exc).__name__)
        return None
    sub = next((a.get("Value") for a in u.get("UserAttributes", []) if a.get("Name") == "sub"), None)
    if not sub:
        return None
    return {"sub": sub, "username": u["Username"], "email": attrs.get("email"),
            "verified": attrs.get("email_verified") == "true",
            "name": attrs.get("name") or u["Username"], "groups": groups}


@router.post("/request", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("10/hour")
def request_reset_code(request: Request, body: _RequestIn, background: BackgroundTasks):
    """Step 1: email a code to the account's verified address (D2)."""
    name = body.username.strip()
    # Per account, before we know whether it exists, so an unknown name costs
    # the same as a real one.
    if not account_security.allow_request(f"mfareq:{name.lower()}", _PURPOSE):
        raise HTTPException(status_code=429, detail="Too many requests for this account. Try again in an hour.")
    acct = _account(name)
    if acct and acct["email"] and acct["verified"]:
        code = account_security.issue_code(f"mfareq:{acct['sub']}", _PURPOSE)
        background.add_task(send_mfa_reset_request_code, to_email=acct["email"], name=acct["name"],
                            code=code, account_ref=acct["sub"])
        token = reset_request_token.issue(acct["sub"], acct["username"])
    else:
        # D2b: a decoy ticket -- same shape, same behaviour at step 2 -- so the
        # answer never says whether the name is real.
        token = reset_request_token.decoy(name)
    return {**_SENT, "request_token": token}


@router.post("/confirm", status_code=status.HTTP_200_OK)
@limiter.limit("20/hour")
def confirm_reset_request(request: Request, body: _ConfirmIn, db: Session = Depends(get_db)):
    """Step 2: the code proves the inbox; record the request and tell whoever can act (D3)."""
    ticket = reset_request_token.read(body.request_token)
    if ticket is None:
        raise HTTPException(status_code=400, detail=_BAD_CODE)
    sub, username = ticket
    # The code is checked BEFORE any lookup: a decoy (no code was ever sent)
    # stops here exactly like a wrong code, with no Cognito call to time.
    if account_security.check_code(f"mfareq:{sub}", _PURPOSE, body.code) != "ok":
        raise HTTPException(status_code=400, detail=_BAD_CODE)
    acct = _account(username)
    if acct is None or acct["sub"] != sub:
        # The account was deleted or renamed in the 10 minutes since step 1.
        raise HTTPException(status_code=400, detail=_BAD_CODE)

    who = mfa_reset_requests.classify(db, acct["sub"], acct["groups"])
    if who is None:
        raise HTTPException(status_code=409, detail=(
            "This account can't request a reset here. Contact the person who set up your account."))
    kind, fields = who
    ip = request.client.host if request.client else None
    req, created = mfa_reset_requests.record(db, sub=acct["sub"], kind=kind, fields=fields, ip=ip)

    if created:
        if kind == "employee":
            from app.services.notify import write_notification
            emp = fields["employee"]
            for admin in (db.query(Employee)
                          .filter(Employee.company_id == emp.company_id, Employee.is_active.is_(True),
                                  Employee.role.in_(mfa_reset_requests.TENANT_RESETTERS),
                                  Employee.id != emp.id).all()):
                write_notification(db, company_id=emp.company_id, employee_id=admin.id,
                                   type="mfa_reset_requested", target_id=emp.id,
                                   message=f"{emp.name} asked for a two-factor reset. Reset it from Assets → Reset requests.")
        elif kind == "staff":
            from app.services.integration_alerts import raise_platform_alert
            raise_platform_alert(db, alert_type="mfa.reset_requested", company_id=None,
                                 subject_kind="platform", subject_ref=acct["username"],
                                 subject_role=next((g for g in ("super_admin", "platform_support")
                                                    if g in acct["groups"]), "platform staff"),
                                 message="A platform account asked for a two-factor reset. Reset it from Platform staff.",
                                 severity="warning")
        # Surveyors: support sees it on Survey activity, beside the reset (D3).
        write_audit(db, action_type="mfa.reset_requested", target_table="mfa_reset_requests",
                    target_id=str(req.id), actor_id=None,
                    company_id=fields.get("company_id"),
                    detail={"account_kind": kind, "request_ip": ip})
    db.commit()
    who_text = {"employee": "your company's admins", "surveyor": "AsheFlow support",
                "staff": "a super admin"}[kind]
    return {"detail": f"Request sent to {who_text}. Once they reset it, sign in and set up two-factor again.",
            "sent_to": who_text}

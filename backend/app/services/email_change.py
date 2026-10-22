"""Changing an account's email, for every kind of account (ADR-563).

One place applies a change, whoever asked for it:
  - self-service (two codes, ADR-541 R2) for tenants and platform accounts;
  - an admin-started change for someone who lost the inbox, which waits for
    the NEW inbox to confirm a link (D3).

Cognito's verified address is the record (D1). It is written first, with the
admin API (a user token can't write `email` since ADR-558), and only then
mirrored to Employee.email / SurveyContributor.email. Then every session ends
and the OLD address is told.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone

from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import settings
from app.services import account_security

logger = logging.getLogger(__name__)

LINK_HOURS = 72
PRIVILEGED_PLATFORM = {"super_admin", "platform_support"}


class EmailChangeError(Exception):
    """A change that can't proceed; `.status` and `.detail` are safe to show."""

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


def token_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def cognito_account(username: str) -> dict | None:
    """sub, username, email, verified, name and groups; None if it can't be read."""
    client = account_security._cognito()
    pool = settings.aws_cognito_user_pool_id
    try:
        u = client.admin_get_user(UserPoolId=pool, Username=username)
        groups = {g["GroupName"] for g in client.admin_list_groups_for_user(
            UserPoolId=pool, Username=u["Username"], Limit=60).get("Groups", [])}
    except (ClientError, BotoCoreError) as exc:
        code = exc.response.get("Error", {}).get("Code") if isinstance(exc, ClientError) else type(exc).__name__
        logger.warning("email change: account lookup failed: %s", code)
        return None
    attrs = {a["Name"]: a.get("Value") for a in u.get("UserAttributes", [])}
    return {"sub": attrs.get("sub"), "username": u["Username"], "email": (attrs.get("email") or "").lower() or None,
            "verified": attrs.get("email_verified") == "true", "name": attrs.get("name") or u["Username"],
            "groups": groups}


def address_taken(email: str, sub: str) -> bool:
    """Another Cognito account already uses this address. Email isn't an identity
    any more (ADR-560), but two accounts sharing one recovery inbox is still a
    trap for resets, so it's refused."""
    try:
        users = account_security._cognito().list_users(
            UserPoolId=settings.aws_cognito_user_pool_id, Filter=f'email = "{email}"', Limit=5).get("Users", [])
    except (ClientError, BotoCoreError):
        raise EmailChangeError(502, "Couldn't check that address. Try again.")
    for u in users:
        other = next((a["Value"] for a in u.get("Attributes", []) if a["Name"] == "sub"), None)
        if other and other != sub:
            return True
    return False


def apply_change(db, *, username: str, new_email: str, actor: dict, confirmed_by: str) -> dict:
    """Write the new address everywhere, end every session, tell the old address.

    `actor` goes into the audit row: {"kind": ..., "ref": ...}. Commits.
    Raises EmailChangeError if the account can't be read or written.
    """
    from app.models.employee import Employee
    from app.models.survey_register import SurveyContributor
    from app.services.audit import write_audit

    acct = cognito_account(username)
    if not acct or not acct["sub"]:
        raise EmailChangeError(404, "That account couldn't be found.")
    sub, old_email = acct["sub"], acct["email"]
    new_email = new_email.strip().lower()

    try:
        account_security._cognito().admin_update_user_attributes(
            UserPoolId=settings.aws_cognito_user_pool_id, Username=acct["username"],
            UserAttributes=[{"Name": "email", "Value": new_email},
                            {"Name": "email_verified", "Value": "true"}])
    except (ClientError, BotoCoreError) as exc:
        code = exc.response.get("Error", {}).get("Code") if isinstance(exc, ClientError) else type(exc).__name__
        logger.error("email change: cognito update failed: %s", code)
        raise EmailChangeError(502, "Couldn't update the email. Try again.")

    # D1: the database copies follow Cognito, never the other way round.
    employee = db.query(Employee).filter(Employee.cognito_sub == sub).first()
    company_id = None
    if employee is not None:
        employee.email = new_email
        employee.email_bounced_at = None
        employee.email_bounce_type = None
        company_id = employee.company_id
        signed_out = account_security.end_all_sessions(employee, acct["username"])
    else:
        signed_out = account_security.end_platform_sessions(db, sub, acct["username"])
        # A surveyor is a platform account (no Employee row); mirror its record.
        contributor = db.query(SurveyContributor).filter(SurveyContributor.cognito_sub == sub).first()
        if contributor is not None:
            contributor.email = new_email

    db.flush()
    write_audit(
        db, action_type="account.email_changed",
        target_table="employees" if employee is not None else "cognito_users",
        target_id=str(employee.id) if employee is not None else sub,
        actor_id=str(actor["employee_id"]) if actor.get("employee_id") else None,
        company_id=str(company_id) if company_id else None,
        detail={"from": account_security.mask_email(old_email or ""),
                "to": account_security.mask_email(new_email),
                "confirmed_by": confirmed_by, "actor_kind": actor.get("kind"), "actor_ref": actor.get("ref"),
                "signed_out_everywhere": signed_out})

    # D2: a recovery-address change on an account that reaches every tenant is
    # something the other super admins should see.
    if acct["groups"] & PRIVILEGED_PLATFORM:
        from app.services.integration_alerts import raise_platform_alert
        raise_platform_alert(
            db, alert_type="account.email_changed", company_id=None, severity="warning",
            subject_kind="platform", subject_ref=acct["username"],
            subject_role=next(iter(sorted(acct["groups"] & PRIVILEGED_PLATFORM))),
            message=(f"The email on platform account {acct['username']} was changed "
                     f"({confirmed_by.replace('_', ' ')}). If nobody expected this, check the account."),
            refresh_message=True)
    db.commit()

    # After the commit: the change stands even if the notice can't be sent.
    old_notified = False
    if old_email and old_email != new_email:
        from app.services.email import send_email_changed_notice
        try:
            send_email_changed_notice(
                to_email=old_email, employee_name=acct["name"],
                new_email_masked=account_security.mask_email(new_email),
                when=datetime.now(timezone.utc).strftime("%d %B %Y at %H:%M UTC"),
                account_ref=str(employee.id) if employee is not None else sub)
            old_notified = True
        except Exception as exc:
            logger.warning("email change: old-address notice failed: %s", type(exc).__name__)
    return {"email": new_email, "signed_out": signed_out, "old_notified": old_notified}


def start_admin_change(db, *, username: str, kind: str, company_id, new_email: str,
                       by_kind: str, by_ref: str, by_label: str) -> datetime:
    """D3: record a pending change and send the confirmation link to the NEW address.

    Replaces any pending change for the account. Commits. Returns the expiry.
    """
    from app.models.email_change_request import EmailChangeRequest
    from app.services.audit import write_audit
    from app.services.email import send_email_change_link

    acct = cognito_account(username)
    if not acct or not acct["sub"]:
        raise EmailChangeError(404, "That account couldn't be found.")
    new_email = new_email.strip().lower()
    if new_email == acct["email"]:
        raise EmailChangeError(400, "That's already the account's email.")
    if address_taken(new_email, acct["sub"]):
        raise EmailChangeError(409, "That email is already used by another account.")

    now = datetime.now(timezone.utc)
    for old in db.query(EmailChangeRequest).filter(EmailChangeRequest.cognito_sub == acct["sub"],
                                                   EmailChangeRequest.status == "pending"):
        old.status, old.closed_at = "cancelled", now
    db.flush()
    raw = secrets.token_urlsafe(32)
    expires = now + timedelta(hours=LINK_HOURS)
    req = EmailChangeRequest(cognito_sub=acct["sub"], cognito_username=acct["username"], account_kind=kind,
                             company_id=company_id, new_email=new_email, token_hash=token_hash(raw),
                             requested_by_kind=by_kind, requested_by_ref=str(by_ref), expires_at=expires)
    db.add(req)
    db.flush()
    write_audit(db, action_type="account.email_change_requested", target_table="email_change_requests",
                target_id=str(req.id), company_id=str(company_id) if company_id else None,
                detail={"account_kind": kind, "to": account_security.mask_email(new_email),
                        "requested_by_kind": by_kind, "requested_by_ref": str(by_ref)})
    db.commit()
    try:
        send_email_change_link(to_email=new_email, name=acct["name"], token=raw, requested_by=by_label,
                               hours=LINK_HOURS, account_ref=acct["sub"])
    except Exception as exc:
        logger.warning("email change: link send failed: %s", type(exc).__name__)
        req.status, req.closed_at = "cancelled", datetime.now(timezone.utc)
        db.commit()
        raise EmailChangeError(502, "Couldn't send the confirmation email. Check the address and try again.")
    return expires


def confirm_admin_change(db, raw_token: str) -> dict:
    """D3: the link from the new inbox. Applies the change once."""
    from app.models.email_change_request import EmailChangeRequest

    req = db.query(EmailChangeRequest).filter(EmailChangeRequest.token_hash == token_hash(raw_token)).first()
    if req is None or req.status != "pending":
        raise EmailChangeError(400, "That link isn't valid any more. Ask for a new one.")
    expires = req.expires_at if req.expires_at.tzinfo else req.expires_at.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        req.status, req.closed_at = "expired", datetime.now(timezone.utc)
        db.commit()
        raise EmailChangeError(400, "That link has expired. Ask for a new one.")
    result = apply_change(db, username=req.cognito_username, new_email=req.new_email,
                          actor={"kind": req.requested_by_kind, "ref": req.requested_by_ref},
                          confirmed_by="link_to_new_address")
    req.status, req.closed_at = "applied", datetime.now(timezone.utc)
    db.commit()
    return result


def cancel_admin_change(db, *, sub: str, by_kind: str, by_ref: str) -> bool:
    """Withdraw a pending admin-started change. Audited: one row per cancel."""
    from app.models.email_change_request import EmailChangeRequest
    from app.services.audit import write_audit
    rows = db.query(EmailChangeRequest).filter(EmailChangeRequest.cognito_sub == sub,
                                               EmailChangeRequest.status == "pending").all()
    for r in rows:
        r.status, r.closed_at = "cancelled", datetime.now(timezone.utc)
        write_audit(db, action_type="account.email_change_cancelled", target_table="email_change_requests",
                    target_id=str(r.id), company_id=str(r.company_id) if r.company_id else None,
                    detail={"cancelled_by_kind": by_kind, "cancelled_by_ref": str(by_ref)})
    db.commit()
    return bool(rows)

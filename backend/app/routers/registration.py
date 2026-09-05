import secrets
import boto3
import logging
from datetime import datetime, timezone, timedelta
from uuid import UUID

from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy.orm import Session

from app.api.deps import RoleChecker, get_caller_employee
from app.api.ratelimit import limiter
from app.core.config import settings
from app.database import get_db
from app.services.audit import write_audit
from app.models.employee import Employee
from app.models.invite_token import InviteToken
from app.services.email import send_invite_email, send_credentials_email
from app.services.integration_alerts import (
    raise_platform_alert, EMAIL_DELIVERY_FAILED, EMAIL_DOWN_MESSAGE,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/registration", tags=["registration"])

# ADR-256/264 added captain, field_supervisor and driver_trainee. A role missing
# here resolves to None via .get() and the Cognito group silently never syncs —
# the user keeps their OLD group and its permissions after a role change.
# Mirrored in routers/registration.py; the two copies must stay in sync.
ROLE_TO_COGNITO_GROUP: dict[str, str] = {
    "driver":           "driver",
    "walker":           "walker",
    "trainer":          "trainer",
    "trainee":          "trainee",
    "dispatch":         "dispatch",
    "management":       "management",
    "admin":            "admin",
    "captain":          "captain",
    "field_supervisor": "field_supervisor",
    "driver_trainee":   "driver_trainee",
}


# ── schemas ──────────────────────────────────────────────────────────────────

class InviteRequest(BaseModel):
    employee_id: UUID


class ValidateResponse(BaseModel):
    employee_id: str
    name: str
    email: str
    role: str
    phone_last4: str | None  # last 4 digits of phone on file, or None


class CompleteRequest(BaseModel):
    token: str
    discord_id: str
    phone_number: str
    # No username or password — Cognito generates a temp password,
    # employee is forced to reset on first login.

    @field_validator("discord_id")
    @classmethod
    def discord_id_valid(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Discord ID is required.")
        return v

    @field_validator("phone_number")
    @classmethod
    def phone_valid(cls, v: str) -> str:
        digits = "".join(c for c in v if c.isdigit())
        if len(digits) < 10:
            raise ValueError("Phone number must contain at least 10 digits.")
        return v.strip()


# ── helpers ──────────────────────────────────────────────────────────────────

def _cognito():
    return boto3.client("cognito-idp", region_name=settings.aws_region)


def _derive_username(name: str, db: Session) -> str:
    """Derive a unique username as firstname.lastname with optional numeric suffix.

    'Jane Smith' → 'jane.smith', or 'jane.smith2' if taken, etc.
    Non-alphanumeric characters in name parts are stripped.
    """
    import re
    parts = name.strip().lower().split()
    first = re.sub(r"[^a-z0-9]", "", parts[0]) if parts else "user"
    last  = re.sub(r"[^a-z0-9]", "", parts[-1]) if len(parts) > 1 else ""
    base  = f"{first}.{last}" if last else first

    # ADR-380 D5 — bounded. 100 employees sharing one normalised name in a
    # single Cognito pool is not a roster; it is a bug or an attack, and either
    # deserves a refusal rather than a spin.
    #
    # The cap is deliberately far above any real collision count: `username` is
    # globally unique (matching Cognito's flat namespace), so this counts
    # `jane.smith` across ALL tenants, not one.
    candidate = base
    suffix    = 2
    MAX_SUFFIX = 100
    while db.query(Employee).filter(Employee.username == candidate).first():
        if suffix > MAX_SUFFIX:
            logger.error(
                "username derivation exhausted %d suffixes for base %r",
                MAX_SUFFIX, base,
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Could not allocate a unique username. Please try again.",
            )
        candidate = f"{base}{suffix}"
        suffix += 1
    return candidate


def _get_valid_token(token_str: str, db: Session) -> InviteToken:
    record = db.query(InviteToken).filter(InviteToken.token == token_str).first()
    # Uniform 404 for all invalid/expired/used states — prevents token oracle enumeration
    if not record or record.used or datetime.now(timezone.utc) > record.expires_at:
        raise HTTPException(status_code=404, detail="Invite link is invalid or has expired.")
    return record


# ── endpoints ────────────────────────────────────────────────────────────────

@router.post("/invite", status_code=status.HTTP_200_OK)
@limiter.limit("10/minute")
def send_invite(
    request: Request,
    body: InviteRequest,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(RoleChecker(["management", "admin"])),
    db: Session = Depends(get_db),
):
    """Generate an invite token for a pending employee and email them the registration link.

    Can be called multiple times to re-send if the previous link expired.
    Each call invalidates the previous token by replacing it.
    """
    employee = db.query(Employee).filter(
        Employee.id == body.employee_id,
        Employee.company_id == caller.company_id,
    ).first()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found.")
    if not employee.email:
        raise HTTPException(status_code=400, detail="Employee has no email address on file.")
    if employee.account_status == "active":
        raise HTTPException(status_code=400, detail="Employee has already registered.")

    # Invalidate any existing token for this employee
    db.query(InviteToken).filter(InviteToken.employee_id == employee.id).delete()

    token_str = secrets.token_urlsafe(48)
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.invite_expiry_days)
    record = InviteToken(
        token=token_str,
        company_id=caller.company_id,
        employee_id=employee.id,
        expires_at=expires_at,
    )
    db.add(record)
    db.commit()

    try:
        send_invite_email(
            to_email=employee.email,
            employee_name=employee.name,
            token=token_str,
        )
    except ClientError as e:
        logger.error("Failed to send invite email to %s: %s", employee.email, e)
        raise HTTPException(
            status_code=502,
            detail="Invite token created but the invitation email could not be delivered. Please try re-sending the invite.",
        )

    employee.invited_at = datetime.now(timezone.utc)
    # Access-control event: an invite is the credential that lets someone into the
    # tenant. The token itself is deliberately NOT recorded — an audit row is
    # readable by other admins, and a live token is a working credential.
    write_audit(
        db=db,
        company_id=str(caller.company_id),
        actor_id=str(caller.id),
        action_type="employee.invite_sent",
        target_table="employees",
        target_id=str(employee.id),
        after={"employee_id": str(employee.id),
               "account_status": employee.account_status,
               "expires_at": record.expires_at.isoformat() if record.expires_at else None},
    )
    db.commit()

    return {"detail": f"Invite sent to {employee.email}."}


@router.post("/resend-credentials", status_code=status.HTTP_200_OK)
@limiter.limit("5/minute")
def resend_credentials(
    request: Request,
    body: InviteRequest,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(RoleChecker(["management", "admin"])),
    db: Session = Depends(get_db),
):
    """Re-send the credentials email to a registered-but-not-yet-signed-in employee.

    Only valid for employees in the 'registered' lifecycle state (username set,
    account_status still pending_verification). Generates a fresh temp password,
    updates it in Cognito, and resends the branded credentials email.
    """
    employee = db.query(Employee).filter(
        Employee.id == body.employee_id,
        Employee.company_id == caller.company_id,
    ).first()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found.")
    if not employee.username:
        raise HTTPException(status_code=400, detail="Employee has not completed registration yet. Use Resend Invite instead.")
    if employee.account_status == "active":
        raise HTTPException(status_code=400, detail="Employee has already signed in.")
    if not employee.email:
        raise HTTPException(status_code=400, detail="Employee has no email address on file.")

    import string
    temp_password = (
        secrets.choice(string.ascii_uppercase) +
        secrets.choice(string.ascii_uppercase) +
        secrets.choice(string.ascii_uppercase) +
        secrets.choice(string.digits) +
        secrets.choice(string.digits) +
        secrets.choice(string.digits) +
        secrets.choice(string.ascii_lowercase) +
        secrets.choice(string.ascii_lowercase) +
        secrets.choice("!@#$%^&*") +
        secrets.choice("!@#$%^&*")
    )

    try:
        _cognito().admin_set_user_password(
            UserPoolId=settings.aws_cognito_user_pool_id,
            Username=employee.username,
            Password=temp_password,
            Permanent=False,
        )
    except ClientError as e:
        logger.error("admin_set_user_password failed for %s: %s", employee.username, e.response["Error"]["Code"])
        raise HTTPException(status_code=502, detail="Failed to reset credentials. Please try again.")

    # Audit BEFORE the email: the password has already been reset in Cognito at
    # this point, and the email step below can raise a 502. Auditing after it
    # would leave a successful credential reset with no record whenever delivery
    # failed — the case most worth having a record of. This endpoint performs no
    # other DB write, so it commits the audit row itself.
    write_audit(
        db=db,
        company_id=str(caller.company_id),
        actor_id=str(caller.id),
        action_type="employee.credentials_reset",
        target_table="employees",
        target_id=str(employee.id),
        after={"username": employee.username, "permanent": False},
    )
    db.commit()

    try:
        send_credentials_email(
            to_email=employee.email,
            employee_name=employee.name,
            username=employee.username,
            temp_password=temp_password,
        )
    except ClientError as e:
        logger.error("Credentials resend email failed for %s: %s", employee.email, e)
        raise HTTPException(status_code=502, detail="Credentials reset but email delivery failed.")

    return {"detail": f"Credentials resent to {employee.email}."}


@router.get("/validate", response_model=ValidateResponse)
@limiter.limit("20/minute")
def validate_token(
    request: Request,
    token: str,
    db: Session = Depends(get_db),
):
    """Validate an invite token and return safe employee info for the registration form.

    Called by the frontend when the user lands on /register?token=...
    Does NOT consume the token.
    """
    record = _get_valid_token(token, db)
    employee = db.query(Employee).filter(Employee.id == record.employee_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="Invite link is invalid.")
    if employee.company_id != record.company_id:
        raise HTTPException(status_code=400, detail="Invite link is invalid.")

    # Extract last 4 digits from phone_number if present
    phone_last4 = None
    if employee.phone_number:
        digits = "".join(c for c in employee.phone_number if c.isdigit())
        if len(digits) >= 4:
            phone_last4 = digits[-4:]

    return ValidateResponse(
        employee_id=str(employee.id),
        name=employee.name,
        email=employee.email or "",
        role=employee.role,
        phone_last4=phone_last4,
    )


@router.post("/complete", status_code=status.HTTP_200_OK)
@limiter.limit("5/minute")
def complete_registration(
    request: Request,
    body: CompleteRequest,
    db: Session = Depends(get_db),
):
    """Complete employee registration: collect missing info, create Cognito account.

    1. Validates the token
    2. Checks Discord ID is not already taken in this company
    3. Derives username as firstname.lastname (with numeric suffix if taken)
    4. Creates Cognito user via AdminCreateUser — Cognito generates a temp password
       and sends it to the employee's email; they are forced to reset on first login
    5. Adds the user to their role group
    6. Stamps cognito_sub, username, discord_id, phone_number on the Employee record
    7. Marks the token used
    8. Sends a welcome email with the derived username
    """
    record = _get_valid_token(body.token, db)
    employee = db.query(Employee).filter(Employee.id == record.employee_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="Invite link is invalid.")
    if employee.company_id != record.company_id:
        raise HTTPException(status_code=400, detail="Invite link is invalid.")

    # Discord ID uniqueness within the company
    if db.query(Employee).filter(
        Employee.company_id == employee.company_id,
        Employee.discord_id == body.discord_id,
        Employee.id != employee.id,
    ).first():
        raise HTTPException(status_code=409, detail="That Discord ID is already linked to another account.")

    username = _derive_username(employee.name, db)

    # Generate our own temp password so we can include it in our branded email
    # instead of letting Cognito send its own plain-text system email.
    # Format: 3 uppercase + 3 digits + 3 lowercase + 2 symbols — satisfies
    # Cognito's default password policy (upper, lower, number, symbol, min 8).
    import string
    temp_password = (
        secrets.choice(string.ascii_uppercase) +
        secrets.choice(string.ascii_uppercase) +
        secrets.choice(string.ascii_uppercase) +
        secrets.choice(string.digits) +
        secrets.choice(string.digits) +
        secrets.choice(string.digits) +
        secrets.choice(string.ascii_lowercase) +
        secrets.choice(string.ascii_lowercase) +
        secrets.choice("!@#$%^&*") +
        secrets.choice("!@#$%^&*")
    )

    cognito = _cognito()

    # SUPPRESS Cognito's system email — we send our own branded credentials email.
    # Retry with a numeric suffix if Cognito already has that username (e.g. orphaned
    # user from a previous failed registration that wasn't cleaned up in Cognito).
    cognito_sub = None
    response = None
    suffix = 2
    max_attempts = 10
    for attempt in range(max_attempts):
        try:
            response = cognito.admin_create_user(
                UserPoolId=settings.aws_cognito_user_pool_id,
                Username=username,
                TemporaryPassword=temp_password,
                UserAttributes=[
                    {"Name": "email",          "Value": employee.email or ""},
                    {"Name": "email_verified", "Value": "true"},
                    {"Name": "name",           "Value": employee.name},
                ],
                MessageAction="SUPPRESS",
            )
            cognito_sub = next(
                (a["Value"] for a in response["User"]["Attributes"] if a["Name"] == "sub"),
                None,
            )
            break
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code == "UsernameExistsException":
                # Cognito has this username (orphaned) — try the next suffix
                import re
                base = re.sub(r'\d+$', '', username)
                username = f"{base}{suffix}"
                suffix += 1
                logger.warning("Username exists in Cognito, retrying as %s", username)
                continue
            logger.error("AdminCreateUser failed for employee %s: %s", employee.id, e)
            raise HTTPException(status_code=502, detail="Failed to create account. Please try again.")
    else:
        raise HTTPException(status_code=502, detail="Could not allocate a unique username. Please try again.")

    # Add to role group (best-effort)
    group = ROLE_TO_COGNITO_GROUP.get(employee.role)
    if group:
        try:
            cognito.admin_add_user_to_group(
                UserPoolId=settings.aws_cognito_user_pool_id,
                Username=username,
                GroupName=group,
            )
        except ClientError as e:
            logger.error("AdminAddUserToGroup failed for %s: %s", username, e)

    # Stamp the employee record — account_status stays pending_verification until
    # they actually sign in (get_caller_employee flips it to active on first login)
    employee.username     = username
    employee.cognito_sub  = cognito_sub
    employee.discord_id   = body.discord_id
    employee.phone_number = body.phone_number

    record.used = True
    # No caller: this endpoint is public and authenticated by the invite token.
    # The actor IS the invitee, so actor_id is their own employee id — this is the
    # row that records a Cognito account being created and added to a role group.
    write_audit(
        db=db,
        company_id=str(employee.company_id),
        actor_id=str(employee.id),
        action_type="employee.registration_complete",
        target_table="employees",
        target_id=str(employee.id),
        after={"username": username, "role": employee.role,
               "cognito_sub_set": cognito_sub is not None,
               "discord_linked": body.discord_id is not None},
    )
    db.commit()

    # Send one branded email with both username and temp password
    email_sent = False
    if employee.email:
        try:
            send_credentials_email(
                to_email=employee.email,
                employee_name=employee.name,
                username=username,
                temp_password=temp_password,
            )
            email_sent = True
        except ClientError as e:
            logger.error("Credentials email failed for %s: %s", employee.email, e)
            # ADR-336 D1 — SES is PLATFORM infrastructure; a company admin
            # cannot verify a sending identity or lift a sandbox limit.
            #
            # Dim 7: the recipient's address is deliberately NOT in the alert.
            # It is the payload of the thing that failed, not something a
            # cross-tenant board needs, and it would put an employee's email on
            # a surface spanning every tenant.
            raise_platform_alert(
                db,
                alert_type=EMAIL_DELIVERY_FAILED,
                company_id=employee.company_id,
                message=EMAIL_DOWN_MESSAGE,
            )
            db.commit()

    # ADR-336 D1 — do not promise an email that failed to send. This returned
    # "Check your email for sign-in credentials" unconditionally, so a new
    # employee whose email bounced was told to wait for something that would
    # never arrive, with no reason to suspect the system.
    detail = (
        "Registration complete. Check your email for sign-in credentials."
        if email_sent or not employee.email
        else "Registration complete, but the credentials email could not be sent. "
             "Contact your manager for your sign-in details."
    )
    return {"detail": detail, "username": username, "email_sent": email_sent}


@router.get("/pending-invites")
def get_pending_invites(
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(RoleChecker(["admin"])),
    db: Session = Depends(get_db),
):
    """Return outstanding (unused, not-yet-expired) invite tokens for this company.

    Allows admins to see which employees haven't completed registration yet and
    whether their link is still active or has expired.
    """
    now = datetime.now(timezone.utc)

    tokens = (
        db.query(InviteToken)
        .filter(
            InviteToken.company_id == caller.company_id,
            InviteToken.used == False,
        )
        .order_by(InviteToken.created_at.desc())
        .all()
    )

    employee_ids = [t.employee_id for t in tokens]
    emp_map = {
        e.id: e
        for e in db.query(Employee).filter(
            Employee.id.in_(employee_ids),
            Employee.company_id == caller.company_id,
        ).all()
    }

    return [
        {
            "employee_id":   str(t.employee_id),
            "employee_name": emp_map[t.employee_id].name if t.employee_id in emp_map else None,
            "employee_role": emp_map[t.employee_id].role if t.employee_id in emp_map else None,
            "invited_at":    t.created_at.isoformat(),
            "expires_at":    t.expires_at.isoformat(),
            "expired":       now > t.expires_at,
        }
        for t in tokens
    ]

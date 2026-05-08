import secrets
import boto3
import logging
from datetime import datetime, timezone, timedelta
from uuid import UUID

from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy.orm import Session

from app.api.deps import RoleChecker, get_caller_employee
from app.core.config import settings
from app.database import get_db
from app.models.employee import Employee
from app.models.invite_token import InviteToken
from app.services.email import send_invite_email

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/registration", tags=["registration"])

ROLE_TO_COGNITO_GROUP: dict[str, str] = {
    "driver":     "driver",
    "walker":     "walker",
    "trainer":    "trainer",
    "trainee":    "trainee",
    "dispatch":   "dispatch",
    "management": "management",
    "admin":      "admin",
}


# ── schemas ──────────────────────────────────────────────────────────────────

class InviteRequest(BaseModel):
    employee_id: UUID


class ValidateResponse(BaseModel):
    employee_id: str
    name: str
    email: str
    role: str


class CompleteRequest(BaseModel):
    token: str
    username: str
    password: str

    @field_validator("username")
    @classmethod
    def username_valid(cls, v: str) -> str:
        v = v.strip().lower()
        if len(v) < 3:
            raise ValueError("Username must be at least 3 characters.")
        if not all(c.isalnum() or c in (".", "_", "-") for c in v):
            raise ValueError("Username may only contain letters, numbers, dots, underscores, and hyphens.")
        return v

    @field_validator("password")
    @classmethod
    def password_valid(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters.")
        return v


# ── helpers ──────────────────────────────────────────────────────────────────

def _cognito():
    return boto3.client("cognito-idp", region_name=settings.aws_region)


def _get_valid_token(token_str: str, db: Session) -> InviteToken:
    record = db.query(InviteToken).filter(InviteToken.token == token_str).first()
    if not record:
        raise HTTPException(status_code=404, detail="Invite link is invalid.")
    if record.used:
        raise HTTPException(status_code=410, detail="This invite link has already been used.")
    if datetime.now(timezone.utc) > record.expires_at:
        raise HTTPException(status_code=410, detail="This invite link has expired.")
    return record


# ── endpoints ────────────────────────────────────────────────────────────────

@router.post("/invite", status_code=status.HTTP_200_OK)
def send_invite(
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
            detail="Invite token created but email delivery failed. Check SES configuration.",
        )

    employee.invited_at = datetime.now(timezone.utc)
    db.commit()

    return {"detail": f"Invite sent to {employee.email}."}


@router.get("/validate", response_model=ValidateResponse)
def validate_token(
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

    return ValidateResponse(
        employee_id=str(employee.id),
        name=employee.name,
        email=employee.email or "",
        role=employee.role,
    )


@router.post("/complete", status_code=status.HTTP_200_OK)
def complete_registration(
    body: CompleteRequest,
    db: Session = Depends(get_db),
):
    """Complete employee registration: set username + password, activate account.

    1. Validates the token
    2. Checks the chosen username is not already taken in Cognito or our DB
    3. Creates the Cognito user with the chosen username and permanent password
    4. Adds the user to their role group
    5. Stamps cognito_sub, username, activates the Employee record
    6. Marks the token used
    """
    record = _get_valid_token(body.token, db)
    employee = db.query(Employee).filter(Employee.id == record.employee_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="Invite link is invalid.")

    # Username uniqueness check in DB
    if db.query(Employee).filter(
        Employee.username == body.username,
        Employee.id != employee.id,
    ).first():
        raise HTTPException(status_code=409, detail="That username is already taken.")

    cognito = _cognito()

    # Create the Cognito user with the employee's chosen username
    try:
        response = cognito.admin_create_user(
            UserPoolId=settings.aws_cognito_user_pool_id,
            Username=body.username,
            TemporaryPassword=body.password,
            UserAttributes=[
                {"Name": "email",          "Value": employee.email or ""},
                {"Name": "email_verified", "Value": "true"},
                {"Name": "name",           "Value": employee.name},
            ],
            MessageAction="SUPPRESS",  # We sent our own invite email
        )
        cognito_sub = next(
            (a["Value"] for a in response["User"]["Attributes"] if a["Name"] == "sub"),
            None,
        )
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code == "UsernameExistsException":
            raise HTTPException(status_code=409, detail="That username is already taken.")
        logger.error("AdminCreateUser failed for employee %s: %s", employee.id, e)
        raise HTTPException(status_code=502, detail="Failed to create account. Please try again.")

    # Set the password as permanent (no force-change on first login)
    try:
        cognito.admin_set_user_password(
            UserPoolId=settings.aws_cognito_user_pool_id,
            Username=body.username,
            Password=body.password,
            Permanent=True,
        )
    except ClientError as e:
        logger.error("AdminSetUserPassword failed for %s: %s", body.username, e)
        # Clean up the Cognito user we just created
        try:
            cognito.admin_delete_user(
                UserPoolId=settings.aws_cognito_user_pool_id,
                Username=body.username,
            )
        except ClientError:
            pass
        raise HTTPException(status_code=502, detail="Failed to set password. Please try again.")

    # Add to role group
    group = ROLE_TO_COGNITO_GROUP.get(employee.role)
    if group:
        try:
            cognito.admin_add_user_to_group(
                UserPoolId=settings.aws_cognito_user_pool_id,
                Username=body.username,
                GroupName=group,
            )
        except ClientError as e:
            logger.error("AdminAddUserToGroup failed for %s: %s", body.username, e)

    # Activate employee record
    employee.username     = body.username
    employee.cognito_sub  = cognito_sub
    employee.is_active    = True
    employee.account_status = "active"

    record.used = True
    db.commit()

    return {"detail": "Account activated. You can now sign in."}

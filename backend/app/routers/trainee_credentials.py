"""
Trainee credentials router.

Endpoints:
  POST /trainee-credentials/{trainee_id}   management/admin — send (or update) credentials
  GET  /trainee-credentials/{trainee_id}   management/admin — fetch credentials for a trainee
  GET  /trainee-credentials/mine           trainee — fetch own credentials
"""

import uuid
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.api.deps import get_caller_employee, RoleChecker
from app.core.encryption import decrypt, encrypt
from app.database import get_db
from app.models.employee import Employee
from app.models.notification import Notification
from app.models.trainee_credentials import TraineeCredentials

router = APIRouter(
    prefix="/trainee-credentials",
    tags=["trainee-credentials"],
)

_mgmt_admin = RoleChecker(["management", "admin"])

# ORE training link — delivered once in the notification, never persisted.
_ORE_LINK = (
    "https://atoz.amazon.work/learn/rustici/launch"
    "?trainingPath=%5B%22TCRLERN20240917180409e3c8b8ca%22%5D"
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class CredentialsSendRequest(BaseModel):
    flex_email: EmailStr
    clock_in_code: str


class CredentialsResponse(BaseModel):
    employee_id: UUID
    flex_email: str
    clock_in_code: str
    sent_by: UUID
    sent_at: str
    updated_at: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_response(row: TraineeCredentials) -> CredentialsResponse:
    return CredentialsResponse(
        employee_id=row.employee_id,
        flex_email=decrypt(row.flex_email),
        clock_in_code=decrypt(row.clock_in_code),
        sent_by=row.sent_by,
        sent_at=row.sent_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/{trainee_id}", response_model=CredentialsResponse, status_code=status.HTTP_200_OK)
def send_credentials(
    trainee_id: UUID,
    body: CredentialsSendRequest,
    _: dict = Depends(_mgmt_admin),
    caller: Employee = Depends(get_caller_employee),
    db: Session = Depends(get_db),
):
    """Send (or re-send) credentials to a phase-1 trainee.

    Creates the credentials row on first call; updates it on subsequent calls.
    Each call fires a ``credentials_sent`` notification that includes the ORE
    training link — the link is NOT stored.
    """
    trainee = db.query(Employee).filter(
        Employee.id == trainee_id,
        Employee.company_id == caller.company_id,
        Employee.role == "trainee",
    ).first()
    if not trainee:
        raise HTTPException(status_code=404, detail="Trainee not found in your company.")

    encrypted_email = encrypt(str(body.flex_email))
    encrypted_code  = encrypt(body.clock_in_code)

    row = db.query(TraineeCredentials).filter(
        TraineeCredentials.employee_id == trainee_id,
        TraineeCredentials.company_id == caller.company_id,
    ).first()

    if row:
        row.flex_email    = encrypted_email
        row.clock_in_code = encrypted_code
        row.sent_by       = caller.id
    else:
        row = TraineeCredentials(
            id=uuid.uuid4(),
            company_id=caller.company_id,
            employee_id=trainee_id,
            flex_email=encrypted_email,
            clock_in_code=encrypted_code,
            sent_by=caller.id,
        )
        db.add(row)

    notification = Notification(
        company_id=trainee.company_id,
        employee_id=trainee_id,
        type="credentials_sent",
        message=(
            f"Your manager has sent your work credentials.\n\n"
            f"Complete your ORE training here: {_ORE_LINK}\n\n"
            f"Your flex email and clock-in code are available in the app under My Credentials."
        ),
    )
    db.add(notification)
    db.commit()
    db.refresh(row)

    return _to_response(row)


@router.get("/mine", response_model=CredentialsResponse)
def get_my_credentials(
    caller: Employee = Depends(get_caller_employee),
    db: Session = Depends(get_db),
):
    """Trainee fetches their own credentials."""
    if caller.role != "trainee":
        raise HTTPException(status_code=403, detail="Only trainees can access this endpoint.")

    row = db.query(TraineeCredentials).filter(
        TraineeCredentials.employee_id == caller.id,
        TraineeCredentials.company_id == caller.company_id,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="No credentials have been sent yet.")

    return _to_response(row)


@router.get("/{trainee_id}", response_model=CredentialsResponse)
def get_credentials(
    trainee_id: UUID,
    _: dict = Depends(_mgmt_admin),
    caller: Employee = Depends(get_caller_employee),
    db: Session = Depends(get_db),
):
    """Management/admin fetches credentials for a specific trainee."""
    row = db.query(TraineeCredentials).filter(
        TraineeCredentials.employee_id == trainee_id,
        TraineeCredentials.company_id == caller.company_id,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="No credentials on file for this trainee.")

    return _to_response(row)

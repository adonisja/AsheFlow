"""
Trainee credentials router.

Endpoints:
  POST /trainee-credentials/{trainee_id}   management/admin — send (or replace) credentials
  GET  /trainee-credentials/{trainee_id}   management/admin — handoff STATUS, never the values
  GET  /trainee-credentials/mine           trainee — own credentials while they exist
  POST /trainee-credentials/mine/confirm   trainee — "I changed both": destroys the values

ADR-491: these are temporary credentials management issues and the trainee
changes on first sign-in. AsheFlow holds them only for the handoff — until the
trainee confirms, or `trainee_credential_retention_days` after sending, whichever
comes first. Management is the source, so it never reads them back.
"""

import logging
import uuid
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from datetime import datetime, timedelta, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy.orm import Session

from app.api.deps import get_caller_employee, RoleChecker
from app.core.config import settings
from app.core.encryption import decrypt, encrypt
from app.database import get_db
from app.models.employee import Employee
from app.models.trainee_credentials import TraineeCredentials
from app.services.audit import write_audit
from app.services.notify import write_notification
from app.tasks.discord_delivery import send_discord

router = APIRouter(
    prefix="/trainee-credentials",
    tags=["trainee-credentials"],
)

_mgmt_admin = RoleChecker(["management", "admin"])
# ADR-491 D1 — only the person who changed the codes can say they did.
_trainee_only = RoleChecker(["trainee"])

logger = logging.getLogger(__name__)


def _fire_discord_dm(discord_id: str, message: str) -> None:
    # ADR-487 D7: the send is a Celery task, not a daemon thread. Retry,
    # backoff, jitter and response classification live there; this builds
    # the payload and hands it over.
    send_discord.delay("dm", {"discord_id": discord_id, "message": message})

# ORE training link — delivered once in the notification, never persisted.
_ORE_LINK = (
    "https://atoz.amazon.work/learn/rustici/launch"
    "?trainingPath=%5B%22TCRLERN20240917180409e3c8b8ca%22%5D"
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class CredentialsSendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    flex_email: EmailStr
    clock_in_code: str = Field(min_length=1, max_length=64)


class CredentialsStatus(BaseModel):
    """The handoff's state, with no secret in it (ADR-491 D3). Management's view."""
    employee_id: UUID
    has_credentials: bool
    sent_by: UUID
    sent_at: datetime
    updated_at: datetime
    confirmed_at: Optional[datetime] = None
    expired_at: Optional[datetime] = None
    # When the values will be destroyed if the trainee never confirms. None once
    # they are gone, or when retention is disabled.
    expires_at: Optional[datetime] = None


class MyCredentials(CredentialsStatus):
    """The trainee's view: the status plus the values while they exist (D4)."""
    flex_email: Optional[str] = None
    clock_in_code: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _expires_at(row: TraineeCredentials) -> Optional[datetime]:
    days = settings.trainee_credential_retention_days
    if row.flex_email is None or days <= 0:
        return None
    return row.sent_at + timedelta(days=days)


def _status_fields(row: TraineeCredentials) -> dict:
    return dict(
        employee_id=row.employee_id,
        has_credentials=row.flex_email is not None,
        sent_by=row.sent_by,
        sent_at=row.sent_at,
        updated_at=row.updated_at,
        confirmed_at=row.confirmed_at,
        expired_at=row.expired_at,
        expires_at=_expires_at(row),
    )


def _to_status(row: TraineeCredentials) -> CredentialsStatus:
    return CredentialsStatus(**_status_fields(row))


def _to_mine(row: TraineeCredentials) -> MyCredentials:
    present = row.flex_email is not None
    return MyCredentials(
        **_status_fields(row),
        flex_email=decrypt(row.flex_email) if present else None,
        clock_in_code=decrypt(row.clock_in_code) if present else None,
    )


def _my_row(db: Session, caller: Employee) -> TraineeCredentials:
    if caller.role != "trainee":
        raise HTTPException(status_code=403, detail="Only trainees can access this endpoint.")
    row = db.query(TraineeCredentials).filter(
        TraineeCredentials.employee_id == caller.id,
        TraineeCredentials.company_id == caller.company_id,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="No credentials have been sent yet.")
    return row


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/{trainee_id}", response_model=CredentialsStatus, status_code=status.HTTP_200_OK)
def send_credentials(
    trainee_id: UUID,
    body: CredentialsSendRequest,
    _: dict = Depends(_mgmt_admin),
    caller: Employee = Depends(get_caller_employee),
    db: Session = Depends(get_db),
):
    """Send (or replace) credentials for a trainee.

    Creates the row on first call; replaces the values on later calls. A replace
    is a NEW handoff: the expiry clock restarts and any earlier confirmation or
    expiry is cleared (ADR-491 D3). Each call fires a ``credentials_sent``
    notification carrying the ORE link — the link is NOT stored.

    Returns the status, not the values: management typed them and has no need to
    read them back.
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
    now = datetime.now(timezone.utc)

    row = db.query(TraineeCredentials).filter(
        TraineeCredentials.employee_id == trainee_id,
        TraineeCredentials.company_id == caller.company_id,
    ).first()

    replaced = row is not None
    if row:
        row.flex_email    = encrypted_email
        row.clock_in_code = encrypted_code
        row.sent_by       = caller.id
        row.sent_at       = now
        row.confirmed_at  = None
        row.expired_at    = None
    else:
        row = TraineeCredentials(
            id=uuid.uuid4(),
            company_id=caller.company_id,
            employee_id=trainee_id,
            flex_email=encrypted_email,
            clock_in_code=encrypted_code,
            sent_by=caller.id,
            sent_at=now,
        )
        db.add(row)

    # ADR-487 D2. GATE in the registry (D8): they cannot use the app without the
    # credentials, so there is nothing to work around the modal for.
    notification = write_notification(
        db,
        company_id=trainee.company_id,
        employee_id=trainee_id,
        type="credentials_sent",
        message=(
            f"Your manager has sent your work credentials.\n\n"
            f"Complete your ORE training here: {_ORE_LINK}\n\n"
            f"Your flex email and clock-in code are available in the app under My Credentials. "
            f"Change both after you sign in, then tap \"I've changed both\"."
        ),
    )
    db.add(notification)
    db.flush()
    write_audit(
        db=db, company_id=caller.company_id, actor_id=caller.id,
        action_type="credentials.sent", target_table="trainee_credentials",
        target_id=str(row.id),
        after={"trainee_id": str(trainee_id), "replaced": replaced},
    )
    db.commit()
    db.refresh(row)

    if trainee.discord_id:
        _fire_discord_dm(
            str(trainee.discord_id),
            "Your manager has sent your sign-in credentials. Check your AsheFlow inbox to view them.",
        )

    return _to_status(row)


@router.get("/mine", response_model=MyCredentials)
def get_my_credentials(
    caller: Employee = Depends(get_caller_employee),
    db: Session = Depends(get_db),
):
    """Trainee fetches their own credentials — the values while they exist, and
    the status once confirmed or expired (ADR-491 D4)."""
    return _to_mine(_my_row(db, caller))


@router.post("/mine/confirm", response_model=MyCredentials)
def confirm_my_credentials_changed(
    _: dict = Depends(_trainee_only),
    caller: Employee = Depends(get_caller_employee),
    db: Session = Depends(get_db),
):
    """The trainee has signed in and changed both codes: destroy the stored values.

    One-way: 409 once the values are already gone, whether by an earlier confirm
    or by expiry (ADR-491 D1).
    """
    row = _my_row(db, caller)
    if row.flex_email is None:
        raise HTTPException(
            status_code=409,
            detail="These credentials are no longer stored. Ask your manager to re-send if you need them.",
        )

    row.flex_email    = None
    row.clock_in_code = None
    row.confirmed_at  = datetime.now(timezone.utc)
    db.flush()
    write_audit(
        db=db, company_id=caller.company_id, actor_id=caller.id,
        action_type="credentials.confirmed", target_table="trainee_credentials",
        target_id=str(row.id),
        before={"has_credentials": True},
        after={"has_credentials": False, "confirmed_at": row.confirmed_at.isoformat()},
    )
    db.commit()
    db.refresh(row)
    return _to_mine(row)


@router.get("/{trainee_id}", response_model=CredentialsStatus)
def get_credentials(
    trainee_id: UUID,
    _: dict = Depends(_mgmt_admin),
    caller: Employee = Depends(get_caller_employee),
    db: Session = Depends(get_db),
):
    """Management/admin see the handoff status for a trainee — never the values
    (ADR-491 D3)."""
    row = db.query(TraineeCredentials).filter(
        TraineeCredentials.employee_id == trainee_id,
        TraineeCredentials.company_id == caller.company_id,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="No credentials on file for this trainee.")

    return _to_status(row)

"""The notification gallery: every type, every surface, before anyone receives it (ADR-507).

Platform-only. Reading is `get_platform_staff`; SENDING writes a notification
into a tenant, so it is `get_super_admin` (ADR-343 D1: platform support reads,
only a super admin writes into a customer's world).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_platform_staff, get_super_admin
from app.models.company import Company
from app.models.employee import Employee
from app.services.audit import super_admin_identity, write_audit
from app.services.notification_gallery import catalog, sample_message
from app.services.notification_spec import SPEC
from app.services.notify import write_notification

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/platform/notification-gallery", tags=["platform"])

#: ADR-280. A company whose data is real. Seed scripts and fault injection
#: already refuse it; fabricated notifications to a real employee are the same
#: class of write, so Send refuses it too.
_LIVE = "live"

#: How long a sample lives. Long enough to look at on a phone and in the inbox,
#: short enough that it does not sit in a test account's list for days.
_SAMPLE_TTL = timedelta(hours=24)


@router.get("")
def get_gallery(_staff: dict = Depends(get_platform_staff)):
    """Every SPEC type with its registry facts, channels, actions and copy."""
    types = catalog()
    return {
        "types": types,
        "summary": {
            "total": len(types),
            "by_source": {s: sum(1 for t in types if t["copy_source"] == s)
                          for s in ("template", "indirect", "unraised")},
        },
    }


@router.get("/targets")
def get_targets(
    db: Session = Depends(get_db),
    _super: dict = Depends(get_super_admin),
):
    """Employees a sample may be sent to: only those in a NON-live company."""
    companies = (
        db.query(Company)
        .filter(Company.data_class != _LIVE, Company.is_active == True)  # noqa: E712
        .order_by(Company.name)
        .all()
    )
    out = []
    for c in companies:
        staff = (
            db.query(Employee.id, Employee.name, Employee.username, Employee.role)
            .filter(Employee.company_id == c.id, Employee.is_active == True)  # noqa: E712
            .order_by(Employee.username)
            .limit(300)
            .all()
        )
        out.append({
            "company_id": str(c.id),
            "company_name": c.name,
            "data_class": c.data_class,
            "employees": [
                {"id": str(e.id), "name": e.name, "username": e.username, "role": e.role}
                for e in staff
            ],
        })
    return {"companies": out}


class SendSampleIn(BaseModel):
    """Dimension 9: one concrete field, unknown keys are a 422."""

    employee_id: UUID
    model_config = ConfigDict(extra="forbid")


@router.post("/{notification_type}/send", status_code=status.HTTP_201_CREATED)
def send_sample(
    notification_type: str,
    payload: SendSampleIn,
    db: Session = Depends(get_db),
    _super: dict = Depends(get_super_admin),
):
    """Raise one REAL notification of this type to a test employee (ADR-507 D3).

    Through `write_notification`, so the normal after-commit delivery runs:
    banner, ticker, inbox, prompt/gate, push and Discord, exactly as a real one.
    The message is marked "Sample · " and expires in 24 hours.
    """
    if notification_type not in SPEC:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown notification type.")

    emp = db.query(Employee).filter(Employee.id == payload.employee_id).first()
    if emp is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found.")

    company = db.query(Company).filter(Company.id == emp.company_id).first()
    if company is None or company.data_class == _LIVE:
        # A live tenant's staff never receive fabricated notifications. Not a
        # 404: the employee exists and the super admin can see it; the refusal
        # is a rule, and saying so is the useful answer.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Samples can only be sent to a test or demo company, never a live one.",
        )

    notif = write_notification(
        db,
        company_id=emp.company_id,
        employee_id=emp.id,
        type=notification_type,
        message=sample_message(notification_type),
        expires_at=datetime.now(timezone.utc) + _SAMPLE_TTL,
    )
    db.flush()
    write_audit(
        db=db,
        company_id=emp.company_id,
        actor_id=None,  # a super admin has no Employee row; identity goes in detail
        action_type="notification.sample_sent",
        target_table="notifications",
        target_id=str(notif.id),
        detail={
            "actor": super_admin_identity(_super),
            "notification_type": notification_type,
            "recipient_employee_id": str(emp.id),
        },
    )
    db.commit()
    return {"notification_id": str(notif.id), "type": notification_type,
            "recipient": emp.username, "message": notif.message}

from uuid import UUID
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List

from app.database import get_db
from app.api.deps import RoleChecker
from app.models.notification import Notification
from app.schemas.notification import NotificationResponse

router = APIRouter(prefix="/notifications", tags=["notifications"])

allow_any_auth = RoleChecker(["driver", "walker", "trainer", "trainee", "dispatch", "management", "admin"])


@router.get("/{employee_id}", response_model=List[NotificationResponse])
def get_notifications(employee_id: UUID, db: Session = Depends(get_db), _: dict = Depends(allow_any_auth)):
    """Get all notifications for an employee, newest first."""
    return (
        db.query(Notification)
        .filter(Notification.employee_id == employee_id)
        .order_by(Notification.created_at.desc())
        .all()
    )


@router.patch("/{notification_id}/read")
def mark_read(notification_id: UUID, db: Session = Depends(get_db), _: dict = Depends(allow_any_auth)):
    """Mark a single notification as read."""
    notif = db.query(Notification).filter(Notification.id == notification_id).first()
    if notif:
        notif.is_read = True
        db.commit()
    return {"ok": True}


@router.patch("/employee/{employee_id}/read-all")
def mark_all_read(employee_id: UUID, db: Session = Depends(get_db), _: dict = Depends(allow_any_auth)):
    """Mark all notifications for an employee as read."""
    db.query(Notification).filter(
        Notification.employee_id == employee_id,
        Notification.is_read == False
    ).update({"is_read": True})
    db.commit()
    return {"ok": True}

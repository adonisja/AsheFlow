from datetime import datetime, timezone, timedelta
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from typing import List

from app.database import get_db
from app.api.deps import RoleChecker, get_caller_employee, Pagination
from app.models.employee import Employee
from app.models.notification import Notification
from app.schemas.notification import NotificationResponse

router = APIRouter(prefix="/notifications", tags=["notifications"])

allow_any_auth   = RoleChecker(["driver", "walker", "trainer", "trainee", "dispatch", "management", "admin"])
allow_management = RoleChecker(["dispatch", "management", "admin"])


@router.get("/{employee_id}", response_model=List[NotificationResponse])
def get_notifications(
    employee_id: UUID,
    skip:  int = Query(default=0,  ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
):
    """Get notifications for an employee, newest first.

    Only the employee themselves or management/dispatch/admin can read them.
    Defaults to the 50 most recent; supports ?skip and ?limit (max 200) for paging.
    """
    if caller.id != employee_id and caller.role not in ("dispatch", "management", "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
    return (
        db.query(Notification)
        .filter(Notification.employee_id == employee_id)
        .order_by(Notification.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


@router.patch("/{notification_id}/read")
def mark_read(
    notification_id: UUID,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
):
    """Mark a single notification as read. Only the owning employee can mark their own."""
    notif = db.query(Notification).filter(Notification.id == notification_id).first()
    if notif:
        if notif.employee_id != caller.id and caller.role not in ("dispatch", "management", "admin"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
        notif.is_read = True
        db.commit()
    return {"ok": True}


@router.patch("/employee/{employee_id}/read-all")
def mark_all_read(
    employee_id: UUID,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
):
    """Mark all notifications for an employee as read."""
    if caller.id != employee_id and caller.role not in ("dispatch", "management", "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
    db.query(Notification).filter(
        Notification.employee_id == employee_id,
        Notification.is_read == False
    ).update({"is_read": True})
    db.commit()
    return {"ok": True}


@router.delete("/prune", status_code=status.HTTP_200_OK)
def prune_notifications(
    days: int = Query(default=30, ge=1, le=365, description="Delete read notifications older than this many days"),
    _: dict = Depends(allow_management),
    db: Session = Depends(get_db),
):
    """Delete read notifications older than N days (default 30). Management/admin only.

    Only removes notifications that have already been marked as read — unread
    notifications are never pruned regardless of age.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    deleted = (
        db.query(Notification)
        .filter(
            Notification.is_read == True,
            Notification.created_at < cutoff,
        )
        .delete(synchronize_session=False)
    )
    db.commit()
    return {"deleted": deleted, "cutoff": cutoff.date().isoformat(), "days": days}

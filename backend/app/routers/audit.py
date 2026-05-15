from datetime import date
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.api.deps import RoleChecker, get_caller_employee, Pagination
from app.models.audit_log import AuditLog
from app.models.employee import Employee

router = APIRouter(prefix="/audit", tags=["audit"])

allow_mgmt = RoleChecker(["management", "admin", "dispatch"])


@router.get("/")
def get_audit_log(
    action_type: Optional[str] = Query(None, description="Filter by action type prefix, e.g. 'pto'"),
    actor_id: Optional[UUID] = Query(None),
    target_table: Optional[str] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    pg: Pagination = Depends(),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_mgmt),
    db: Session = Depends(get_db),
):
    """Return audit log entries scoped to the caller's company. Management and admin only."""
    q = db.query(AuditLog, Employee).outerjoin(
        Employee, AuditLog.actor_id == Employee.id
    ).filter(
        AuditLog.company_id == caller.company_id,
    ).order_by(AuditLog.created_at.desc())

    if action_type:
        q = q.filter(AuditLog.action_type.like(f"{action_type}%"))
    if actor_id:
        q = q.filter(AuditLog.actor_id == actor_id)
    if target_table:
        q = q.filter(AuditLog.target_table == target_table)
    if start_date:
        q = q.filter(AuditLog.created_at >= start_date)
    if end_date:
        q = q.filter(AuditLog.created_at <= end_date)

    rows = pg.apply(q).all()

    return [
        {
            "id":              str(log.id),
            "actor_id":        str(log.actor_id) if log.actor_id else None,
            "actor_name":      emp.name if emp else None,
            "action_type":     log.action_type,
            "target_table":    log.target_table,
            "target_id":       str(log.target_id),
            "before_snapshot": log.before_snapshot,
            "after_snapshot":  log.after_snapshot,
            "created_at":      log.created_at.isoformat() if log.created_at else None,
        }
        for log, emp in rows
    ]

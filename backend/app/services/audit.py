"""Audit log helper.

Usage inside any router — call write_audit() before db.commit():

    write_audit(
        db,
        actor_id=current_user.get("id"),        # cognito sub / employee UUID
        action_type="pto.approved",
        target_table="time_off_requests",
        target_id=str(db_request.id),
        before={"status": "pending"},
        after={"status": "approved"},
    )
    db.commit()
"""

from __future__ import annotations

from typing import Any, Optional
from sqlalchemy.orm import Session
from app.models.audit_log import AuditLog


def write_audit(
    db: Session,
    *,
    action_type: str,
    target_table: str,
    target_id: str,
    actor_id: Optional[str] = None,
    company_id: Optional[str] = None,
    before: Optional[dict[str, Any]] = None,
    after: Optional[dict[str, Any]] = None,
) -> None:
    """Append one immutable audit row to the session (does NOT commit).

    The caller is responsible for committing.  Placing write_audit() just
    before db.commit() ensures the audit row is part of the same transaction
    as the state change it records — either both land or neither does.
    """
    from uuid import UUID as _UUID

    actor_uuid: Optional[_UUID] = None
    if actor_id:
        try:
            actor_uuid = _UUID(str(actor_id))
        except (ValueError, AttributeError):
            pass

    company_uuid: Optional[_UUID] = None
    if company_id:
        try:
            company_uuid = _UUID(str(company_id))
        except (ValueError, AttributeError):
            pass

    try:
        target_uuid = _UUID(str(target_id))
    except (ValueError, AttributeError):
        return  # Silently skip if target_id is not a valid UUID

    db.add(AuditLog(
        actor_id=actor_uuid,
        company_id=company_uuid,
        action_type=action_type,
        target_table=target_table,
        target_id=target_uuid,
        before_snapshot=before,
        after_snapshot=after,
    ))

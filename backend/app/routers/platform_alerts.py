"""Platform-level infrastructure alerts, for super admins (ADR-335).

Deliberately NOT on a company-scoped router. A platform alert may have no owning
tenant (a Discord outage is one incident across every company), so there is no
`company_id` to check a caller against — which is exactly why these endpoints
gate on `get_super_admin` rather than `RoleChecker`.
"""
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_super_admin, get_platform_staff
from app.models.platform_alert import PlatformAlert
from app.services.audit import write_audit, super_admin_identity

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/platform", tags=["platform"])


class PlatformAlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    alert_type: str
    company_id: Optional[UUID]
    message: str
    severity: str
    is_resolved: bool
    occurrence_count: int
    first_seen_at: Optional[datetime]
    last_seen_at: Optional[datetime]
    resolved_at: Optional[datetime]
    resolved_by_email: Optional[str]


class ResolveRequest(BaseModel):
    """Dimension 9 — typed, bounded, closed."""
    model_config = ConfigDict(extra="forbid")
    note: Optional[str] = Field(default=None, max_length=500)


@router.get("/alerts", status_code=status.HTTP_200_OK)
def list_platform_alerts(
    include_resolved: bool = Query(False),
    limit: int = Query(100, ge=1, le=500),
    _super: dict = Depends(get_platform_staff),
    db: Session = Depends(get_db),
) -> list[PlatformAlertOut]:
    """Open infrastructure alerts, newest first (ADR-335 D5).

    No company filter: a super admin is looking across tenants, and a
    platform-wide incident has no tenant to filter by.
    """
    q = db.query(PlatformAlert)
    if not include_resolved:
        q = q.filter(PlatformAlert.is_resolved.is_(False))
    rows = q.order_by(PlatformAlert.last_seen_at.desc()).limit(limit).all()
    return [PlatformAlertOut.model_validate(r, from_attributes=True) for r in rows]


@router.post("/alerts/{alert_id}/resolve", status_code=status.HTTP_200_OK)
def resolve_platform_alert(
    alert_id: UUID,
    body: ResolveRequest,
    _super: dict = Depends(get_super_admin),
    db: Session = Depends(get_db),
) -> PlatformAlertOut:
    """Close an alert by hand (ADR-335 D3).

    Most alerts resolve THEMSELVES when the integration answers again. This is
    for a condition the code cannot detect — and it is the only path that sets
    `resolved_by_sub`, which is how a self-resolve is told apart from a human one.
    """
    row = db.query(PlatformAlert).filter(PlatformAlert.id == alert_id).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alert not found.",
        )
    if row.is_resolved:
        # One-way state stamp — 409 rather than silently re-stamping, so a
        # double click cannot overwrite who actually closed it.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That alert is already resolved.",
        )

    row.is_resolved = True
    row.resolved_at = datetime.now(timezone.utc)
    # Text, not an FK. A super admin has no Employee row, and writing their
    # Cognito sub into an employees FK raises ForeignKeyViolation (ADR-274 D13).
    row.resolved_by_sub = _super.get("id")
    row.resolved_by_email = _super.get("email")

    db.flush()
    write_audit(
        db=db,
        # Platform-scoped: the alert may belong to no tenant.
        company_id=str(row.company_id) if row.company_id else None,
        actor_id=None,  # ADR-274 D13 — super admins leave actor_id NULL
        action_type="platform_alert.resolved",
        target_table="platform_alerts",
        target_id=str(row.id),
        after={**super_admin_identity(_super),
               "alert_type": row.alert_type,
               "note": body.note},
    )
    db.commit()
    db.refresh(row)
    return PlatformAlertOut.model_validate(row, from_attributes=True)

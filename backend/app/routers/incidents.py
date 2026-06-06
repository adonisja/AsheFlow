from datetime import date, datetime, timedelta, timezone
from typing import List, Optional
from uuid import UUID

from app.services.local_date import company_today

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.api.deps import RoleChecker, get_current_user, Pagination, get_caller_employee
from app.services.audit import write_audit
from app.models.incident import Incident
from app.models.employee import Employee
from app.models.truck import Truck
from app.models.truck_assignment import TruckAssignment
from app.models.assignment_member import AssignmentMember
from app.models.notification import Notification
from app.schemas.incident import (
    IncidentCreate, IncidentResponse, IncidentListItem,
    VALID_CATEGORIES, VALID_SEVERITIES, CATEGORY_DEFAULT_SEVERITY,
)

router = APIRouter(prefix="/incidents", tags=["incidents"])

allow_field_staff = RoleChecker(["driver", "walker", "trainer", "trainee"])
allow_management  = RoleChecker(["dispatch", "management", "admin"])


def _resolve_assignment(reporter_id: UUID, date, db: Session) -> tuple[Optional[UUID], Optional[UUID]]:
    """Return (truck_id, assignment_id) for the reporter on the given date, or (None, None)."""
    member = (
        db.query(AssignmentMember)
        .join(TruckAssignment, AssignmentMember.assignment_id == TruckAssignment.id)
        .filter(
            AssignmentMember.employee_id == reporter_id,
            TruckAssignment.date == date,
        )
        .first()
    )
    if not member:
        return None, None
    assignment = db.query(TruckAssignment).filter(TruckAssignment.id == member.assignment_id).first()
    if not assignment:
        return None, None
    return assignment.truck_id, assignment.id


def _resolve_driver_id(assignment_id: UUID, db: Session) -> Optional[UUID]:
    """Return the employee_id of the driver on the given assignment, or None."""
    driver_member = (
        db.query(AssignmentMember)
        .filter(
            AssignmentMember.assignment_id == assignment_id,
            AssignmentMember.role == "driver",
        )
        .first()
    )
    return driver_member.employee_id if driver_member else None


def _notify_management(incident: Incident, reporter: Employee, db: Session):
    """Send notifications to all active dispatch/management/admin for this incident."""
    severity = incident.severity
    notif_type = f"incident_{severity}"  # incident_info | incident_warning | incident_critical

    category_label = incident.category.replace("_", " ").title()
    message = (
        f"{severity.upper()} — {category_label} incident reported by {reporter.name} "
        f"on {incident.date.strftime('%a, %b %d')}. "
        f"{incident.description[:120]}{'…' if len(incident.description) > 120 else ''}"
    )

    recipients = db.query(Employee).filter(
        Employee.company_id == incident.company_id,
        Employee.role.in_(["dispatch", "management", "admin"]),
        Employee.is_active == True,
    ).all()

    for emp in recipients:
        db.add(Notification(
            company_id=incident.company_id,
            employee_id=emp.id,
            type=notif_type,
            message=message,
        ))


# ---------------------------------------------------------------------------
# Submit
# ---------------------------------------------------------------------------

@router.post("/", response_model=IncidentResponse, status_code=status.HTTP_201_CREATED)
def submit_incident(
    payload: IncidentCreate,
    db: Session = Depends(get_db),
    reporter: Employee = Depends(get_caller_employee),
):
    """Submit a new incident report.

    reporter_id is resolved from the authenticated caller's employee record —
    the client cannot supply or override it. Validates category and severity.
    Severity cannot be below the category default (e.g. an injury cannot be
    filed as info). Truck is auto-resolved from today's dispatch assignment.
    Notifies all dispatch/management/admin.
    """
    if payload.category not in VALID_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"Invalid category. Choose from: {', '.join(sorted(VALID_CATEGORIES))}")

    if payload.severity not in VALID_SEVERITIES:
        raise HTTPException(status_code=400, detail=f"Invalid severity. Choose from: info, warning, critical.")

    # Enforce minimum severity per category
    severity_rank = {"info": 0, "warning": 1, "critical": 2}
    min_severity = CATEGORY_DEFAULT_SEVERITY.get(payload.category, "info")
    if severity_rank[payload.severity] < severity_rank[min_severity]:
        raise HTTPException(
            status_code=400,
            detail=f"Severity for '{payload.category}' cannot be lower than '{min_severity}'.",
        )

    truck_id, assignment_id = _resolve_assignment(reporter.id, payload.date, db)

    # Auto-resolve driver — for non-drivers, find the driver on the same truck
    driver_id: Optional[UUID] = None
    if reporter.role != "driver" and assignment_id:
        driver_id = _resolve_driver_id(assignment_id, db)
    elif reporter.role == "driver":
        driver_id = reporter.id

    incident = Incident(
        company_id=reporter.company_id,
        reporter_id=reporter.id,
        truck_id=truck_id,
        driver_id=driver_id,
        date=payload.date,
        category=payload.category,
        severity=payload.severity,
        description=payload.description,
        photo_url=payload.photo_url,
        incident_time=payload.incident_time,
        packages_tba=payload.packages_tba,
        incident_location=payload.incident_location,
        witness_name=payload.witness_name,
        body_part_affected=payload.body_part_affected,
        medical_attention_required=payload.medical_attention_required,
    )
    db.add(incident)
    db.flush()

    _notify_management(incident, reporter, db)

    # Self-notification: reporter gets a record of their own submission
    category_label = incident.category.replace("_", " ").title()
    db.add(Notification(
        company_id=reporter.company_id,
        employee_id=reporter.id,
        type="incident_submitted",
        message=(
            f"Your {category_label} incident report for "
            f"{incident.date.strftime('%a, %b %d')} has been submitted and is under review."
        ),
    ))

    db.commit()
    db.refresh(incident)
    return incident


# ---------------------------------------------------------------------------
# Reporter — own incidents
# ---------------------------------------------------------------------------

@router.get("/my", response_model=List[IncidentResponse])
def get_my_incidents(
    pg: Pagination = Depends(),
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
):
    """Return all incidents submitted by the authenticated caller, newest first.

    reporter_id is resolved from the JWT — callers cannot read another
    employee's incident history by supplying a different UUID.
    """
    q = (
        db.query(Incident)
        .filter(Incident.reporter_id == caller.id, Incident.company_id == caller.company_id)
        .order_by(Incident.created_at.desc())
    )
    return pg.apply(q).all()


# ---------------------------------------------------------------------------
# Management — all incidents
# ---------------------------------------------------------------------------

@router.get("/", response_model=List[IncidentListItem])
def list_incidents(
    severity: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    resolved: Optional[bool] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    pg: Pagination = Depends(),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_management),
    db: Session = Depends(get_db),
):
    """Return all incidents with optional filters. Management/dispatch/admin only."""
    q = db.query(Incident).filter(Incident.company_id == caller.company_id)
    if severity:
        q = q.filter(Incident.severity == severity)
    if category:
        q = q.filter(Incident.category == category)
    if resolved is not None:
        q = q.filter(Incident.resolved == resolved)
    if date_from:
        q = q.filter(Incident.date >= date_from)
    if date_to:
        q = q.filter(Incident.date <= date_to)

    incidents = pg.apply(q.order_by(Incident.created_at.desc())).all()

    # Collect all referenced IDs then fetch in two bulk queries
    emp_ids  = {i.reporter_id for i in incidents} | {i.driver_id for i in incidents if i.driver_id}
    truck_ids = {i.truck_id for i in incidents if i.truck_id}

    emp_map   = {e.id: e for e in db.query(Employee).filter(Employee.id.in_(emp_ids)).all()}
    truck_map = {t.id: t for t in db.query(Truck).filter(Truck.id.in_(truck_ids)).all()}

    result = []
    for inc in incidents:
        reporter = emp_map.get(inc.reporter_id)
        driver   = emp_map.get(inc.driver_id) if inc.driver_id else None
        truck    = truck_map.get(inc.truck_id) if inc.truck_id else None
        result.append(IncidentListItem(
            id=inc.id,
            reporter_id=inc.reporter_id,
            reporter_name=reporter.name if reporter else None,
            truck_id=inc.truck_id,
            truck_name=truck.name if truck else None,
            driver_id=inc.driver_id,
            driver_name=driver.name if driver else None,
            date=inc.date,
            category=inc.category,
            severity=inc.severity,
            description=inc.description,
            resolved=inc.resolved,
            resolved_at=inc.resolved_at,
            created_at=inc.created_at,
        ))
    return result


@router.get("/unresolved-urgent", response_model=List[IncidentListItem])
def get_unresolved_urgent(
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_management),
    db: Session = Depends(get_db),
):
    """Return unresolved warning + critical incidents, newest first."""
    incidents = (
        db.query(Incident)
        .filter(
            Incident.company_id == caller.company_id,
            Incident.resolved == False,
            Incident.severity.in_(["warning", "critical"]),
        )
        .order_by(Incident.created_at.desc())
        .limit(10)
        .all()
    )

    emp_ids   = {i.reporter_id for i in incidents} | {i.driver_id for i in incidents if i.driver_id}
    truck_ids = {i.truck_id for i in incidents if i.truck_id}
    emp_map   = {e.id: e for e in db.query(Employee).filter(Employee.id.in_(emp_ids)).all()}
    truck_map = {t.id: t for t in db.query(Truck).filter(Truck.id.in_(truck_ids)).all()}

    result = []
    for inc in incidents:
        reporter = emp_map.get(inc.reporter_id)
        driver   = emp_map.get(inc.driver_id) if inc.driver_id else None
        truck    = truck_map.get(inc.truck_id) if inc.truck_id else None
        result.append(IncidentListItem(
            id=inc.id,
            reporter_id=inc.reporter_id,
            reporter_name=reporter.name if reporter else None,
            truck_id=inc.truck_id,
            truck_name=truck.name if truck else None,
            driver_id=inc.driver_id,
            driver_name=driver.name if driver else None,
            date=inc.date,
            category=inc.category,
            severity=inc.severity,
            description=inc.description,
            resolved=inc.resolved,
            resolved_at=inc.resolved_at,
            created_at=inc.created_at,
        ))
    return result


# ---------------------------------------------------------------------------
# Resolve
# ---------------------------------------------------------------------------

@router.patch("/{incident_id}/resolve", response_model=IncidentResponse)
def resolve_incident(
    incident_id: UUID,
    resolver: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_management),
    db: Session = Depends(get_db),
):
    """Mark an incident as resolved. Records who resolved it and when."""
    incident = db.query(Incident).filter(
        Incident.id == incident_id,
        Incident.company_id == resolver.company_id,
    ).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found.")
    if incident.resolved:
        raise HTTPException(status_code=400, detail="Incident is already resolved.")

    incident.resolved = True
    incident.resolved_by = resolver.id
    incident.resolved_at = datetime.now(timezone.utc)

    # Notify reporter
    db.add(Notification(
        company_id=resolver.company_id,
        employee_id=incident.reporter_id,
        type="incident_resolved",
        message=f"Your {incident.category.replace('_', ' ')} incident report from {incident.date.strftime('%a, %b %d')} has been reviewed and marked resolved.",
    ))
    write_audit(
        db,
        actor_id=str(resolver.id),
        company_id=str(resolver.company_id),
        action_type="incident.resolved",
        target_table="incidents",
        target_id=str(incident.id),
        before={"resolved": False},
        after={"resolved": True, "resolved_by": str(resolver.id)},
    )

    db.commit()
    db.refresh(incident)
    return incident


# ---------------------------------------------------------------------------
# Incident Trend Summary — management reporting
# ---------------------------------------------------------------------------

@router.get("/summary")
def get_incident_summary(
    days: int = Query(7, ge=1, le=90),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_management),
    db: Session = Depends(get_db),
):
    """Return incident counts grouped by severity and category over the last N days."""
    since = company_today(db, caller.company_id) - timedelta(days=days - 1)

    incidents = (
        db.query(Incident)
        .filter(Incident.company_id == caller.company_id, Incident.date >= since)
        .all()
    )

    by_severity = {"info": 0, "warning": 0, "critical": 0}
    by_category: dict = {}
    unresolved = 0

    for inc in incidents:
        if inc.severity in by_severity:
            by_severity[inc.severity] += 1
        cat = inc.category
        by_category[cat] = by_category.get(cat, 0) + 1
        if not inc.resolved:
            unresolved += 1

    return {
        "days": days,
        "since": since.isoformat(),
        "total": len(incidents),
        "unresolved": unresolved,
        "by_severity": by_severity,
        "by_category": [
            {"category": k, "label": k.replace("_", " ").title(), "count": v}
            for k, v in sorted(by_category.items(), key=lambda x: x[1], reverse=True)
        ],
    }

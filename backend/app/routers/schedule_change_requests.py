from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.database import get_db
from app.api.deps import RoleChecker, get_caller_employee, get_current_user
from app.models.schedule_change_request import ScheduleChangeRequest
from app.models.employee_off_day import EmployeeOffDay
from app.models.employee import Employee
from app.models.notification import Notification
from app.services.audit import write_audit

router = APIRouter(prefix="/schedule-change-requests", tags=["schedule-change-requests"])

VALID_DAYS = {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"}
VALID_TYPES = {"add_day", "drop_day", "full_rework"}

# Field staff submit; management/admin review. Dispatch is excluded — schedule
# changes are a field-staff concern; dispatch operates on the published schedule.
allow_submitter = RoleChecker(["driver", "walker", "trainer", "trainee"])
allow_reviewer  = RoleChecker(["management", "admin"])
allow_any_auth  = RoleChecker(["driver", "walker", "trainer", "trainee", "management", "admin"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ScheduleChangeRequestCreate(BaseModel):
    employee_id: UUID
    request_type: str
    days_to_add: List[str] = []
    days_to_drop: List[str] = []
    proposed_schedule: Optional[List[str]] = None
    reason: Optional[str] = Field(None, max_length=500)

    @field_validator("request_type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        if v not in VALID_TYPES:
            raise ValueError(f"request_type must be one of: {', '.join(sorted(VALID_TYPES))}")
        return v

    @field_validator("days_to_add", "days_to_drop", "proposed_schedule", mode="before")
    @classmethod
    def validate_days(cls, v):
        if v is None:
            return v
        for day in v:
            if day not in VALID_DAYS:
                raise ValueError(f"'{day}' is not a valid day of the week.")
        return v


class ScheduleChangeRequestResponse(BaseModel):
    id: UUID
    employee_id: UUID
    request_type: str
    days_to_add: List[str]
    days_to_drop: List[str]
    proposed_schedule: Optional[List[str]]
    reason: Optional[str]
    status: str
    reviewed_by: Optional[UUID]
    created_at: datetime
    resolved_at: Optional[datetime]

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Submit
# ---------------------------------------------------------------------------

@router.post("/", response_model=ScheduleChangeRequestResponse, status_code=status.HTTP_201_CREATED)
def submit_schedule_change_request(
    payload: ScheduleChangeRequestCreate,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
):
    """Submit a schedule change request. Employee can only submit for themselves."""
    if payload.employee_id != caller.id:
        raise HTTPException(status_code=403, detail="You can only submit schedule changes for yourself.")

    # Validate type-specific fields
    if payload.request_type == "add_day" and not payload.days_to_add:
        raise HTTPException(status_code=400, detail="add_day requests must include at least one day in days_to_add.")

    if payload.request_type == "drop_day" and not payload.days_to_drop:
        raise HTTPException(status_code=400, detail="drop_day requests must include at least one day in days_to_drop.")

    if payload.request_type == "full_rework":
        if not payload.proposed_schedule:
            raise HTTPException(status_code=400, detail="full_rework requests must include a proposed_schedule.")
        if len(payload.proposed_schedule) < 1:
            raise HTTPException(status_code=400, detail="proposed_schedule must include at least one working day.")

    # Reject if there's already a pending request for this employee
    existing_pending = db.query(ScheduleChangeRequest).filter(
        ScheduleChangeRequest.employee_id == payload.employee_id,
        ScheduleChangeRequest.status == "pending",
    ).first()
    if existing_pending:
        raise HTTPException(
            status_code=409,
            detail="You already have a pending schedule change request. Cancel it before submitting a new one.",
        )

    req = ScheduleChangeRequest(
        employee_id=payload.employee_id,
        request_type=payload.request_type,
        days_to_add=payload.days_to_add,
        days_to_drop=payload.days_to_drop,
        proposed_schedule=payload.proposed_schedule,
        reason=payload.reason,
    )
    db.add(req)
    db.flush()

    # Notify management/admin reviewers
    reviewers = db.query(Employee).filter(
        Employee.role.in_(["management", "admin"]),
        Employee.is_active == True,
    ).all()

    type_label = {
        "add_day": "add working days",
        "drop_day": "drop working days",
        "full_rework": "rework their full schedule",
    }.get(payload.request_type, payload.request_type)

    for reviewer in reviewers:
        db.add(Notification(
            employee_id=reviewer.id,
            type="schedule_change_request",
            message=f"{caller.name} has submitted a request to {type_label}."
            + (f" Reason: {payload.reason}" if payload.reason else ""),
        ))

    db.commit()
    db.refresh(req)
    return req


# ---------------------------------------------------------------------------
# Read own
# ---------------------------------------------------------------------------

@router.get("/employee/{employee_id}", response_model=List[ScheduleChangeRequestResponse])
def get_my_schedule_change_requests(
    employee_id: UUID,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
):
    """Return all schedule change requests for an employee.

    Employees can only read their own; management/admin can read any.
    """
    mgmt_roles = {"management", "admin"}
    if caller.role not in mgmt_roles and caller.id != employee_id:
        raise HTTPException(status_code=403, detail="You can only view your own schedule change requests.")

    return (
        db.query(ScheduleChangeRequest)
        .filter(ScheduleChangeRequest.employee_id == employee_id)
        .order_by(ScheduleChangeRequest.created_at.desc())
        .all()
    )


# ---------------------------------------------------------------------------
# Read all (management/admin)
# ---------------------------------------------------------------------------

@router.get("/", response_model=List[dict])
def get_all_schedule_change_requests(
    db: Session = Depends(get_db),
    _: dict = Depends(allow_reviewer),
    filter_status: Optional[str] = Query(None, alias="status", description="Filter by status: pending, approved, rejected. Omit for all."),
):
    """Return schedule change requests with employee details. Management/admin only.

    Use ?status=pending (default view), ?status=approved, ?status=rejected, or omit for all.
    """
    q = db.query(ScheduleChangeRequest)
    if filter_status is not None:
        q = q.filter(ScheduleChangeRequest.status == filter_status)
    requests = q.order_by(ScheduleChangeRequest.created_at.asc()).all()

    result = []
    for req in requests:
        emp = db.query(Employee).filter(Employee.id == req.employee_id).first()
        result.append({
            "id": str(req.id),
            "employee": {"id": str(emp.id), "name": emp.name, "role": emp.role} if emp else None,
            "request_type": req.request_type,
            "days_to_add": req.days_to_add,
            "days_to_drop": req.days_to_drop,
            "proposed_schedule": req.proposed_schedule,
            "reason": req.reason,
            "status": req.status,
            "created_at": req.created_at.isoformat(),
        })
    return result


# ---------------------------------------------------------------------------
# Approve — auto-applies changes to employee_off_days
# ---------------------------------------------------------------------------

@router.patch("/{request_id}/approve", response_model=ScheduleChangeRequestResponse)
def approve_schedule_change_request(
    request_id: UUID,
    db: Session = Depends(get_db),
    current_user: dict = Depends(allow_reviewer),
    reviewer: Employee = Depends(get_caller_employee),
):
    """Approve and auto-apply a schedule change request.

    Applies changes directly to employee_off_days:
    - add_day: removes the day from employee_off_days (making them eligible again)
    - drop_day: inserts new employee_off_days rows for each dropped day
    - full_rework: clears all existing off days, inserts new ones for any day
                   NOT in proposed_schedule
    """
    req = db.query(ScheduleChangeRequest).filter(
        ScheduleChangeRequest.id == request_id,
        ScheduleChangeRequest.status == "pending",
    ).first()
    if not req:
        raise HTTPException(status_code=404, detail="Pending schedule change request not found.")

    # --- Apply the schedule changes ---

    if req.request_type == "add_day":
        # Remove off-day entries for days being added back
        for day in req.days_to_add:
            db.query(EmployeeOffDay).filter(
                EmployeeOffDay.employee_id == req.employee_id,
                EmployeeOffDay.day_of_week == day,
            ).delete()

    elif req.request_type == "drop_day":
        # Add new off-day entries, skip days already in the table
        existing_off_days = {
            od.day_of_week for od in
            db.query(EmployeeOffDay).filter(
                EmployeeOffDay.employee_id == req.employee_id
            ).all()
        }
        for day in req.days_to_drop:
            if day not in existing_off_days:
                db.add(EmployeeOffDay(
                    employee_id=req.employee_id,
                    day_of_week=day,
                    status="approved",
                ))

    elif req.request_type == "full_rework":
        # Clear all existing off days for this employee
        db.query(EmployeeOffDay).filter(
            EmployeeOffDay.employee_id == req.employee_id
        ).delete()

        # Any day NOT in the proposed working schedule becomes an off day
        working_days = set(req.proposed_schedule or [])
        for day in VALID_DAYS:
            if day not in working_days:
                db.add(EmployeeOffDay(
                    employee_id=req.employee_id,
                    day_of_week=day,
                    status="approved",
                ))

    # Mark request resolved
    req.status = "approved"
    req.resolved_at = datetime.now(timezone.utc)
    req.reviewed_by = reviewer.id

    # Notify employee
    type_label = {
        "add_day": "add working days",
        "drop_day": "drop working days",
        "full_rework": "rework your full schedule",
    }.get(req.request_type, req.request_type)

    db.add(Notification(
        employee_id=req.employee_id,
        type="schedule_change_approved",
        message=f"Your request to {type_label} has been approved and your schedule has been updated.",
    ))
    write_audit(
        db,
        actor_id=current_user.get("id"),
        action_type="schedule_change.approved",
        target_table="schedule_change_requests",
        target_id=str(req.id),
        before={"status": "pending", "request_type": req.request_type},
        after={"status": "approved", "reviewed_by": str(reviewer.id)},
    )

    db.commit()
    db.refresh(req)
    return req


# ---------------------------------------------------------------------------
# Reject
# ---------------------------------------------------------------------------

@router.patch("/{request_id}/reject", response_model=ScheduleChangeRequestResponse)
def reject_schedule_change_request(
    request_id: UUID,
    db: Session = Depends(get_db),
    current_user: dict = Depends(allow_reviewer),
    reviewer: Employee = Depends(get_caller_employee),
):
    """Reject a pending schedule change request. No schedule changes are applied."""
    req = db.query(ScheduleChangeRequest).filter(
        ScheduleChangeRequest.id == request_id,
        ScheduleChangeRequest.status == "pending",
    ).first()
    if not req:
        raise HTTPException(status_code=404, detail="Pending schedule change request not found.")

    req.status = "rejected"
    req.resolved_at = datetime.now(timezone.utc)
    req.reviewed_by = reviewer.id

    db.add(Notification(
        employee_id=req.employee_id,
        type="schedule_change_rejected",
        message="Your schedule change request was reviewed and not approved.",
    ))
    write_audit(
        db,
        actor_id=current_user.get("id"),
        action_type="schedule_change.rejected",
        target_table="schedule_change_requests",
        target_id=str(req.id),
        before={"status": "pending", "request_type": req.request_type},
        after={"status": "rejected", "reviewed_by": str(reviewer.id)},
    )

    db.commit()
    db.refresh(req)
    return req


# ---------------------------------------------------------------------------
# Cancel own pending
# ---------------------------------------------------------------------------

@router.delete("/{request_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel_schedule_change_request(
    request_id: UUID,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
):
    """Cancel a pending schedule change request. Employee can only cancel their own."""
    req = db.query(ScheduleChangeRequest).filter(
        ScheduleChangeRequest.id == request_id,
        ScheduleChangeRequest.status == "pending",
    ).first()
    if not req:
        raise HTTPException(status_code=404, detail="Pending schedule change request not found.")

    if caller.id != req.employee_id:
        raise HTTPException(status_code=403, detail="You can only cancel your own requests.")

    db.delete(req)
    db.commit()

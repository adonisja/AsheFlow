from datetime import date, datetime, timezone
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.api.deps import RoleChecker, get_caller_employee
from app.models.assignment_change_request import AssignmentChangeRequest
from app.models.assignment_member import AssignmentMember
from app.models.truck_assignment import TruckAssignment
from app.models.employee import Employee
from app.models.notification import Notification
from app.schemas.assignment_change_request import AssignmentChangeRequestCreate, AssignmentChangeRequestResponse
from app.services.audit import write_audit

router = APIRouter(prefix="/assignment-change-requests", tags=["assignment-change-requests"])

allow_submitter  = RoleChecker(["walker", "trainer"])
allow_viewer     = RoleChecker(["driver", "walker", "trainer", "dispatch", "management", "admin"])
allow_dispatcher = RoleChecker(["dispatch", "admin"])


@router.post("/", status_code=status.HTTP_201_CREATED, response_model=AssignmentChangeRequestResponse)
def submit_change_request(
    payload: AssignmentChangeRequestCreate,
    db: Session = Depends(get_db),
    _: dict = Depends(allow_submitter),
    caller: Employee = Depends(get_caller_employee),
):
    """Walker or trainer submits a request to be reassigned to a different truck.

    Enforces:
    - requested_date must be today (same-day only)
    - caller must have an active TruckAssignment for today
    - only one pending request per employee per date
    A notification is sent to all active dispatch employees.
    """
    if payload.employee_id != caller.id:
        raise HTTPException(status_code=403, detail="You can only submit reassignment requests for yourself.")

    employee = db.query(Employee).filter(
        Employee.id == payload.employee_id,
        Employee.company_id == caller.company_id,
        Employee.role.in_(["walker", "trainer"]),
        Employee.is_active == True,
    ).first()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found or not eligible to submit reassignment requests.")

    today = date.today()
    if payload.requested_date != today:
        raise HTTPException(status_code=400, detail="Reassignment requests can only be submitted for today.")

    active_assignment = (
        db.query(AssignmentMember)
        .join(TruckAssignment, AssignmentMember.assignment_id == TruckAssignment.id)
        .filter(
            AssignmentMember.employee_id == payload.employee_id,
            TruckAssignment.date == today,
            TruckAssignment.company_id == caller.company_id,
        )
        .first()
    )
    if not active_assignment:
        raise HTTPException(
            status_code=400,
            detail="You are not assigned to a truck today. Reassignment requests require an active assignment.",
        )

    existing = db.query(AssignmentChangeRequest).filter(
        AssignmentChangeRequest.employee_id == payload.employee_id,
        AssignmentChangeRequest.company_id == caller.company_id,
        AssignmentChangeRequest.requested_date == payload.requested_date,
        AssignmentChangeRequest.status == "pending",
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A pending reassignment request already exists for this date.",
        )

    new_req = AssignmentChangeRequest(
        employee_id=payload.employee_id,
        company_id=caller.company_id,
        requested_date=payload.requested_date,
        reason=payload.reason,
    )
    db.add(new_req)
    db.flush()

    dispatch_employees = db.query(Employee).filter(
        Employee.company_id == caller.company_id,
        Employee.role == "dispatch",
        Employee.is_active == True,
    ).all()

    for emp in dispatch_employees:
        db.add(Notification(
            company_id=caller.company_id,
            employee_id=emp.id,
            type="assignment_change_request",
            message=(
                f"{employee.name} has requested a truck reassignment for "
                f"{payload.requested_date.strftime('%A, %b %d')}."
                + (f" Reason: {payload.reason}" if payload.reason else "")
            ),
        ))

    db.commit()
    db.refresh(new_req)
    return new_req


@router.get("/pending", response_model=List[dict])
def get_pending_requests(
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_dispatcher),
):
    """Return all pending assignment change requests with employee details.

    Used by the dispatcher dashboard Pending Approvals card.
    Sorted by requested_date ascending (most urgent first).
    """
    pending = (
        db.query(AssignmentChangeRequest)
        .join(Employee, AssignmentChangeRequest.employee_id == Employee.id)
        .filter(
            AssignmentChangeRequest.status == "pending",
            Employee.company_id == caller.company_id,
        )
        .order_by(AssignmentChangeRequest.requested_date.asc(), AssignmentChangeRequest.created_at.asc())
        .all()
    )

    result = []
    for req in pending:
        employee = db.query(Employee).filter(Employee.id == req.employee_id, Employee.company_id == caller.company_id).first()
        result.append({
            "id": str(req.id),
            "employee": {
                "id": str(employee.id),
                "name": employee.name,
                "role": employee.role,
            } if employee else None,
            "requested_date": req.requested_date.isoformat(),
            "reason": req.reason,
            "created_at": req.created_at.isoformat(),
        })
    return result


@router.get("/employee/{employee_id}", response_model=List[AssignmentChangeRequestResponse])
def get_employee_requests(
    employee_id: UUID,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_viewer),
):
    """Return all assignment change requests for a specific employee.

    Field staff can only view their own; dispatch/management/admin can view any.
    """
    privileged_roles = {"dispatch", "management", "admin"}
    if caller.role not in privileged_roles and caller.id != employee_id:
        raise HTTPException(status_code=403, detail="You can only view your own requests.")

    return (
        db.query(AssignmentChangeRequest)
        .join(Employee, AssignmentChangeRequest.employee_id == Employee.id)
        .filter(
            AssignmentChangeRequest.employee_id == employee_id,
            Employee.company_id == caller.company_id,
        )
        .order_by(AssignmentChangeRequest.created_at.desc())
        .all()
    )


@router.patch("/{request_id}/approve", response_model=AssignmentChangeRequestResponse)
def approve_change_request(
    request_id: UUID,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_dispatcher),
):
    """Approve a pending reassignment request.

    Marks the request approved and records who reviewed it.
    The actual truck swap must be performed separately via PATCH /dispatch/assign.
    A notification is sent to the requesting employee.
    """
    req = (
        db.query(AssignmentChangeRequest)
        .join(Employee, AssignmentChangeRequest.employee_id == Employee.id)
        .filter(
            AssignmentChangeRequest.id == request_id,
            AssignmentChangeRequest.status == "pending",
            Employee.company_id == caller.company_id,
        )
        .first()
    )
    if not req:
        raise HTTPException(status_code=404, detail="Pending request not found.")

    req.status = "approved"
    req.resolved_at = datetime.now(timezone.utc)
    req.reviewed_by = caller.id

    db.add(Notification(
        company_id=caller.company_id,
        employee_id=req.employee_id,
        type="assignment_change_approved",
        message=f"Your truck reassignment request for {req.requested_date.strftime('%A, %b %d')} has been approved. Dispatch will update your assignment shortly.",
    ))
    write_audit(
        db,
        actor_id=str(caller.id),
        company_id=str(caller.company_id),
        action_type="assignment_change.approved",
        target_table="assignment_change_requests",
        target_id=str(req.id),
        before={"status": "pending"},
        after={"status": "approved", "reviewed_by": str(caller.id)},
    )

    db.commit()
    db.refresh(req)
    return req


@router.patch("/{request_id}/reject", response_model=AssignmentChangeRequestResponse)
def reject_change_request(
    request_id: UUID,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_dispatcher),
):
    """Reject a pending reassignment request. Notifies the employee."""
    req = (
        db.query(AssignmentChangeRequest)
        .join(Employee, AssignmentChangeRequest.employee_id == Employee.id)
        .filter(
            AssignmentChangeRequest.id == request_id,
            AssignmentChangeRequest.status == "pending",
            Employee.company_id == caller.company_id,
        )
        .first()
    )
    if not req:
        raise HTTPException(status_code=404, detail="Pending request not found.")

    req.status = "rejected"
    req.resolved_at = datetime.now(timezone.utc)
    req.reviewed_by = caller.id

    db.add(Notification(
        company_id=caller.company_id,
        employee_id=req.employee_id,
        type="assignment_change_rejected",
        message=f"Your truck reassignment request for {req.requested_date.strftime('%A, %b %d')} was not approved.",
    ))
    write_audit(
        db,
        actor_id=str(caller.id),
        company_id=str(caller.company_id),
        action_type="assignment_change.rejected",
        target_table="assignment_change_requests",
        target_id=str(req.id),
        before={"status": "pending"},
        after={"status": "rejected", "reviewed_by": str(caller.id)},
    )

    db.commit()
    db.refresh(req)
    return req


@router.delete("/{request_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel_change_request(
    request_id: UUID,
    db: Session = Depends(get_db),
    _: dict = Depends(allow_submitter),
    caller: Employee = Depends(get_caller_employee),
):
    """Cancel a pending reassignment request (employee self-cancel)."""
    req = (
        db.query(AssignmentChangeRequest)
        .join(Employee, AssignmentChangeRequest.employee_id == Employee.id)
        .filter(
            AssignmentChangeRequest.id == request_id,
            AssignmentChangeRequest.status == "pending",
            Employee.company_id == caller.company_id,
        )
        .first()
    )
    if not req:
        raise HTTPException(status_code=404, detail="Pending request not found.")

    if caller.id != req.employee_id:
        raise HTTPException(status_code=403, detail="You can only cancel your own requests.")

    db.delete(req)
    db.commit()


@router.delete("/pending/{request_id}", status_code=status.HTTP_204_NO_CONTENT)
def purge_pending_request(
    request_id: UUID,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_dispatcher),
):
    """Dispatcher/admin hard-delete a stuck pending request.

    Intended for cleanup of orphaned or erroneous pending entries that the
    submitting employee is unable to cancel themselves.
    """
    req = (
        db.query(AssignmentChangeRequest)
        .join(Employee, AssignmentChangeRequest.employee_id == Employee.id)
        .filter(
            AssignmentChangeRequest.id == request_id,
            AssignmentChangeRequest.status == "pending",
            Employee.company_id == caller.company_id,
        )
        .first()
    )
    if not req:
        raise HTTPException(status_code=404, detail="Pending request not found.")

    db.delete(req)
    db.commit()

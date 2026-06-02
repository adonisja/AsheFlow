from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.api.deps import RoleChecker, get_caller_employee, Pagination
from app.models.employee import Employee
from app.models.time_off_request import TimeOffRequest
from app.models.employee_off_day import EmployeeOffDay
from app.models.notification import Notification
from app.schemas.time_off_request import TimeOffRequestCreate, TimeOffRequestResponse
from app.services.audit import write_audit

router = APIRouter(prefix="/time-off-requests", tags=["time-off-requests"])

allow_field_staff = RoleChecker(["driver", "walker", "trainer", "trainee"])
allow_mgmt        = RoleChecker(["management", "admin", "dispatch"])

@router.get("/", response_model=list[TimeOffRequestResponse])
def get_all_time_off_requests(
    pg: Pagination = Depends(),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_mgmt),
    db: Session = Depends(get_db),
):
    return pg.apply(
        db.query(TimeOffRequest)
        .join(Employee, TimeOffRequest.employee_id == Employee.id)
        .filter(Employee.company_id == caller.company_id)
    ).all()

@router.get("/{employee_id}", response_model=list[TimeOffRequestResponse])
def get_time_off_requests(
    employee_id: UUID,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
):
    # Field staff can only see their own; management/admin/dispatch can see any
    mgmt_roles = {"management", "admin", "dispatch"}
    if caller.role not in mgmt_roles and caller.id != employee_id:
        raise HTTPException(status_code=403, detail="You can only view your own time-off requests.")
    return db.query(TimeOffRequest).filter(
        TimeOffRequest.employee_id == employee_id,
        TimeOffRequest.company_id == caller.company_id,
    ).all()

@router.post("/", response_model=TimeOffRequestResponse, status_code=status.HTTP_201_CREATED)
def create_time_off_request(
    request: TimeOffRequestCreate,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
):
    mgmt_roles = {"management", "admin", "dispatch"}
    if caller.role not in mgmt_roles and caller.id != request.employee_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only submit time-off requests for yourself.")
    day_of_week = request.date.strftime("%A")
    
    recurring_off_day = db.query(EmployeeOffDay).filter(
        EmployeeOffDay.employee_id == request.employee_id,
        EmployeeOffDay.company_id == caller.company_id,
        EmployeeOffDay.day_of_week == day_of_week,
        EmployeeOffDay.status == "approved"
    ).first()

    if recurring_off_day:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail=f"Cannot request time off on {day_of_week}s; it is already an approved recurring off-day."
        )

    existing_request = db.query(TimeOffRequest).filter(
        TimeOffRequest.employee_id == request.employee_id,
        TimeOffRequest.company_id == caller.company_id,
        TimeOffRequest.date == request.date
    ).first()

    if existing_request:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="A time-off request already exists for this date."
        )

    db_request = TimeOffRequest(
        employee_id=request.employee_id,
        company_id=caller.company_id,
        date=request.date,
        status="pending"
    )
    db.add(db_request)
    db.commit()
    db.refresh(db_request)
    return db_request

@router.delete("/{request_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_time_off_request(
    request_id: UUID,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
):
    db_request = db.query(TimeOffRequest).filter(
        TimeOffRequest.id == request_id,
        TimeOffRequest.company_id == caller.company_id,
    ).first()
    if not db_request:
        raise HTTPException(status_code=404, detail="Time-off request not found")

    mgmt_roles = {"management", "admin", "dispatch"}
    if caller.role not in mgmt_roles and caller.id != db_request.employee_id:
        raise HTTPException(status_code=403, detail="You can only cancel your own time-off requests.")

    db.delete(db_request)
    db.commit()

@router.patch("/{request_id}/approve", response_model=TimeOffRequestResponse)
def approve_time_off_request(
    request_id: UUID,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_mgmt),
    db: Session = Depends(get_db),
):
    db_request = (
        db.query(TimeOffRequest)
        .join(Employee, TimeOffRequest.employee_id == Employee.id)
        .filter(TimeOffRequest.id == request_id, Employee.company_id == caller.company_id)
        .first()
    )
    if not db_request:
        raise HTTPException(status_code=404, detail="Time-off request not found")

    db_request.status = "approved"
    db.add(Notification(
        company_id=caller.company_id,
        employee_id=db_request.employee_id,
        type="pto_approved",
        message=f"Your PTO request for {db_request.date} has been approved.",
    ))
    write_audit(
        db,
        actor_id=str(caller.id),
        company_id=str(caller.company_id),
        action_type="pto.approved",
        target_table="time_off_requests",
        target_id=str(db_request.id),
        before={"status": "pending"},
        after={"status": "approved"},
    )
    db.commit()
    db.refresh(db_request)
    return db_request


@router.patch("/{request_id}/reject", response_model=TimeOffRequestResponse)
def reject_time_off_request(
    request_id: UUID,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_mgmt),
    db: Session = Depends(get_db),
):
    db_request = (
        db.query(TimeOffRequest)
        .join(Employee, TimeOffRequest.employee_id == Employee.id)
        .filter(TimeOffRequest.id == request_id, Employee.company_id == caller.company_id)
        .first()
    )
    if not db_request:
        raise HTTPException(status_code=404, detail="Time-off request not found")

    db_request.status = "rejected"
    db.add(Notification(
        company_id=caller.company_id,
        employee_id=db_request.employee_id,
        type="pto_rejected",
        message=f"Your PTO request for {db_request.date} was not approved.",
    ))
    write_audit(
        db,
        actor_id=str(caller.id),
        company_id=str(caller.company_id),
        action_type="pto.rejected",
        target_table="time_off_requests",
        target_id=str(db_request.id),
        before={"status": "pending"},
        after={"status": "rejected"},
    )
    db.commit()
    db.refresh(db_request)
    return db_request

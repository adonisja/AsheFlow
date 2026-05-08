from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.api.deps import RoleChecker, get_caller_employee
from app.models.employee import Employee
from app.models.employee_off_day import EmployeeOffDay
from app.models.notification import Notification
from app.schemas.employee_off_day import EmployeeOffDayCreate, EmployeeOffDayResponse

router = APIRouter(prefix="/employee-off-days", tags=["employee-off-days"])
allow_mgmt       = RoleChecker(["management", "admin", "dispatch"])
allow_field_staff = RoleChecker(["driver", "walker", "trainer", "trainee"])
allow_any_auth   = RoleChecker(["driver", "walker", "trainer", "trainee", "dispatch", "management", "admin"])


@router.post("/", response_model=EmployeeOffDayResponse, status_code=status.HTTP_201_CREATED)
def create_employee_off_day(
    employee_off_day: EmployeeOffDayCreate,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
):
    """Add a recurring off day for an employee.

    Field staff can only create off-days for themselves. Management/admin can
    create for any employee.
    """
    mgmt_roles = {"management", "admin"}
    if caller.role not in mgmt_roles and caller.id != employee_off_day.employee_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only add off-days for yourself.")

    db_employee = db.query(Employee).filter(
        Employee.id == employee_off_day.employee_id,
        Employee.company_id == caller.company_id,
    ).first()
    if not db_employee:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")

    db_off_day = EmployeeOffDay(**employee_off_day.model_dump())
    db.add(db_off_day)
    db.commit()
    db.refresh(db_off_day)
    return db_off_day

@router.get("/", response_model=list[EmployeeOffDayResponse])
def get_all_employee_off_days(
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_mgmt),
    db: Session = Depends(get_db),
):
    return (
        db.query(EmployeeOffDay)
        .join(Employee, EmployeeOffDay.employee_id == Employee.id)
        .filter(Employee.company_id == caller.company_id)
        .all()
    )

@router.get("/{employee_id}", response_model=list[EmployeeOffDayResponse])
def get_employee_off_days(
    employee_id: UUID,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
):
    """Return all off days for a specific employee.

    Field staff can only read their own off-days. Management/admin can read any.
    """
    mgmt_roles = {"management", "admin", "dispatch"}
    if caller.role not in mgmt_roles and caller.id != employee_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only view your own off-days.")

    return (
        db.query(EmployeeOffDay)
        .join(Employee, EmployeeOffDay.employee_id == Employee.id)
        .filter(EmployeeOffDay.employee_id == employee_id, Employee.company_id == caller.company_id)
        .all()
    )

@router.delete("/employee/{employee_id}/clear", status_code=status.HTTP_204_NO_CONTENT)
def delete_all_off_days(
    employee_id: UUID,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_mgmt),
    db: Session = Depends(get_db),
):
    employee = db.query(Employee).filter(
        Employee.id == employee_id,
        Employee.company_id == caller.company_id,
    ).first()
    if not employee:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")

    db.query(EmployeeOffDay).filter(EmployeeOffDay.employee_id == employee_id).delete()
    db.commit()

@router.delete("/{off_day_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_employee_off_day(
    off_day_id: UUID,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_mgmt),
    db: Session = Depends(get_db),
):
    """Delete a single employee off-day record by its ID. Management/admin only."""
    off_day = (
        db.query(EmployeeOffDay)
        .join(Employee, EmployeeOffDay.employee_id == Employee.id)
        .filter(EmployeeOffDay.id == off_day_id, Employee.company_id == caller.company_id)
        .first()
    )
    if not off_day:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Off day not found")

    db.delete(off_day)
    db.commit()

@router.patch("/{off_day_id}/approve", response_model=EmployeeOffDayResponse)
def approve_employee_off_day(
    off_day_id: UUID,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_mgmt),
    db: Session = Depends(get_db),
):
    off_day = (
        db.query(EmployeeOffDay)
        .join(Employee, EmployeeOffDay.employee_id == Employee.id)
        .filter(EmployeeOffDay.id == off_day_id, Employee.company_id == caller.company_id)
        .first()
    )
    if not off_day:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Off day not found")
    off_day.status = "approved"
    db.add(Notification(
        company_id=caller.company_id,
        employee_id=off_day.employee_id,
        type="offday_approved",
        message=f"Your request to have {off_day.day_of_week}s off has been approved.",
    ))
    db.commit()
    db.refresh(off_day)
    return off_day


@router.patch("/{off_day_id}/reject", response_model=EmployeeOffDayResponse)
def reject_employee_off_day(
    off_day_id: UUID,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_mgmt),
    db: Session = Depends(get_db),
):
    off_day = (
        db.query(EmployeeOffDay)
        .join(Employee, EmployeeOffDay.employee_id == Employee.id)
        .filter(EmployeeOffDay.id == off_day_id, Employee.company_id == caller.company_id)
        .first()
    )
    if not off_day:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Off day not found")
    off_day.status = "rejected"
    db.add(Notification(
        company_id=caller.company_id,
        employee_id=off_day.employee_id,
        type="offday_rejected",
        message=f"Your request to have {off_day.day_of_week}s off was not approved.",
    ))
    db.commit()
    db.refresh(off_day)
    return off_day


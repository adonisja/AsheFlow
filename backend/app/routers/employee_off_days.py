from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.api.deps import RoleChecker
from app.models.employee import Employee
from app.models.employee_off_day import EmployeeOffDay
from app.schemas.employee_off_day import EmployeeOffDayCreate, EmployeeOffDayResponse

router = APIRouter(prefix="/employee-off-days", tags=["employee-off-days"])
allow_mgmt = RoleChecker(["management", "admin"])


@router.post("/", response_model=EmployeeOffDayResponse, status_code=status.HTTP_201_CREATED)
def create_employee_off_day(employee_off_day: EmployeeOffDayCreate, db: Session = Depends(get_db)):
    """Add a recurring off day for an employee.

    Args:
        employee_off_day: Validated payload containing employee_id and day_of_week.
        db: Database session.

    Returns:
        The newly created EmployeeOffDay record.

    Raises:
        HTTPException(404): If the referenced employee does not exist.
    """
    db_employee = db.query(Employee).filter(Employee.id == employee_off_day.employee_id).first()
    if not db_employee:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")

    db_off_day = EmployeeOffDay(**employee_off_day.model_dump())
    db.add(db_off_day)
    db.commit()
    db.refresh(db_off_day)
    return db_off_day

@router.get("/", response_model=list[EmployeeOffDayResponse])
def get_all_employee_off_days(db:Session = Depends(get_db)):
    """Return all employee off-day records.

    Args:
        db: Database session.

    Returns:
        List of all EmployeeOffDay records.
    """
    return db.query(EmployeeOffDay).all()

@router.get("/{employee_id}", response_model=list[EmployeeOffDayResponse])
def get_employee_off_days(employee_id: UUID, db: Session = Depends(get_db)):
    """Return all off days for a specific employee.

    Args:
        employee_id: UUID of the employee.
        db: Database session.

    Returns:
        List of EmployeeOffDay records for the given employee.
    """
    return db.query(EmployeeOffDay).filter(EmployeeOffDay.employee_id == employee_id).all()

@router.delete("/employee/{employee_id}/clear", status_code=status.HTTP_204_NO_CONTENT)
def delete_all_off_days(employee_id: UUID, db: Session = Depends(get_db)):
    """Delete all recurring off days for an employee.

    Args:
        employee_id: UUID of the employee whose off days to clear.
        db: Database session.

    Raises:
        HTTPException(404): If the referenced employee does not exist.
    """
    employee = db.query(Employee).filter(Employee.id == employee_id).first()

    if not employee:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")
    
    db.query(EmployeeOffDay).filter(EmployeeOffDay.employee_id == employee_id).delete()
    db.commit()

@router.delete("/{off_day_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_employee_off_day(off_day_id: UUID, db: Session = Depends(get_db)):
    """Delete a single employee off-day record by its ID.

    Args:
        off_day_id: UUID of the EmployeeOffDay record to remove.
        db: Database session.

    Raises:
        HTTPException(404): If no off-day record with the given ID exists.
    """
    off_day = db.query(EmployeeOffDay).filter(EmployeeOffDay.id == off_day_id).first()
    if not off_day:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Off day not found")

    db.delete(off_day)
    db.commit()

@router.patch("/{off_day_id}/approve", response_model=EmployeeOffDayResponse)
def approve_employee_off_day(off_day_id: UUID, db: Session = Depends(get_db), current_user: dict = Depends(allow_mgmt)):
    off_day = db.query(EmployeeOffDay).filter(EmployeeOffDay.id == off_day_id).first()
    if not off_day:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Off day not found")
    off_day.status = "approved"
    db.commit()
    db.refresh(off_day)
    return off_day

@router.patch("/{off_day_id}/reject", response_model=EmployeeOffDayResponse)
def reject_employee_off_day(off_day_id: UUID, db: Session = Depends(get_db), current_user: dict = Depends(allow_mgmt)):
    off_day = db.query(EmployeeOffDay).filter(EmployeeOffDay.id == off_day_id).first()
    if not off_day:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Off day not found")
    off_day.status = "rejected"
    db.commit()
    db.refresh(off_day)
    return off_day


from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import RoleChecker
from app.database import get_db
from app.models.employee import Employee
from app.schemas.employee import EmployeeCreate, EmployeeUpdate, EmployeeResponse

router = APIRouter(prefix="/employees", tags=["employees"])


@router.post("/", response_model=EmployeeResponse, status_code=status.HTTP_201_CREATED)
def create_employee(employee: EmployeeCreate, current_user: dict = Depends(RoleChecker(["management", "admin"])), db: Session = Depends(get_db)):
    """Create and persist a new employee record.

    Args:
        employee: Validated employee creation payload.
        db: Database session.

    Returns:
        The newly created Employee record.
    """
    db_employee = Employee(**employee.model_dump())
    db.add(db_employee)
    db.commit()
    db.refresh(db_employee)
    return db_employee


@router.get("/", response_model=list[EmployeeResponse])
def get_all_employees(current_user: dict = Depends(RoleChecker(["management", "admin", "dispatch", "driver", "walker", "trainer", "trainee"])), db: Session = Depends(get_db)):
    """Return all active employees.

    Args:
        db: Database session.

    Returns:
        List of active Employee records.
    """
    return db.query(Employee).filter(Employee.is_active == True).all()


@router.get("/{employee_id}", response_model=EmployeeResponse)
def get_employee(employee_id: UUID, current_user: dict = Depends(RoleChecker(["management", "admin", "dispatch", "driver", "walker", "trainer", "trainee"])), db: Session = Depends(get_db)):
    """Fetch a single employee by ID.

    Args:
        employee_id: UUID of the employee to retrieve.
        db: Database session.

    Returns:
        The matching Employee record.

    Raises:
        HTTPException(404): If no employee with the given ID exists.
    """
    employee = db.query(Employee).filter(Employee.id == employee_id).first()
    if not employee:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")
    return employee


@router.put("/{employee_id}", response_model=EmployeeResponse)
def update_employee(employee_id: UUID, employee: EmployeeUpdate, current_user: dict = Depends(RoleChecker(["management", "admin"])), db: Session = Depends(get_db)):
    """Update an existing employee's fields.

    Args:
        employee_id: UUID of the employee to update.
        employee: Partial update payload; only provided fields are applied.
        db: Database session.

    Returns:
        The updated Employee record.

    Raises:
        HTTPException(404): If no employee with the given ID exists.
    """
    db_employee = db.query(Employee).filter(Employee.id == employee_id).first()
    if not db_employee:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")

    for key, value in employee.model_dump(exclude_unset=True).items():
        setattr(db_employee, key, value)

    db.commit()
    db.refresh(db_employee)
    return db_employee


@router.put("/{employee_id}/deactivate", response_model=EmployeeResponse)
def deactivate_employee(employee_id: UUID, current_user: dict = Depends(RoleChecker(["management", "admin"])), db: Session = Depends(get_db)):
    """Set an employee's active status to False.

    Args:
        employee_id: UUID of the employee to deactivate.
        db: Database session.

    Returns:
        The updated Employee record with ``is_active`` set to False.

    Raises:
        HTTPException(404): If no employee with the given ID exists.
    """
    db_employee = (db.query(Employee)
                   .filter(Employee.id == employee_id)
                   .first()
                )
    if not db_employee:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")

    db_employee.is_active = False
    db.commit()
    db.refresh(db_employee)
    return db_employee


@router.delete("/{employee_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_employee(employee_id: UUID, current_user: dict = Depends(RoleChecker(["management", "admin"])), db: Session = Depends(get_db)):
    """Soft-delete an employee by setting ``is_active`` to False.

    Args:
        employee_id: UUID of the employee to delete.
        db: Database session.

    Raises:
        HTTPException(404): If no employee with the given ID exists.
    """
    db_employee = db.query(Employee).filter(Employee.id == employee_id).first()
    if not db_employee:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")

    db_employee.is_active = False
    db.commit()

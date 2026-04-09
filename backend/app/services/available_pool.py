from datetime import date

from sqlalchemy import and_, exists
from sqlalchemy.orm import Session
from app.models.employee import Employee
from app.models.employee_off_day import EmployeeOffDay

def get_available_pool(db: Session, target_date: date = None)->dict:
    """Return all active employees grouped by role who are not off on the target date.

    Args:
        db: Database session.
        target_date: Date to check availability for. Defaults to today.

    Returns:
        A dict with keys ``"drivers"``, ``"trainers"``, and ``"walkers"``, each
        containing a list of Employee ORM objects available on that date.
    """
    target_date = target_date or date.today()

    # 1. Define the existence check representing "Has an off day today"
    # Even though we define this as a separate python variable, SQLAlchemy
    # treats this as a sub-clause and compiles it into the main queries below.
    has_off_day_today = (
        db.query(EmployeeOffDay)
        .filter(
            EmployeeOffDay.employee_id == Employee.id,
            EmployeeOffDay.day_of_week == target_date.strftime("%A"),
            EmployeeOffDay.status == 'approved'
        )
        .exists()
    )

    # 2. Query ALL available employees in a single network round-trip
    available_employees = (
        db.query(Employee)
        .filter(
            Employee.role.in_(["driver", "trainer", "walker"]),
            Employee.is_active == True,
            ~has_off_day_today
        )
        .all()
    )

    available_pool = {
        "drivers": [],
        "trainers": [],
        "walkers": []
    }

    # 3. Group the results in Python memory
    for employee in available_employees:
        if employee.role == "driver":
            available_pool["drivers"].append(employee)
        elif employee.role == "trainer":
            available_pool["trainers"].append(employee)
        elif employee.role == "walker":
            available_pool["walkers"].append(employee)

    return available_pool


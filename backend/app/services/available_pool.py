from datetime import date
from uuid import UUID

from sqlalchemy import or_
from sqlalchemy.orm import Session
from app.models.employee import Employee
from app.models.employee_off_day import EmployeeOffDay
from app.models.time_off_request import TimeOffRequest


def get_available_pool(db: Session, target_date: date = None, company_id: UUID = None) -> dict:
    """Return active employees grouped by role who are available on target_date, scoped to company."""
    if company_id is None:
        raise ValueError("company_id is required for get_available_pool")
    target_date = target_date or date.today()

    has_off_day_today = (
        db.query(EmployeeOffDay)
        .filter(
            EmployeeOffDay.employee_id == Employee.id,
            EmployeeOffDay.day_of_week == target_date.strftime("%A"),
            EmployeeOffDay.status == "approved",
        )
        .exists()
    )

    has_pto_today = (
        db.query(TimeOffRequest)
        .filter(
            TimeOffRequest.employee_id == Employee.id,
            TimeOffRequest.date == target_date,
            TimeOffRequest.status == "approved",
        )
        .exists()
    )

    available_employees = (
        db.query(Employee)
        .filter(
            Employee.company_id == company_id,
            Employee.role.in_(["driver", "trainer", "trainee", "walker"]),
            Employee.is_active == True,
            ~or_(has_off_day_today, has_pto_today),
        )
        .all()
    )

    available_pool = {"drivers": [], "trainers": [], "trainees": [], "walkers": []}
    for employee in available_employees:
        if employee.role == "driver":
            available_pool["drivers"].append(employee)
        elif employee.role == "trainer":
            available_pool["trainers"].append(employee)
        elif employee.role == "trainee":
            available_pool["trainees"].append(employee)
        elif employee.role == "walker":
            available_pool["walkers"].append(employee)

    return available_pool


def get_unavailable_staff(db: Session, target_date: date = None, roles: list = None, company_id: UUID = None) -> list:
    """Return active employees excluded from the pool on target_date, with reason, scoped to company.

    The inverse of get_available_pool for a given set of roles. Used by dispatch
    to surface a call-in list when understaffed warnings fire.

    Trainees are always excluded — their assignment flow is managed through the
    training system, not manual dispatch phone calls.
    """
    if company_id is None:
        raise ValueError("company_id is required for get_unavailable_staff")
    target_date = target_date or date.today()
    day_name = target_date.strftime("%A")

    allowed_roles = [r for r in (roles or ["driver", "trainer", "walker"]) if r != "trainee"]

    employees = (
        db.query(Employee)
        .filter(
            Employee.company_id == company_id,
            Employee.role.in_(allowed_roles),
            Employee.is_active == True,
        )
        .all()
    )

    employee_ids = [e.id for e in employees]

    time_off_ids = {
        row.employee_id
        for row in db.query(TimeOffRequest).filter(
            TimeOffRequest.date == target_date,
            TimeOffRequest.status == "approved",
            TimeOffRequest.employee_id.in_(employee_ids),
        ).all()
    } if employee_ids else set()

    off_day_ids = {
        row.employee_id
        for row in db.query(EmployeeOffDay).filter(
            EmployeeOffDay.day_of_week == day_name,
            EmployeeOffDay.status == "approved",
            EmployeeOffDay.employee_id.in_(employee_ids),
        ).all()
    } if employee_ids else set()

    excluded_ids = time_off_ids | off_day_ids

    result = []
    for emp in employees:
        if emp.id not in excluded_ids:
            continue
        reason = "time_off_request" if emp.id in time_off_ids else "recurring_off_day"
        result.append({
            "id": str(emp.id),
            "name": emp.name,
            "role": emp.role,
            "discord_id": emp.discord_id,
            "phone_number": emp.phone_number,
            "reason": reason,
        })

    role_order = {"driver": 0, "trainer": 1, "walker": 2}
    result.sort(key=lambda e: (role_order.get(e["role"], 9), e["name"]))
    return result


def get_unavailable_drivers(db: Session, target_date: date = None, company_id: UUID = None) -> list:
    """Convenience wrapper — returns unavailable drivers only."""
    return get_unavailable_staff(db, target_date, roles=["driver"], company_id=company_id)

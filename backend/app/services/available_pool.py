from datetime import date

from sqlalchemy import and_, exists, or_
from sqlalchemy.orm import Session
from app.models.employee import Employee
from app.models.employee_off_day import EmployeeOffDay
from app.models.time_off_request import TimeOffRequest

def get_available_pool(db: Session, target_date: date = None)->dict:
    """Return all active employees grouped by role who are not off on the target date.

    Args:
        db: Database session.
        target_date: Date to check availability for. Defaults to today.

    Returns:
        A dict with keys ``"drivers"``, ``"trainers"``, ``"trainees"``, and ``"walkers"``, each
        containing a list of Employee ORM objects available on that date.
    """
    target_date = target_date or date.today()

    # 1. Define existence checks for both exclusion reasons.
    has_off_day_today = (
        db.query(EmployeeOffDay)
        .filter(
            EmployeeOffDay.employee_id == Employee.id,
            EmployeeOffDay.day_of_week == target_date.strftime("%A"),
            EmployeeOffDay.status == 'approved'
        )
        .exists()
    )

    has_pto_today = (
        db.query(TimeOffRequest)
        .filter(
            TimeOffRequest.employee_id == Employee.id,
            TimeOffRequest.date == target_date,
            TimeOffRequest.status == 'approved'
        )
        .exists()
    )

    # 2. Query ALL available employees in a single network round-trip
    available_employees = (
        db.query(Employee)
        .filter(
            Employee.role.in_(["driver", "trainer", "trainee", "walker"]),
            Employee.is_active == True,
            ~or_(has_off_day_today, has_pto_today)
        )
        .all()
    )

    available_pool = {
        "drivers": [],
        "trainers": [],
        "trainees": [],
        "walkers": []
    }

    # 3. Group the results in Python memory
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


def get_unavailable_staff(db: Session, target_date: date = None, roles: list = None) -> list:
    """Return active employees excluded from the available pool on target_date, with reason.

    The inverse of get_available_pool for a given set of roles. Used by dispatch
    to surface a call-in list when understaffed warnings fire.

    Trainees are intentionally excluded — their assignment flow is managed through
    the training system, not manual dispatch phone calls.

    An employee is excluded if they have:
    - An approved recurring off-day matching the target date's weekday, OR
    - An approved time-off request for the exact target date.

    When both apply, time_off_request takes priority (more specific reason).

    Args:
        db: Database session.
        target_date: Date to check. Defaults to today.
        roles: List of roles to include. Defaults to ["driver", "trainer", "walker"].
               "trainee" is always excluded even if passed.

    Returns:
        List of dicts: [{ "id", "name", "role", "discord_id", "phone_number", "reason" }, ...]
        reason is one of: "time_off_request" | "recurring_off_day"
    """
    target_date = target_date or date.today()
    day_name = target_date.strftime("%A")

    # Trainees are always excluded — never callable for ad-hoc coverage.
    allowed_roles = [r for r in (roles or ["driver", "trainer", "walker"]) if r != "trainee"]

    employees = (
        db.query(Employee)
        .filter(Employee.role.in_(allowed_roles), Employee.is_active == True)
        .all()
    )

    # Build exclusion sets — one query each, not per-employee.
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

    # Sort: role order (driver → trainer → walker), then name within role.
    role_order = {"driver": 0, "trainer": 1, "walker": 2}
    result.sort(key=lambda e: (role_order.get(e["role"], 9), e["name"]))

    return result


def get_unavailable_drivers(db: Session, target_date: date = None) -> list:
    """Convenience wrapper — returns unavailable drivers only.

    Kept for backward compatibility with existing call sites.
    """
    return get_unavailable_staff(db, target_date, roles=["driver"])


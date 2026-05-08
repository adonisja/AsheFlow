from datetime import date, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.api.deps import RoleChecker, get_caller_employee, assert_owns_or_privileged
from app.models.employee_off_day import EmployeeOffDay
from app.models.time_off_request import TimeOffRequest
from app.models.truck_assignment import TruckAssignment
from app.models.assignment_member import AssignmentMember
from app.models.truck import Truck
from app.models.employee import Employee

router = APIRouter(prefix="/schedule", tags=["schedule"])

allow_mgmt = RoleChecker(["management", "admin"])

@router.get("/{employee_id}")
def get_employee_schedule(
    employee_id: UUID,
    start_date: date,
    end_date: date,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
):
    """Return schedule data for an employee over a date range.

    Field staff (driver/walker/trainer/trainee) may only query their own schedule.
    Management and admin may query any employee's schedule.
    Dispatch cannot access schedules — they don't work shifts.
    """
    from fastapi import HTTPException, status as http_status
    if caller.role == "dispatch":
        raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail="Dispatch cannot access employee schedules.")
    assert_owns_or_privileged(caller, employee_id, "schedule")
    # Determine all dates to process
    delta = end_date - start_date
    if delta.days < 0:
        return []
    
    days = [start_date + timedelta(days=i) for i in range(delta.days + 1)]

    # 1. Fetch recurring off days for the employee
    off_days = db.query(EmployeeOffDay).filter(
        EmployeeOffDay.employee_id == employee_id,
        EmployeeOffDay.status.in_(["approved", "pending"])
    ).all()
    recurring_off_day_map = {od.day_of_week: od.status for od in off_days}

    # 1.5 Fetch specific date time-off requests
    time_off_reqs = db.query(TimeOffRequest).filter(
        TimeOffRequest.employee_id == employee_id,
        TimeOffRequest.date >= start_date,
        TimeOffRequest.date <= end_date,
        TimeOffRequest.status.in_(["approved", "pending"])
    ).all()
    specific_time_off_map = {req.date: req.status for req in time_off_reqs}

    # 2. Fetch assignments for the employee in the specified date range
    assignments = (
        db.query(TruckAssignment, AssignmentMember, Truck)
        .join(AssignmentMember, TruckAssignment.id == AssignmentMember.assignment_id)
        .join(Truck, TruckAssignment.truck_id == Truck.id)
        .filter(
            AssignmentMember.employee_id == employee_id,
            TruckAssignment.date >= start_date,
            TruckAssignment.date <= end_date
        )
        .all()
    )

    assignment_map = {}
    for ta, am, tr in assignments:
        assignment_map[ta.date] = {
            "truck_name": tr.name, 
            "assignment_id": ta.id
        }

    # 3. Fetch the full crew for any assignments found
    assignment_ids = [info["assignment_id"] for info in assignment_map.values()]
    crews = {}
    if assignment_ids:
        all_crew_members = (
            db.query(AssignmentMember, Employee)
            .join(Employee, AssignmentMember.employee_id == Employee.id)
            .filter(AssignmentMember.assignment_id.in_(assignment_ids))
            .all()
        )
        for crew_am, crew_emp in all_crew_members:
            if crew_am.assignment_id not in crews:
                crews[crew_am.assignment_id] = []
            crews[crew_am.assignment_id].append({
                "id": str(crew_emp.id),
                "name": crew_emp.name,
                "role": crew_am.role
            })

    # 4. Construct the schedule response
    results = []
    # Base recurring off day logic (case-insensitive)
    recurring_off_day_map_lower = {k.lower(): v for k, v in recurring_off_day_map.items()}

    for d in days:
        day_str = d.strftime('%A').lower()
        status = "Available"
        truck_name = None
        crew = None

        # Base recurring off day logic
        if day_str in recurring_off_day_map_lower:
            if recurring_off_day_map_lower[day_str] == "approved":
                status = "Off (Recurring)"
            elif recurring_off_day_map_lower[day_str] == "pending":
                status = "Pending Off (Recurring)"
        
        # Override with exact date requests (supercedes recurring if conflicting or pending)
        if d in specific_time_off_map:
            if specific_time_off_map[d] == "approved":
                status = "Time Off"
            elif specific_time_off_map[d] == "pending":
                if status != "Off (Recurring)":
                    status = "Pending Time Off"
        
        # Override with assignment if scheduled
        if d in assignment_map:
            status = "Assigned"
            truck_name = assignment_map[d]["truck_name"]
            assignment_id = assignment_map[d]["assignment_id"]
            crew = crews.get(assignment_id, [])
        
        results.append({
            "date": d,
            "status": status,
            "truck_name": truck_name,
            "crew": crew
        })

    return results

@router.get("/available/{target_date}")
def get_available_employees(
    target_date: date,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_mgmt),
    db: Session = Depends(get_db),
):
    day_name = target_date.strftime("%A")

    has_recurring_off = (
        db.query(EmployeeOffDay)
        .filter(
            EmployeeOffDay.employee_id == Employee.id,
            EmployeeOffDay.day_of_week.ilike(day_name),
            EmployeeOffDay.status == 'approved'
        )
        .exists()
    )

    has_specific_off = (
        db.query(TimeOffRequest)
        .filter(
            TimeOffRequest.employee_id == Employee.id,
            TimeOffRequest.date == target_date,
            TimeOffRequest.status == 'approved'
        )
        .exists()
    )

    available_employees = (
        db.query(Employee)
        .filter(
            Employee.company_id == caller.company_id,
            Employee.is_active == True,
            ~has_recurring_off,
            ~has_specific_off,
        )
        .order_by(Employee.role, Employee.name)
        .all()
    )

    pool = {"driver": [], "trainer": [], "walker": [], "trainee": []}
    for e in available_employees:
        role = str(e.role).lower()
        if role in pool:
            pool[role].append({"id": str(e.id), "name": e.name, "role": role})

    return pool

from datetime import date, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.employee_off_day import EmployeeOffDay
from app.models.time_off_request import TimeOffRequest
from app.models.truck_assignment import TruckAssignment
from app.models.assignment_member import AssignmentMember
from app.models.truck import Truck
from app.models.employee import Employee

router = APIRouter(prefix="/schedule", tags=["schedule"])

@router.get("/{employee_id}")
def get_employee_schedule(
    employee_id: UUID, 
    start_date: date, 
    end_date: date, 
    db: Session = Depends(get_db)
):
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
            crews[crew_am.assignment_id].append(f"{crew_am.role}: {crew_emp.name}")

    # 4. Construct the schedule response
    results = []
    for d in days:
        day_str = d.strftime('%A')
        status = "Available"
        truck_name = None
        crew = None

        # Base recurring off day logic
        if day_str in recurring_off_day_map:
            if recurring_off_day_map[day_str] == "approved":
                status = "Off (Recurring)"
            elif recurring_off_day_map[day_str] == "pending":
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

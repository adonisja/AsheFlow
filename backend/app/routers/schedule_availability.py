from datetime import date
from typing import Dict, List
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import exists, and_
from app.database import get_db
from app.models.employee import Employee
from app.models.employee_off_day import EmployeeOffDay
from app.models.time_off_request import TimeOffRequest

router = APIRouter(prefix="/available", tags=["schedule"])

@router.get("/{target_date}")
def get_available_employees(
    target_date: date,
    db: Session = Depends(get_db)
):
    day_name = target_date.strftime("%A")

    # Recurring off
    has_recurring_off = (
        db.query(EmployeeOffDay)
        .filter(
            EmployeeOffDay.employee_id == Employee.id,
            EmployeeOffDay.day_of_week.ilike(day_name),
            EmployeeOffDay.status == 'approved'
        )
        .exists()
    )

    # Specific date off
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
            Employee.is_active == True,
            ~has_recurring_off,
            ~has_specific_off
        )
        .order_by(Employee.role, Employee.name)
        .all()
    )

    pool = {"driver": [], "trainer": [], "walker": []}
    for e in available_employees:
        role = str(e.role).lower()
        if role in pool:
            pool[role].append({"id": str(e.id), "name": e.name, "role": role})
            
    return pool
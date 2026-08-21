"""EOD reminder tasks.

Fires at 17:00 (5 PM) Eastern daily to remind drivers who have not yet
submitted their fuel/mileage log for today. Only fires on days where a
dispatch exists (no false alarms on non-dispatch days).

A second pass at 18:30 (6:30 PM) re-notifies any still-missing drivers —
this handles late returns.
"""

from app.celery_app import celery_app
from app.database import SessionLocal
from app.services.local_date import task_today, fetch_company_timezones
from app.models.employee import Employee
from app.models.field_ops import FuelMileageLog, CheckIn
from app.models.notification import Notification
from app.models.truck_assignment import TruckAssignment
from app.models.assignment_member import AssignmentMember


@celery_app.task(name="app.tasks.eod_reminders.remind_fuel_log_missing")
def remind_fuel_log_missing() -> dict:
    """Fires at 17:00 and 18:30 Eastern.

    Finds every driver who:
      1. Was dispatched today (has an AssignmentMember row with role='driver')
      2. Checked in today (has a CheckIn row for today)
      3. Has NOT submitted a FuelMileageLog for today

    Sends each of them an in-app notification reminder.
    Returns a summary dict.
    """
    db = SessionLocal()
    try:
        tz_map = fetch_company_timezones(db)
        total_reminded = 0

        for company_id, tz in tz_map.items():
            today = task_today(tz)

            has_dispatch = db.query(TruckAssignment).filter(
                TruckAssignment.company_id == company_id,
                TruckAssignment.date == today,
            ).first()
            if not has_dispatch:
                continue

            dispatched_driver_ids = {
                str(row.employee_id)
                for row in (
                    db.query(AssignmentMember)
                    .join(TruckAssignment, AssignmentMember.assignment_id == TruckAssignment.id)
                    .filter(
                        TruckAssignment.company_id == company_id,
                        TruckAssignment.date == today,
                        AssignmentMember.role == "driver",
                    )
                    .all()
                )
            }
            if not dispatched_driver_ids:
                continue

            checked_in_ids = {
                str(row.employee_id)
                for row in db.query(CheckIn).filter(
                    CheckIn.company_id == company_id,
                    CheckIn.date == today,
                ).all()
            }

            submitted_ids = {
                str(row.driver_id)
                for row in db.query(FuelMileageLog).filter(
                    FuelMileageLog.company_id == company_id,
                    FuelMileageLog.date == today,
                ).all()
            }

            missing_ids = (dispatched_driver_ids & checked_in_ids) - submitted_ids
            if not missing_ids:
                continue

            import uuid as _uuid
            drivers = db.query(Employee).filter(
                Employee.company_id == company_id,
                Employee.id.in_([_uuid.UUID(eid) for eid in missing_ids]),
            ).all()

            for driver in drivers:
                db.add(Notification(
                    company_id=company_id,
                    employee_id=driver.id,
                    type="fuel_log_reminder",
                    message=(
                        f"📋 Reminder: Please submit your fuel and mileage log for today ({today}). "
                        f"Go to Field Ops → Fuel & Mileage to complete your submission."
                    ),
                ))

            total_reminded += len(drivers)

        db.commit()
        return {"status": "ok", "reminded": total_reminded}
    finally:
        db.close()

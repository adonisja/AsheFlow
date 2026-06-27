import logging
import asyncio
from datetime import datetime, timedelta

from app.celery_app import celery_app
from app.database import SessionLocal
from app.services.local_date import task_today, fetch_company_timezones
from app.models.adp_integration import ADPIntegration
from app.models.employee import Employee
from app.models.adp_timecard import ADPTimeCard, ADPTimeCardSegment
from app.services.adp import fetch_adp_timecard

logger = logging.getLogger(__name__)

@celery_app.task(name="app.tasks.adp_timecard_sync.sync_adp_timecards")
def sync_adp_timecards() -> dict:
    """Fetch and store the previous day's ADP timecards for all verified employees.

    Runs daily at 06:00 AM Eastern. For each company with an enabled ADP integration,
    fetches timecards for every employee whose ADP association has been verified.

    Each timecard is upserted: created on first fetch, updated on re-fetch (e.g.,
    if the task is re-run after a failure). Timecard segments (clock-in/out pairs)
    are replaced wholesale on each sync to ensure consistency with ADP's current state.

    A per-company try/except ensures one company's failure does not block others.
    """

    db = SessionLocal()
    try:
        tz_map = fetch_company_timezones(db)

        integrations = db.query(ADPIntegration).filter(
            ADPIntegration.is_enabled == True
        ).all()

        for integration in integrations:
            try:
                work_date = task_today(tz_map.get(integration.company_id)) - timedelta(days=1)
                employees = db.query(Employee).filter(
                    Employee.is_active == True,
                    Employee.hr_system_id_adp_verified == True,
                    Employee.company_id == integration.company_id,
                ).all()

                for employee in employees:
                    timecard = asyncio.run(fetch_adp_timecard(integration, employee.hr_system_id_adp, work_date))

                    existing_timecard = db.query(ADPTimeCard).filter(
                        ADPTimeCard.employee_id == employee.id,
                        ADPTimeCard.work_date == work_date,
                    ).first()

                    if not timecard:
                        is_working_day = False
                        raw_payload = None

                    else:
                        is_working_day = True
                        raw_payload = timecard
                        
                    
                    if existing_timecard is None:
                       db.add(ADPTimeCard(
                           company_id = integration.company_id,
                           employee_id = employee.id,
                           adp_associate_oid = employee.hr_system_id_adp,
                           work_date = work_date,
                           is_working_day = is_working_day,
                           raw_payload = raw_payload,
                           fetched_at = datetime.now()
                        ))
                    else:
                        existing_timecard.is_working_day = is_working_day
                        existing_timecard.raw_payload = raw_payload
                        existing_timecard.fetched_at = datetime.now()

                    db.commit()

                    if is_working_day and timecard:
                        timecard_row = existing_timecard if existing_timecard else db.query(ADPTimeCard).filter(
                            ADPTimeCard.employee_id == employee.id,
                            ADPTimeCard.work_date == work_date,
                        ).first()

                        if existing_timecard:
                            deleted_rows = db.query(ADPTimeCardSegment).filter(
                                ADPTimeCardSegment.company_id == integration.company_id,
                                ADPTimeCardSegment.timecard_id == timecard_row.id
                            ).all()

                            for row in deleted_rows:
                                db.delete(row)

                        db.commit()

                        for index, entry in enumerate(timecard.get("timeLaborEntries", [])):
                            db.add(ADPTimeCardSegment(
                                company_id = integration.company_id,
                                timecard_id = timecard_row.id,
                                segment_index = index,
                                clock_in_at = entry.get("clockIn"),
                                clock_out_at = entry.get("clockOut")
                            ))
                        
                        db.commit()

            except Exception as e:
                logger.warning("ADP timecard sync failed for company %s: %s", integration.company_id, e)
                continue
        
        return {"status": "ok"}
    
    finally:
        db.close()

    
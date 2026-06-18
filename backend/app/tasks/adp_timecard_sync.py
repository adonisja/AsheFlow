import logging
import asyncio
from datetime import date, datetime, timedelta

from app.celery_app import celery_app
from app.database import SessionLocal
from app.models.adp_integration import ADPIntegration
from app.models.employee import Employee
from app.models.adp_timecard import ADPTimeCard, ADPTimeCardSegment
from app.services.adp import fetch_adp_timecard

logger = logging.getLogger(__name__)

@celery_app.task(name="app.tasks.adp_timecard_sync.sync_adp_timecards")
def sync_adp_timecards() -> dict:

    work_date: date = date.today() - timedelta(days=1)
    db = SessionLocal()
    try:
        
        integrations = db.query(ADPIntegration).filter(
            ADPIntegration.is_enabled == True
        ).all()

        for integration in integrations:
            try:
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
                logger.warning(f"Integration failed for company {integration.company_id}: {e}")
                continue
        
        return {"status": "ok"}
    
    finally:
        db.close()

    
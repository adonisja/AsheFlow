import asyncio
import logging
from itertools import groupby

from datetime import datetime, date, timezone
from app.models.employee import Employee
from app.celery_app import celery_app
from app.database import SessionLocal

from app.models.timecard_adjustments import TimeCardAdjustment
from app.models.adp_integration import ADPIntegration
from app.models.adp_pay_period import ADPPayPeriod
from app.models.notification import Notification

from app.services.adp import patch_adp_timecard
from app.services.adp_exceptions import ADPServerError, ADPClientError

logger = logging.getLogger(__name__)

@celery_app.task(name="app.tasks.failed_adp_writes.retry_failed_adp_writes")
def retry_failed_adp_writes():

    db = SessionLocal()
    try:
        adjustments = db.query(TimeCardAdjustment).filter(
            TimeCardAdjustment.status == "write_failed",
            TimeCardAdjustment.is_retryable == True
        ).order_by(TimeCardAdjustment.company_id).all()

        adjustment_map = {k: list(g) for k,g in groupby(adjustments, key=lambda x: x.company_id)}

        for company_id, company_adjustments in adjustment_map.items():
            integration = db.query(ADPIntegration).filter(
                ADPIntegration.company_id == company_id
            ).first()

            employee_ids = [a.employee_id for a in company_adjustments]

            # Bulk-fetch all Employee rows 
            employees = db.query(Employee).filter(Employee.id.in_(employee_ids)).all()
            employee_map = {e.id: e for e in employees}

            pay_period_ids = [a.pay_period_id for a in company_adjustments]
            pay_periods = db.query(ADPPayPeriod).filter(ADPPayPeriod.id.in_(pay_period_ids)).all()
            pay_period_id_map = {p.id: p for p in pay_periods}

            
            for adjustment in company_adjustments:
                employee = employee_map[adjustment.employee_id]
                pay_period = pay_period_id_map[adjustment.pay_period_id]
                associate_oid = employee.hr_system_id_adp
                pay_period_id = pay_period.adp_pay_period_id
                break_start = adjustment.proposed_break_start_at
                break_end = adjustment.proposed_break_end_at
                try: 
                    new_timecard = asyncio.run(patch_adp_timecard(integration, associate_oid, pay_period_id, break_start, break_end))
                    adjustment.status = "applied"
                    adjustment.adp_applied_at = datetime.now(timezone.utc)
                    adjustment.adp_response_payload = new_timecard
                    

                except ADPClientError as e:
                    notif_message = (
                        f"ADP timecard update to failed due to malformed "
                        f"payload, please review before retrying: {e.body}\n"
                        f"Employee: {employee.name}\n"
                        f'Break: {adjustment.proposed_break_start_at.strftime("%I:%M %p")} - {adjustment.proposed_break_end_at.strftime("%I:%M %p")}'
                        )
                    adjustment.write_attempt_count += 1
                    managers_and_admins = db.query(Employee).filter(
                        Employee.company_id == adjustment.company_id,
                        Employee.role.in_(["admin", "manager"]),
                        Employee.is_active == True
                    ).all()
                    for person in managers_and_admins:
                        db.add(Notification(
                            company_id = integration.company_id,
                            employee_id = person.id,
                            type = "timecard_update_failed",
                            message = notif_message
                        ))
                    adjustment.is_retryable = False
                    

                except ADPServerError as e:
                    adjustment.write_attempt_count += 1
                    logger.warning(f"Failed to write Timecard Adjustment ({adjustment.id}) to ADP for {employee.name}: {e}")

                db.commit()


    finally:
        db.close()
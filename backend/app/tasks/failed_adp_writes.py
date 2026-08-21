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
    """Re-attempt failed ADP timecard writes before the pay period close deadline.

    Runs on a Beat schedule every 2 hours Saturday–Sunday and a final pass
    Monday 18:00 Eastern. Queries all write_failed adjustments where is_retryable
    is True, groups them by company to minimise database round-trips, then calls
    patch_adp_timecard for each one.

    Outcomes per adjustment:
    - Success: status → "applied", adp_applied_at and adp_response_payload stamped.
    - ADPClientError (4xx): is_retryable → False, managers notified. Will not be
      retried again — requires human review of the payload.
    - ADPServerError (5xx / network): write_attempt_count incremented, warning
      logged. Adjustment remains retryable for the next scheduled run.
    """

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
                associate_oid = employee.hr_system_id_adp
                work_assignment_id = employee.hr_system_work_assignment_id_adp
                break_start = adjustment.proposed_break_start_at
                break_end = adjustment.proposed_break_end_at

                # Both ADP references are required by the write. Retrying without
                # them would burn attempts on a payload ADP must reject, so the
                # adjustment is parked as non-retryable for human review instead.
                if not adjustment.adp_entry_id or not work_assignment_id:
                    logger.warning(
                        "Adjustment %s (company %s) not retryable: missing %s",
                        adjustment.id, adjustment.company_id,
                        "adp_entry_id" if not adjustment.adp_entry_id else "work assignment id",
                    )
                    adjustment.is_retryable = False
                    db.commit()
                    continue

                try:
                    new_timecard = asyncio.run(patch_adp_timecard(
                        integration,
                        associate_oid,
                        work_assignment_id,
                        adjustment.adp_entry_id,
                        adjustment.work_date,
                        break_start,
                        break_end,
                    ))
                    adjustment.status = "applied"
                    adjustment.adp_applied_at = datetime.now(timezone.utc)
                    adjustment.adp_response_payload = new_timecard
                    

                except ADPClientError as e:
                    break_window = (
                        f"{adjustment.proposed_break_start_at.strftime('%I:%M %p')} - "
                        f"{adjustment.proposed_break_end_at.strftime('%I:%M %p')}"
                    )
                    logger.warning(
                        "ADP rejected timecard write for adjustment %s (employee %s, company %s) "
                        "with status %s — payload invalid, marking non-retryable. ADP response: %s",
                        adjustment.id, employee.name, adjustment.company_id, e.status_code, e.body
                    )
                    notif_message = (
                        f"ADP rejected the timecard correction for {employee.name.title()} "
                        f"(break: {break_window}) — the submission was invalid and will not be "
                        f"retried automatically. Please review the adjustment and re-submit manually."
                    )
                    adjustment.write_attempt_count += 1
                    adjustment.is_retryable = False
                    managers_and_admins = db.query(Employee).filter(
                        Employee.company_id == adjustment.company_id,
                        Employee.role.in_(["admin", "manager"]),
                        Employee.is_active == True
                    ).all()
                    for person in managers_and_admins:
                        db.add(Notification(
                            company_id=integration.company_id,
                            employee_id=person.id,
                            type="timecard_update_failed",
                            message=notif_message,
                        ))

                except ADPServerError as e:
                    logger.warning(
                        "ADP timecard write failed for adjustment %s (employee %s, company %s) "
                        "with status %s — will retry on next scheduled run.",
                        adjustment.id, employee.name, adjustment.company_id, e.status_code
                    )
                    adjustment.write_attempt_count += 1

                db.commit()


    finally:
        db.close()
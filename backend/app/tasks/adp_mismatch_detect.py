import logging

from datetime import date, datetime, timedelta, timezone
from app.celery_app import celery_app

from app.database import SessionLocal
from app.models.adp_integration import ADPIntegration
from app.models.adp_timecard import ADPTimeCard, ADPTimeCardSegment
from app.models.flex_timesheets import FlexTimesheet
from app.models.timecard_adjustments import TimeCardAdjustment
from app.models.adp_pay_period import ADPPayPeriod
from app.models.company import CompanyConfig
from app.models.employee import Employee
from app.models.notification import Notification

logger = logging.getLogger(__name__)


def _calculate_urgency(detected_at, company_config) -> str:
    urgent_day = company_config.adp_urgent_correction_day if company_config else 5
    mandatory_day = company_config.adp_mandatory_correction_day if company_config else 6
    mandatory_hour = company_config.adp_mandatory_correction_hour if company_config else 0

    if detected_at.weekday() >= mandatory_day and detected_at.hour >= mandatory_hour:
        return "mandatory"
    elif detected_at.weekday() >= urgent_day:
        return "urgent"
    else:
        return "routine"
    

@celery_app.task(name="app.tasks.adp_mismatch_detect.detect_timecard_mismatches")
def detect_timecard_mismatches() -> dict:
    db = SessionLocal()
    try:
        integrations = db.query(ADPIntegration).filter(
            ADPIntegration.is_enabled == True
        ).all()

        for integration in integrations:
            try:
                timecards = db.query(ADPTimeCard).filter(
                    ADPTimeCard.company_id == integration.company_id,
                    ADPTimeCard.work_date == (date.today() - timedelta(days=1)),
                    ADPTimeCard.is_working_day == True
                ).all()

                company_config = db.query(CompanyConfig).filter(
                    CompanyConfig.company_id == integration.company_id
                ).first()

                now = datetime.now(timezone.utc)
                urgency = _calculate_urgency(now, company_config)

                for timecard in timecards:
                    flex = db.query(FlexTimesheet).filter(
                        FlexTimesheet.company_id == integration.company_id,
                        FlexTimesheet.employee_id == timecard.employee_id,
                        FlexTimesheet.work_date == timecard.work_date
                    ).first()

                    if not flex: continue

                    employee = db.query(Employee).filter(
                        Employee.company_id == integration.company_id,
                        Employee.id == timecard.employee_id
                    ).first()

                    segments = db.query(ADPTimeCardSegment).filter(
                        ADPTimeCardSegment.company_id == integration.company_id,
                        ADPTimeCardSegment.timecard_id == timecard.id,
                    ).order_by(ADPTimeCardSegment.segment_index.asc()).all()

                    open_adjustment = db.query(TimeCardAdjustment).filter(
                        TimeCardAdjustment.company_id == integration.company_id,
                        TimeCardAdjustment.employee_id == timecard.employee_id,
                        TimeCardAdjustment.work_date == timecard.work_date,
                        TimeCardAdjustment.status.notin_(["applied", "rejected"])
                    ).first()

                    if open_adjustment: continue

                    pay_period = db.query(ADPPayPeriod).filter(
                        ADPPayPeriod.company_id == integration.company_id,
                        ADPPayPeriod.period_start <= timecard.work_date,
                        ADPPayPeriod.period_end >= timecard.work_date,
                    ).first()
                    
                    if not pay_period: continue

                    if not segments:
                        description = f"{employee.name.title()} has no ADP timecard segments found for working day {timecard.work_date}"
                        db.add(TimeCardAdjustment(
                            company_id = integration.company_id,
                            employee_id = timecard.employee_id,
                            flex_timesheet_id = flex.id,
                            pay_period_id = pay_period.id,
                            adp_timecard_id = timecard.id,
                            work_date = timecard.work_date,
                            proposed_break_start_at = flex.break_start_at,
                            proposed_break_end_at = flex.break_end_at,
                            mismatch_description = description,
                            status = "pending_employee",
                            urgency = urgency,
                            detected_at = now
                        ))
                        db.commit()
                        db.add(Notification(
                            company_id = integration.company_id,
                            employee_id = timecard.employee_id,
                            type = "timecard_mismatch",
                            message = f"Action required: {description}. Please review and sign off in AsheFlow."
                        ))
                        db.commit()
                        continue
                    
                    missing_entry = False
                    for segment in segments:
                        if segment.clock_in_at is None:
                            description = f"{employee.name.title()} has a missing Lunch Break Punch In for {timecard.work_date} on segment {segment.segment_index}"
                            db.add(TimeCardAdjustment(
                                company_id = integration.company_id,
                                employee_id = timecard.employee_id,
                                flex_timesheet_id = flex.id,
                                pay_period_id = pay_period.id,
                                adp_timecard_id = timecard.id,
                                work_date = timecard.work_date,
                                proposed_break_start_at = flex.break_start_at,
                                proposed_break_end_at = flex.break_end_at,
                                mismatch_description = description,
                                status = "pending_employee",
                                urgency = urgency,
                                detected_at = now
                            ))
                            db.commit()
                            db.add(Notification(
                                company_id = integration.company_id,
                                employee_id = timecard.employee_id,
                                type = "timecard_mismatch",
                                message = f"Action required: {description}. Please review and sign off in AsheFlow."
                            ))
                            db.commit()
                            missing_entry = True
                            

                        if segment.clock_out_at is None:
                            description = f"{employee.name.title()} has a missing Lunch Break Punch Out for {timecard.work_date} on segment {segment.segment_index}"
                            db.add(TimeCardAdjustment(
                                    company_id = integration.company_id,
                                    employee_id = timecard.employee_id,
                                    flex_timesheet_id = flex.id,
                                    pay_period_id = pay_period.id,
                                    adp_timecard_id = timecard.id,
                                    work_date = timecard.work_date,
                                    proposed_break_start_at = flex.break_start_at,
                                    proposed_break_end_at = flex.break_end_at,
                                    mismatch_description = description,
                                    status = "pending_employee",
                                    urgency = urgency,
                                    detected_at = now
                            ))
                            db.commit()
                            db.add(Notification(
                                company_id = integration.company_id,
                                employee_id = timecard.employee_id,
                                type = "timecard_mismatch",
                                message = f"Action required: {description}. Please review and sign off in AsheFlow."
                            ))
                            db.commit()
                            missing_entry = True
                            
                    if missing_entry: continue

                    adp_break_start = None
                    adp_break_end = None

                    for i in range(len(segments) - 1):
                        gap_start = segments[i].clock_out_at
                        gap_end = segments[i+1].clock_in_at
                        if (gap_end - gap_start) >= timedelta(minutes=30):
                            adp_break_start = gap_start
                            adp_break_end = gap_end
                            break

                    if adp_break_start is None:
                        description = f"{employee.name.title()} is missing a Lunch Break Period on {timecard.work_date}"
                        db.add(TimeCardAdjustment(
                            company_id = integration.company_id,
                            employee_id = timecard.employee_id,
                            flex_timesheet_id = flex.id,
                            pay_period_id = pay_period.id,
                            adp_timecard_id = timecard.id,
                            work_date = timecard.work_date,
                            proposed_break_start_at = flex.break_start_at,
                            proposed_break_end_at = flex.break_end_at,
                            mismatch_description = description,
                            status = "pending_employee",
                            urgency = urgency,
                            detected_at = now
                        ))
                        db.commit()
                        db.add(Notification(
                            company_id = integration.company_id,
                            employee_id = timecard.employee_id,
                            type = "timecard_mismatch",
                            message = f"Action required: {description}. Please review and sign off"
                        ))
                        db.commit()
                        continue

                    if abs(adp_break_start - flex.break_start_at) > timedelta(minutes=5) or abs(adp_break_end - flex.break_end_at) > timedelta(minutes=5):
                        description = f"{employee.name.title()} has a Break Mismatch on {timecard.work_date}: Flex [{flex.break_start_at} - {flex.break_end_at}] vs ADP [{adp_break_start} - {adp_break_end}]"
                        db.add(TimeCardAdjustment(
                            company_id = integration.company_id,
                            employee_id = timecard.employee_id,
                            flex_timesheet_id = flex.id,
                            pay_period_id = pay_period.id,
                            adp_timecard_id = timecard.id,
                            work_date = timecard.work_date,
                            proposed_break_start_at = flex.break_start_at,
                            proposed_break_end_at = flex.break_end_at,
                            mismatch_description = description,
                            status = "pending_employee",
                            urgency = urgency,
                            detected_at = now
                        ))
                        db.commit()
                        db.add(Notification(
                            company_id = integration.company_id,
                            employee_id = timecard.employee_id,
                            type = "timecard_mismatch",
                            message = f"Action required: {description}. Please review and sign off"
                        ))
                        db.commit()
                        continue

   
            except Exception as e:
                logger.warning(f"Integration failed for company {integration.company_id}: {e}")
                continue

       

        return {"status": "ok"}
    finally:
        db.close()
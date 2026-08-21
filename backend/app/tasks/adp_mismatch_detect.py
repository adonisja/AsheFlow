"""Detect break-window disagreements between ADP and Amazon Flex (ADR-233).

AsheFlow is not a system of record for timecards or labour compliance. ADP owns
the timecard, its retention, and native meal-break violation reporting; Flex owns
Amazon's break telemetry. AsheFlow owns the one thing neither can see: **that the
two disagree** — because neither system holds the other's data.

So the test for raising a finding is not "does ADP have a problem here?" (ADP
sees its own gaps and reports them). It is **"does Flex hold data that resolves
it?"** ADP reporting "no break recorded" is not ADP being able to fill it; only
AsheFlow sees both sides.

Every finding proposes one value: the Flex break window. Nothing is ever written
to ADP from here — findings are created in `pending_employee` and reach payroll
only after the employee signs off and a manager approves.
"""
import logging
from datetime import datetime, timedelta, timezone

from app.celery_app import celery_app
from app.database import SessionLocal
from app.services.local_date import task_today, fetch_company_timezones
from app.models.adp_integration import ADPIntegration
from app.models.adp_timecard import ADPTimeCard, ADPTimeCardBreak
from app.models.flex_timesheets import FlexTimesheet
from app.models.timecard_adjustments import TimeCardAdjustment
from app.models.adp_pay_period import ADPPayPeriod
from app.models.company import CompanyConfig
from app.models.employee import Employee
from app.models.notification import Notification
from app.services.adp_urgency import calculate_urgency
from app.services.break_selection import (
    MIN_QUALIFYING_BREAK,
    BreakCandidate,
    select_break,
)

logger = logging.getLogger(__name__)

# How far ADP's break window may differ from Flex's before it is a finding.
# Absorbs clock drift and rounding between the two systems.
MISMATCH_TOLERANCE = timedelta(minutes=5)


def _fmt(value: datetime | None) -> str:
    """Render a break bound for the description shown to the employee."""
    return value.strftime("%-I:%M %p") if value else "—"


def _describe(finding_type: str, work_date, flex, adp_start, adp_end) -> str:
    """Human-readable description of the disagreement.

    Deliberately carries no employee name: the row already has employee_id, and
    a name baked into a string is a denormalised copy that drifts and escapes
    redaction. The name is resolved at read time from the FK (ADR-233).
    """
    flex_window = f"{_fmt(flex.break_start_at)}–{_fmt(flex.break_end_at)}"

    if finding_type == "entry_missing_in_adp":
        return (
            f"ADP has no time entries for {work_date}, but Flex recorded a break "
            f"of {flex_window}."
        )
    if finding_type == "break_missing_in_adp":
        return (
            f"ADP recorded no break on {work_date}, but Flex recorded {flex_window}."
        )
    if finding_type == "break_short_in_adp":
        return (
            f"ADP recorded a break of {_fmt(adp_start)}–{_fmt(adp_end)} on {work_date}, "
            f"under the 30-minute minimum. Flex recorded {flex_window}."
        )
    return (
        f"Break times differ on {work_date}: Flex recorded {flex_window}, "
        f"ADP recorded {_fmt(adp_start)}–{_fmt(adp_end)}."
    )


def _open_finding(
    db, *, integration, employee, flex, timecard, pay_period, urgency, now,
    finding_type, adp_entry_id, adp_start=None, adp_end=None,
) -> None:
    """Create one adjustment in pending_employee, and notify the employee.

    The proposed correction is always the Flex break window — that is the value
    the other system holds and ADP does not. This function never contacts ADP.
    """
    description = _describe(finding_type, timecard.work_date, flex, adp_start, adp_end)

    db.add(TimeCardAdjustment(
        company_id=integration.company_id,
        employee_id=employee.id,
        flex_timesheet_id=flex.id,
        pay_period_id=pay_period.id,
        adp_timecard_id=timecard.id,
        adp_entry_id=adp_entry_id,
        work_date=timecard.work_date,
        finding_type=finding_type,
        proposed_break_start_at=flex.break_start_at,
        proposed_break_end_at=flex.break_end_at,
        mismatch_description=description,
        status="pending_employee",
        urgency=urgency,
        detected_at=now,
    ))
    db.add(Notification(
        company_id=integration.company_id,
        employee_id=employee.id,
        type="timecard_mismatch",
        message=f"Action required: {description} Please review and sign off in AsheFlow.",
    ))


@celery_app.task(name="app.tasks.adp_mismatch_detect.detect_timecard_mismatches")
def detect_timecard_mismatches() -> dict:
    """Compare the previous day's ADP breaks against Flex and open findings.

    Runs daily at 12:00 PM Eastern, per company, gated on
    `mismatch_detection_enabled`.

    Raises a finding only where Flex holds data that resolves the disagreement:

    - `entry_missing_in_adp`  Flex working day, ADP has no time entries
    - `break_missing_in_adp`  ADP recorded no break, Flex did
    - `break_short_in_adp`    ADP's break is under 30 min, Flex's is not
    - `break_time_mismatch`   both have a break, windows differ by >5 min

    Deliberately not findings: both systems agreeing a break was short (no
    disagreement, and ADP reports it natively), and daily clock in/out (ADP's
    attendance domain).

    Skips employees with an open adjustment for that date. A per-company
    try/except keeps one company's failure from blocking others.
    """
    db = SessionLocal()
    try:
        tz_map = fetch_company_timezones(db)
        integrations = db.query(ADPIntegration).filter(
            ADPIntegration.is_enabled == True
        ).all()

        opened = 0

        for integration in integrations:
            try:
                if not integration.mismatch_detection_enabled:
                    logger.info(
                        "ADP mismatch detection gated off for company %s — enable "
                        "after reviewing the dry-run count (ADR-233)",
                        integration.company_id,
                    )
                    continue

                work_date = task_today(tz_map.get(integration.company_id)) - timedelta(days=1)

                company_config = db.query(CompanyConfig).filter(
                    CompanyConfig.company_id == integration.company_id
                ).first()
                now = datetime.now(timezone.utc)
                urgency = calculate_urgency(now, company_config)

                # Flex is the entry point: no Flex record means nothing to
                # disagree with, so iterate Flex rather than ADP timecards.
                flex_records = db.query(FlexTimesheet).filter(
                    FlexTimesheet.company_id == integration.company_id,
                    FlexTimesheet.work_date == work_date,
                ).all()

                for flex in flex_records:
                    employee = db.query(Employee).filter(
                        Employee.company_id == integration.company_id,
                        Employee.id == flex.employee_id,
                    ).first()
                    if not employee:
                        continue

                    open_adjustment = db.query(TimeCardAdjustment).filter(
                        TimeCardAdjustment.company_id == integration.company_id,
                        TimeCardAdjustment.employee_id == flex.employee_id,
                        TimeCardAdjustment.work_date == work_date,
                        TimeCardAdjustment.status.notin_(["applied", "rejected"]),
                    ).first()
                    if open_adjustment:
                        continue

                    pay_period = db.query(ADPPayPeriod).filter(
                        ADPPayPeriod.company_id == integration.company_id,
                        ADPPayPeriod.period_start <= work_date,
                        ADPPayPeriod.period_end >= work_date,
                    ).first()
                    if not pay_period:
                        # A finding cannot be created without one:
                        # pay_period_id is NOT NULL. An empty adp_pay_periods
                        # table therefore disables detection wholesale, which is
                        # how this went unnoticed before — so it is logged, never
                        # silent (ADR-233).
                        logger.warning(
                            "Detection skipped employee %s on %s (company %s): no pay "
                            "period covers this date — check adp_pay_period_sync",
                            flex.employee_id, work_date, integration.company_id,
                        )
                        continue

                    timecard = db.query(ADPTimeCard).filter(
                        ADPTimeCard.company_id == integration.company_id,
                        ADPTimeCard.employee_id == flex.employee_id,
                        ADPTimeCard.work_date == work_date,
                    ).first()
                    if not timecard:
                        # ADP was never synced for this employee/date — that is a
                        # sync gap, not a disagreement. Raising a finding here
                        # would propose a correction against an entry we have not
                        # actually seen.
                        logger.warning(
                            "Detection skipped employee %s on %s (company %s): no ADP "
                            "timecard synced",
                            flex.employee_id, work_date, integration.company_id,
                        )
                        continue

                    breaks = db.query(ADPTimeCardBreak).filter(
                        ADPTimeCardBreak.company_id == integration.company_id,
                        ADPTimeCardBreak.timecard_id == timecard.id,
                    ).order_by(ADPTimeCardBreak.start_at.asc()).all()

                    finding = _classify(timecard, breaks, flex)
                    if finding is None:
                        continue

                    finding_type, adp_entry_id, adp_start, adp_end = finding
                    _open_finding(
                        db,
                        integration=integration, employee=employee, flex=flex,
                        timecard=timecard, pay_period=pay_period,
                        urgency=urgency, now=now,
                        finding_type=finding_type, adp_entry_id=adp_entry_id,
                        adp_start=adp_start, adp_end=adp_end,
                    )
                    opened += 1

                # One commit per company rather than per finding — a company's
                # findings land together or not at all.
                db.commit()

            except Exception as e:
                db.rollback()
                logger.warning(
                    "ADP mismatch detection failed for company %s: %s",
                    integration.company_id, e,
                )
                continue

        return {"status": "ok", "findings_opened": opened}
    finally:
        db.close()


def _classify(timecard, breaks, flex):
    """Decide whether this employee/date is a finding, and which kind.

    Returns (finding_type, adp_entry_id, adp_start, adp_end) or None.

    Kept separate from the task so the decision can be tested without a session.
    """
    # ADP has no entries at all for a day Flex says was worked.
    if not timecard.is_working_day:
        return ("entry_missing_in_adp", None, None, None)

    # Entries exist but carry no breaks.
    if not breaks:
        entry_id = None
        return ("break_missing_in_adp", entry_id, None, None)

    selection = select_break([
        BreakCandidate(
            adp_entry_id=b.adp_entry_id,
            start_at=b.start_at,
            end_at=b.end_at,
            break_type_code=b.break_type_code,
            break_item_id=b.break_item_id,
        )
        for b in breaks
    ])

    if not selection.found:
        # Breaks exist but none has both bounds — nothing comparable.
        return ("break_missing_in_adp", None, None, None)

    candidate = selection.candidate

    if not selection.qualifying:
        flex_duration = flex.break_end_at - flex.break_start_at
        if flex_duration < MIN_QUALIFYING_BREAK:
            # Both systems agree the break was short. That is agreement, not a
            # disagreement — there is nothing for Flex to supply, and ADP already
            # reports it natively as a meal-break violation.
            return None
        return (
            "break_short_in_adp",
            candidate.adp_entry_id,
            candidate.start_at,
            candidate.end_at,
        )

    start_delta = abs(candidate.start_at - flex.break_start_at)
    end_delta = abs(candidate.end_at - flex.break_end_at)
    if start_delta > MISMATCH_TOLERANCE or end_delta > MISMATCH_TOLERANCE:
        return (
            "break_time_mismatch",
            candidate.adp_entry_id,
            candidate.start_at,
            candidate.end_at,
        )

    return None

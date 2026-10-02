"""Opening campaign runs on a schedule (ADR-485 D12).

Manual open is ALWAYS available and is not this file's business. A schedule is
a convenience; this is what makes it happen.

FOUR MODES, ALL BOUNDED
=======================

    daily          every dispatch day   window: to next shift_start   for 1 week
    weekly_fixed   a chosen weekday     window: 2 days                for 1 month
    weekly_random  a random day/week    window: 2 days                for 1 month
    monthly        once a month         window: 3 days                for 3 months

The windows are short on purpose: these ask someone to recall a specific shift,
and recall decays fast. A month-long window does not collect more data, it
collects vaguer data.

Every mode ends, so a campaign somebody set up and forgot stops asking on its
own. The failure that bounding introduces is the opposite one — it lapses and
nobody notices — so the end is announced (`_notify_schedule_ended`).

A SCHEDULED DAY WITH NO DISPATCH ROLLS OVER
===========================================

Opening a run on a day the station did not run produces an empty respondent
set: nobody notified, nobody able to answer, and a run sitting open collecting
nothing. On the results page that is indistinguishable from a survey everybody
ignored.

`daily` SKIPS such a day; every other mode PUSHES to the next day with a
dispatch. The difference is what gets lost: a daily schedule already has
tomorrow queued, so rolling Sunday onto Monday would collide with Monday's own
occurrence, while a monthly schedule losing its single occurrence means a month
with no data because of one holiday.
"""
from __future__ import annotations

import logging
import random
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from app.celery_app import celery_app
from app.database import SessionLocal
from app.models.campaign import Campaign, CampaignRun, CampaignSchedule
from app.models.employee import Employee
from app.models.notification import Notification
from app.models.truck_assignment import TruckAssignment
from app.services.audit import write_audit
from app.services.campaign_scope import (
    assignments_without_a_subject, respondents_for,
)
from app.services.company_config import get_company_config
from app.services.local_date import company_datetime, company_tz, task_today

logger = logging.getLogger(__name__)

# How far a pushed occurrence may search for a day with a dispatch. Bounded so
# a station that stops dispatching does not leave a schedule silently probing
# forward forever.
MAX_ROLL_DAYS = 14

# D12's windows, in days. `daily` is absent: its close is the next day's
# shift_start, which is computed rather than counted.
WINDOW_DAYS = {"weekly_fixed": 2, "weekly_random": 2, "monthly": 3}


def _has_dispatch(db, company_id: UUID, d: date) -> bool:
    return db.query(TruckAssignment.id).filter(
        TruckAssignment.company_id == company_id,
        TruckAssignment.date == d,
    ).first() is not None


def resolve_open_date(db, company_id: UUID, wanted: date, mode: str) -> date | None:
    """The first date from `wanted` onward that actually has a dispatch.

    `daily` does not search: a daily schedule already has tomorrow queued, so
    rolling a closed Sunday onto Monday would collide with Monday's own
    occurrence. The week simply yields fewer runs.
    """
    if mode == "daily":
        return wanted if _has_dispatch(db, company_id, wanted) else None

    for offset in range(MAX_ROLL_DAYS):
        d = wanted + timedelta(days=offset)
        if _has_dispatch(db, company_id, d):
            return d
    return None


def _due_today(schedule: CampaignSchedule, today: date) -> bool:
    """Is this schedule's occurrence due on `today`?

    `weekly_random` is resolved by `_random_day_for_week`, which is
    deterministic for a given (schedule, week) — a schedule that re-rolled on
    read would give two callers different answers.
    """
    if today < schedule.starts_on or today > schedule.ends_on:
        return False

    if schedule.mode == "daily":
        return True
    if schedule.mode == "weekly_fixed":
        return today.weekday() == schedule.weekday
    if schedule.mode == "weekly_random":
        return today == _random_day_for_week(schedule, today)
    if schedule.mode == "monthly":
        # The same day-of-month the schedule started on, clamped so the 31st
        # does not silently skip February.
        last = _last_day_of_month(today)
        return today.day == min(schedule.starts_on.day, last)
    return False


def _random_day_for_week(schedule: CampaignSchedule, today: date) -> date:
    """The day this week's occurrence falls on, chosen once and reproducibly.

    Seeded from the schedule id and the ISO week, so every call in a given week
    returns the same answer without storing it. Storing it would need a column
    that only this mode uses; deriving it means the "decided when the week
    begins" property holds even across a restart.
    """
    monday = today - timedelta(days=today.weekday())
    rng = random.Random(f"{schedule.id}:{monday.isoformat()}")
    return monday + timedelta(days=rng.randrange(7))


def _last_day_of_month(d: date) -> int:
    nxt = date(d.year + (d.month == 12), (d.month % 12) + 1, 1)
    return (nxt - timedelta(days=1)).day


def _close_at(db, company_id: UUID, run_date: date, mode: str, opened_at: datetime):
    """When this run stops accepting answers.

    `daily` closes at the NEXT day's shift_start in company time — a fixed,
    predictable instant that does not depend on tomorrow's dispatch existing
    yet, so a respondent can be shown a real countdown (D12).
    """
    tz = company_tz(db, company_id)
    cfg = get_company_config(db, company_id)

    if mode == "daily":
        if cfg is not None and cfg.shift_start is not None:
            closes = company_datetime(tz, run_date + timedelta(days=1), cfg.shift_start)
        else:
            closes = company_datetime(tz, run_date + timedelta(days=1),
                                      datetime.min.time())
    else:
        days = WINDOW_DAYS.get(mode, 2)
        at = cfg.shift_start if (cfg and cfg.shift_start) else datetime.min.time()
        closes = company_datetime(tz, run_date + timedelta(days=days), at)

    # A window that already closed is not a window. Only reachable when a
    # schedule fires late enough that its own close has passed.
    return closes if closes > opened_at else opened_at + timedelta(hours=12)


@celery_app.task(name="app.tasks.campaign_runs.open_scheduled_runs")
def open_scheduled_runs() -> dict:
    """Open every run due today, across every company.

    Idempotent per (campaign, date) by the DB's own unique constraint: a
    duplicate beat tick, or a retry, cannot produce two runs for one day.
    """
    db = SessionLocal()
    opened = skipped = ended = 0
    try:
        schedules = db.query(CampaignSchedule).all()
        for schedule in schedules:
            try:
                result = _process(db, schedule)
                opened += result["opened"]
                skipped += result["skipped"]
                ended += result["ended"]
            except Exception:
                # One company's bad data must not stop every other company's
                # campaigns from opening.
                db.rollback()
                logger.exception(
                    "campaign schedule %s failed to process", schedule.id)
        return {"opened": opened, "skipped": skipped, "ended": ended}
    finally:
        db.close()


def _process(db, schedule: CampaignSchedule) -> dict:
    out = {"opened": 0, "skipped": 0, "ended": 0}
    tz = company_tz(db, schedule.company_id)
    today = task_today(tz)

    if today > schedule.ends_on:
        if schedule.ended_notified_at is None:
            _notify_schedule_ended(db, schedule)
            out["ended"] = 1
        return out

    if not _due_today(schedule, today):
        return out

    run_date = resolve_open_date(db, schedule.company_id, today, schedule.mode)
    if run_date is None:
        # No dispatch within the horizon. Skipping silently is the failure this
        # whole section exists to prevent, so it is logged and counted.
        logger.info(
            "campaign schedule %s: no dispatch on or after %s within %d days; "
            "occurrence skipped", schedule.id, today, MAX_ROLL_DAYS)
        out["skipped"] = 1
        return out

    campaign = db.query(Campaign).filter(
        Campaign.id == schedule.campaign_id,
        Campaign.company_id == schedule.company_id,
    ).first()
    if campaign is None or campaign.status != "active":
        return out

    existing = db.query(CampaignRun.id).filter(
        CampaignRun.campaign_id == campaign.id,
        CampaignRun.company_id == schedule.company_id,
        CampaignRun.date == run_date,
    ).first()
    if existing is not None:
        return out

    now = datetime.now(timezone.utc)
    run = CampaignRun(
        company_id=schedule.company_id,
        campaign_id=campaign.id,
        date=run_date,
        opens_at=now,
        closes_at=_close_at(db, schedule.company_id, run_date, schedule.mode, now),
        schedule_id=schedule.id,
    )
    db.add(run)
    db.flush()

    respondents = respondents_for(db, run, campaign)
    if not respondents:
        # Nothing to collect. An open run that could never receive a response
        # is indistinguishable, on the results page, from one everybody
        # ignored (D16).
        db.rollback()
        logger.info("campaign schedule %s: nobody eligible on %s; not opened",
                    schedule.id, run_date)
        out["skipped"] = 1
        return out

    run.notified_count = len(respondents)
    run.skipped_assignment_ids = [
        str(a) for a in assignments_without_a_subject(db, run, campaign)
    ]

    write_audit(
        db=db,
        company_id=str(schedule.company_id),
        # No actor: a schedule opened this, not a person. actor_id is a FK to
        # employees and a scheduled action has none (ADR-274's shape).
        action_type="campaign.run_opened_by_schedule",
        target_table="campaign_runs",
        target_id=str(run.id),
        after={"campaign": campaign.label, "date": run_date.isoformat(),
               "mode": schedule.mode, "notified": len(respondents)},
    )
    db.commit()
    out["opened"] = 1
    return out


def _notify_schedule_ended(db, schedule: CampaignSchedule) -> None:
    """Tell the creator AND management that a schedule has finished (D12).

    Fired when the LAST run closes, not when it opens: the message can then
    carry what was collected, and prompting to renew while a run is still open
    invites two overlapping schedules for one campaign.

    To management as well as the creator, because `created_by` is
    ondelete="SET NULL" — the creator may have left, and a notice addressed
    only to a null actor is the lapse this exists to prevent.
    """
    campaign = db.query(Campaign).filter(
        Campaign.id == schedule.campaign_id,
        Campaign.company_id == schedule.company_id,
    ).first()
    if campaign is None:
        return

    run_count = db.query(CampaignRun.id).filter(
        CampaignRun.campaign_id == campaign.id,
        CampaignRun.company_id == schedule.company_id,
    ).count()

    recipients = {
        e.id for e in db.query(Employee).filter(
            Employee.company_id == schedule.company_id,
            Employee.role.in_(("management", "admin")),
            Employee.is_active.is_(True),
        ).all()
    }
    if schedule.created_by is not None:
        recipients.add(schedule.created_by)

    message = (
        f"{campaign.label} has finished its schedule — {run_count} run(s), "
        f"{schedule.starts_on.isoformat()} to {schedule.ends_on.isoformat()}. "
        f"Start another?"
    )
    for employee_id in recipients:
        db.add(Notification(
            company_id=schedule.company_id,
            employee_id=employee_id,
            type="campaign_schedule_ended",
            message=message,
        ))

    # One-way stamp: the notice is sent once, not on every tick for the rest of
    # the schedule's existence.
    schedule.ended_notified_at = datetime.now(timezone.utc)
    db.flush()
    write_audit(
        db=db,
        company_id=str(schedule.company_id),
        action_type="campaign.schedule_ended",
        target_table="campaign_schedules",
        target_id=str(schedule.id),
        after={"campaign": campaign.label, "runs": run_count,
               "notified": len(recipients)},
    )
    db.commit()

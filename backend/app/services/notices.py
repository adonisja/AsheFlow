"""Resolving a notice's anchor into a tenant-local instant (ADR-488 D3, D4).

THE PROBLEM THIS SOLVES
=======================

Four beat tasks notify people on a fixed SERVER hour. Measured:

    warn_before_mfa_deadline     16:30 server, NO tenant awareness at all
    remind_fuel_log_missing      17:00 + 18:30 server, tenant DATE only
    detect_timecard_mismatches   12:00 server, tenant DATE only
    alert_finalization_deadline  09:05 server (condition + cutoff already fixed)

So a West Coast employee was warned about their MFA deadline at 13:30 local, and
a tenant whose drivers return at 20:00 was reminded to file a fuel log three
hours before anyone could have filed one.

A notice does not declare WHEN it fires. It declares what tenant time it fires
RELATIVE TO, and the tenant's own config supplies the clock.

WHY A NULL ANCHOR SKIPS RATHER THAN FALLING BACK
================================================

All three config-backed anchors are `Column(Time, nullable=True)` with no
default. ADR-485's own idiom falls back to midnight:

    at = cfg.shift_start if (cfg and cfg.shift_start) else datetime.min.time()

which is right for opening a campaign run and WRONG for a notice: a fuel-log
reminder at 00:00 is noise delivered at the worst possible hour. ADR-482 supplies
the rule instead --

    a platform setting that never arrived must fail LOUDLY rather than silently
    blocking a tenant

-- so an unresolvable anchor is skipped, counted, and NAMED, and the sweep raises
a platform alert when any tenant is unservable. An unconfigured tenant becomes
visible rather than silently unserved, which is the ADR-480 parameter-drift
failure avoided in a new place.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models.notice import (
    CONFIG_BACKED_ANCHORS, Anchor, NoticeOrigin, NoticeSchedule, NoticeTemplate,
)
from app.services.local_date import company_datetime

logger = logging.getLogger(__name__)

#: A notice more than this late is skipped rather than fired. "File your fuel
#: log" at 02:00 because the worker was down since 18:00 is worse than silence.
#: The stamp still advances, so it does not retry at tomorrow's midnight either.
MAX_LATENESS = timedelta(hours=4)


@dataclass(frozen=True)
class Unservable:
    """A notice that cannot fire because its tenant has not configured the anchor.

    Carried rather than logged-and-forgotten so the sweep can report a count and
    name the column — "shift_end" tells an operator what to set; "a notice was
    skipped" sends them hunting.
    """

    company_id: str
    notice_id: str
    label: str
    anchor: str


def resolve_anchor(
    notice: NoticeTemplate,
    cfg,
    tz: ZoneInfo,
    on_date: date,
) -> datetime | None:
    """The notice's firing instant as a real UTC datetime, or None if unservable.

    `company_datetime` rather than `datetime.combine(...).replace(tzinfo=utc)`:
    the config columns are NAIVE and documented "read in the company's own
    timezone", so attaching UTC RELABELS them — 17:00 New York becomes 17:00
    UTC, four or five hours early depending on DST (ADR-486).
    """
    if notice.anchor == Anchor.LOCAL_MIDNIGHT:
        base = datetime.min.time()
    elif notice.anchor == Anchor.FIXED_LOCAL:
        # NOT NULL for this anchor by CheckConstraint, so a None here means the
        # constraint was bypassed (a raw INSERT, a bad migration) rather than a
        # tenant configuration gap — worth distinguishing in the log.
        base = notice.at_local
        if base is None:
            logger.error(
                "notice %s has anchor=fixed_local with no at_local; the "
                "ck_notice_fixed_local_needs_time constraint should have "
                "prevented this row", notice.id,
            )
            return None
    else:
        # The anchor's VALUE is the CompanyConfig column name (ADR-488 D3).
        base = getattr(cfg, str(notice.anchor), None) if cfg is not None else None
        if base is None:
            return None     # unservable: the tenant has not set it. See module docstring.

    return company_datetime(tz, on_date, base) + timedelta(minutes=notice.offset_minutes)


def is_due_today(schedule: NoticeSchedule, local_today: date) -> bool:
    """Does this schedule's recurrence include today, in the tenant's own date?

    The four modes are `CampaignSchedule`'s, deliberately — ADR-488 D2 reuses
    that vocabulary rather than inventing a second scheduler.

    `weekly_random` is NOT random per call: that would make a notice fire on a
    different day every time the sweep ran. It is seeded on the schedule id and
    the ISO week, so the chosen day is stable within a week and varies between
    weeks — which is what "random" means for a recurring reminder.
    """
    if local_today < schedule.starts_on:
        return False
    if schedule.ends_on is not None and local_today > schedule.ends_on:
        return False

    if schedule.mode == "daily":
        return True
    if schedule.mode == "weekly_fixed":
        return local_today.weekday() == schedule.weekday
    if schedule.mode == "monthly":
        return local_today.day == schedule.starts_on.day
    if schedule.mode == "weekly_random":
        iso_year, iso_week, _ = local_today.isocalendar()
        seed = hash((str(schedule.id), iso_year, iso_week))
        return local_today.weekday() == (seed % 7)
    logger.error("notice schedule %s has unknown mode %r", schedule.id, schedule.mode)
    return False


def pass_number_due(
    schedule: NoticeSchedule,
    fire_at: datetime,
    now: datetime,
) -> int | None:
    """Which pass (1-based) is due now, or None if none is.

    Firing is "the instant has PASSED and this pass has not fired", not "we are
    within 15 minutes of it". The difference matters on a worker restart: a
    window test silently drops any notice whose window elapsed while the worker
    was down, which is ADR-487 D3's lost-`.delay()` failure in a new place.
    `fired_count` makes late better than never — bounded by MAX_LATENESS.
    """
    already = schedule.fired_count or 0
    if already >= (schedule.max_fires_per_day or 1):
        return None

    # The Nth pass is offset by (N-1) * repeat_after_minutes from the anchor.
    gap = timedelta(minutes=schedule.repeat_after_minutes or 0)
    due_at = fire_at + gap * already

    if now < due_at:
        return None
    if now - due_at > MAX_LATENESS:
        logger.warning(
            "notice schedule %s pass %d is %s late; skipping rather than firing "
            "at the wrong hour", schedule.id, already + 1, now - due_at,
        )
        return None
    return already + 1


def tenant_notice_must_end(notice: NoticeTemplate, schedule: NoticeSchedule) -> bool:
    """ADR-488 D11, as a predicate the router and the seeder both call.

    A cross-table CHECK is not portable, so this rule cannot live in the schema
    the way the single-table constraints do. It is enforced here and pinned by a
    test, and the migration says so in a comment rather than leaving the absence
    to be discovered.

    Returns True when the pair VIOLATES the rule.
    """
    return (
        notice.origin == NoticeOrigin.TENANT.value
        and schedule.ends_on is None
    )

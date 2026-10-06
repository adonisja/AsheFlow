"""Fire every notice whose tenant-local anchor has passed (ADR-488 D6, D7).

WHY A SWEEP AND NOT A CRONTAB PER NOTICE
========================================

The alternative is mutating `beat_schedule` at runtime so each tenant gets its
own entry, which ADR-487 D4d rejected as the design to avoid. The lever for
finer resolution is this task's interval, not the beat config.

THE INTERVAL, COSTED RATHER THAN ASSERTED
=========================================

    resolve_pending_addresses   every 10 min   144 ticks/day   (already running)
    check_integration_health    every 10 min   144 ticks/day   (already running)
    ──
    this sweep                  every 15 min    96 ticks/day

Fewer ticks than the cheapest recurring task already in the schedule, and
`check_integration_health` makes THREE outbound HTTP calls per tick where this
makes zero. Per tick: two bulk reads and no per-tenant round trip.

And what it replaces is itself polling. The four tasks it supersedes fire five
times a day between them and each then scans every tenant anyway — so the
comparison is not "nothing vs a sweep", it is "five whole-table scans at times
that mean nothing to the tenant" vs "96 cheap checks that fire at the right
local moment".

WHY "THE INSTANT HAS PASSED" AND NOT "WE ARE INSIDE THE WINDOW"
===============================================================

A window test ("fired within the last 15 minutes") silently drops any notice
whose window elapsed while the worker was down — ADR-487 D3's lost-`.delay()`
failure in a new place. `fired_count` makes late better than never, bounded by
`MAX_LATENESS` so "file your fuel log" never arrives at 02:00.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.celery_app import celery_app
from app.database import SessionLocal
from app.models.company import CompanyConfig
from app.models.notice import NoticeSchedule, NoticeTemplate
from app.services.local_date import fetch_company_timezones, task_today
from app.services.notice_conditions import resolve_recipients
from app.services.notices import Unservable, is_due_today, pass_number_due, resolve_anchor
from app.services.notify import write_notification

logger = logging.getLogger(__name__)

#: The notification type every notice is raised as. One declared type for the
#: whole tier, because the LABEL and BODY come from the row — ADR-487 D4c's one
#: narrow exception to "every type is declared".
NOTICE_TYPE = "tenant_notice"


@celery_app.task(name="app.tasks.notice_sweep.fire_due_notices")
def fire_due_notices() -> dict:
    """Fire the notices whose tenant-local firing instant has arrived.

    Returns a summary rather than None so the result is inspectable in the
    worker log and in a test: `fired`, `skipped_not_due`, `unservable`, and the
    unservable anchors by name.
    """
    db = SessionLocal()
    fired = skipped = 0
    unservable: list[Unservable] = []
    try:
        now = datetime.now(timezone.utc)

        # Two bulk reads, no per-tenant round trip. `fetch_company_timezones`
        # documents this shape: "avoids N per-company DB lookups".
        tz_map = fetch_company_timezones(db)
        cfg_map = {
            c.company_id: c for c in db.query(CompanyConfig).all()
        }

        # Deliberately cross-tenant — this is a sweep over every company, and
        # each row is scoped by its OWN `schedule.company_id` downstream.
        #
        # The join predicate checks company_id on BOTH sides even though
        # notice_id is a foreign key. A join adds a second table, and filtering
        # one side does not scope the other (Dimension 1): a schedule whose
        # company_id disagreed with its template's would make the sweep read
        # tenant A's config and notify tenant A's employees with tenant B's
        # notice TEXT. The FK makes that hard to create and not impossible —
        # a bad backfill or a company merge would do it — and the cost of the
        # check is one indexed comparison.
        rows = (
            db.query(NoticeSchedule, NoticeTemplate)
            .join(
                NoticeTemplate,
                (NoticeSchedule.notice_id == NoticeTemplate.id)
                & (NoticeSchedule.company_id == NoticeTemplate.company_id),
            )
            .filter(NoticeTemplate.is_active.is_(True))
            .all()
        )

        for schedule, notice in rows:
            try:
                outcome = _process_one(
                    db, schedule, notice, tz_map, cfg_map, now,
                )
            except Exception:
                # One tenant's bad data must not stop every other tenant's
                # notices — `campaign_runs.open_scheduled_runs`'s own pattern
                # and its own reason.
                db.rollback()
                logger.exception("notice schedule %s failed to process", schedule.id)
                continue

            if outcome is None:
                skipped += 1
            elif isinstance(outcome, Unservable):
                unservable.append(outcome)
            else:
                fired += outcome

        db.commit()

        if unservable:
            _report_unservable(db, unservable)

        return {
            "fired": fired,
            "skipped_not_due": skipped,
            "unservable": len(unservable),
            # Named, not counted: "shift_end" tells an operator what to set,
            # where "a notice was skipped" sends them hunting.
            "unservable_anchors": sorted({u.anchor for u in unservable}),
        }
    finally:
        db.close()


def _process_one(db, schedule, notice, tz_map, cfg_map, now):
    """Fire one notice if due. Returns the recipient count, None, or Unservable."""
    tz = tz_map.get(schedule.company_id)
    if tz is None:
        logger.warning("notice %s: company %s has no timezone",
                       notice.id, schedule.company_id)
        return None

    local_today = task_today(tz)

    if not is_due_today(schedule, local_today):
        return None

    fire_at = resolve_anchor(notice, cfg_map.get(schedule.company_id), tz, local_today)
    if fire_at is None:
        # The tenant has not configured this anchor. Skip and REPORT — ADR-482's
        # rule: a platform setting that never arrived must fail loudly rather
        # than silently blocking a tenant.
        return Unservable(
            company_id=str(schedule.company_id), notice_id=str(notice.id),
            label=notice.label, anchor=str(notice.anchor),
        )

    # A new local day resets the per-day counter before the pass check reads it.
    if schedule.fired_on != local_today:
        schedule.fired_on = local_today
        schedule.fired_count = 0

    which_pass = pass_number_due(schedule, fire_at, now)
    if which_pass is None:
        return None

    recipients, context = resolve_recipients(
        db, schedule.company_id, notice, local_today,
    )
    if not recipients:
        # The condition is not met — the tenant finalised everything, every
        # driver filed. Stamping the pass anyway would be wrong: the condition
        # may still become true before the next pass, which is exactly what the
        # second fuel-log pass exists for.
        return None

    body = _render(notice.body, context)
    for emp in recipients:
        write_notification(
            db,
            company_id=schedule.company_id,
            employee_id=emp.id,
            type=NOTICE_TYPE,
            message=body,
        )

    schedule.fired_count = which_pass
    logger.info(
        "notice %s (%s) pass %d fired to %d recipient(s) for company %s",
        notice.id, notice.seed_key or "tenant", which_pass,
        len(recipients), schedule.company_id,
    )
    return len(recipients)


def _render(body: str, context: dict) -> str:
    """Interpolate the condition's context into the body.

    `str.format_map` with a defaulting dict rather than `.format(**context)`: a
    body containing a placeholder the condition does not supply would raise
    KeyError inside a Celery task, where the traceback is a log line nobody
    reads. An unfilled placeholder renders as itself instead, which is visible
    and harmless.
    """
    if not context:
        return body

    class _Defaulting(dict):
        def __missing__(self, key):
            logger.warning("notice body references unknown placeholder %r", key)
            return "{" + key + "}"

    try:
        return body.format_map(_Defaulting(context))
    except Exception:
        # A malformed body (an unbalanced brace) must not lose the notice.
        logger.exception("could not render notice body; sending it verbatim")
        return body


def _report_unservable(db, unservable: list[Unservable]) -> None:
    """Raise one platform alert naming the anchors no tenant has configured.

    One alert for the sweep, not one per notice: twelve unconfigured notices at
    one tenant is one configuration problem, and twelve alerts would bury it.
    `raise_platform_alert` dedups on the open incident, so a tenant that stays
    unconfigured accumulates `occurrence_count` rather than rows.
    """
    from app.services.integration_alerts import raise_platform_alert

    by_company: dict[str, set[str]] = {}
    for u in unservable:
        by_company.setdefault(u.company_id, set()).add(u.anchor)

    for company_id, anchors in by_company.items():
        try:
            raise_platform_alert(
                db,
                alert_type="notice_anchor_unconfigured",
                company_id=company_id,
                message=(
                    "Scheduled reminders cannot fire for this company: "
                    + ", ".join(sorted(anchors))
                    + " is not set in company settings. The reminders are "
                    "skipped until it is."
                ),
                severity="warning",
            )
        except Exception:
            logger.exception("could not report unservable notices for %s", company_id)
    db.commit()

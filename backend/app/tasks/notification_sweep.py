"""The safety net for a lost enqueue (ADR-487 D3).

WHY A SWEEP AT ALL
==================

`after_commit` hands each delivery to Celery with `.delay()`. That call can be
lost — a broker restart, a worker killed between the commit and the enqueue, a
network blip to Redis. The notification row is committed either way, so the
symptom is a row that was supposed to produce a push or a Discord post and
produced nothing, with no error anywhere.

`celery_app.py`'s beat schedule opens with exactly this shape and states the
rule in its own comment:

    Every 10 min — sweeps BuildingProfiles left `pending` by a submit whose
    .delay() dispatch was lost (broker restart, worker down). The submit path
    queues resolution immediately (ADR-277 D1); this is the safety net, not
    the mechanism, so the interval only bounds how long a dropped dispatch
    stays invisible.

Same here. The interval bounds how long an undelivered URGENT push stays
invisible, which is the failure this whole ADR exists to prevent.

WHAT IT LOOKS FOR, AND WHY `dispatched_at IS NULL` IS NOT ENOUGH ALONE
======================================================================

A row with no `dispatched_at` is either lost or two seconds old. The age filter
is what separates them, and it has to exceed the retry window: a task that is
mid-backoff has not been delivered yet and has not been lost, and re-enqueueing
it would duplicate the message a person reads.

D3's policy is `retry_backoff=2` with `max_retries=5`, so the worst case is
2+4+8+16+32 = 62 seconds of backoff plus five request timeouts of 10s each.
`_MIN_AGE` is comfortably past that.

ROWS THAT WERE NEVER MEANT TO BE DISPATCHED
===========================================

A BANNER-only type is delivered by being read — there is no send. `_record_intent`
already declines to record an intent for those, so they never get a
`dispatched_at` and would look lost forever. The sweep therefore re-derives the
channel set from the registry and skips anything with nothing to send, rather
than trusting a column that was deliberately never written.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from app.celery_app import celery_app
from app.database import SessionLocal
from app.models.notification import Notification
from app.services.notification_spec import Channel, resolve_spec

logger = logging.getLogger(__name__)

# Older than the full retry window (62s of backoff + 5 timeouts of 10s) with
# room to spare, so a task that is merely mid-retry is never re-enqueued.
_MIN_AGE = timedelta(minutes=10)

# Rows older than this are not worth chasing: the message is stale, the shift is
# over, and re-sending "confirm your assignment for Tuesday" on Thursday is
# worse than not sending it. They are logged so the gap is countable.
_MAX_AGE = timedelta(hours=24)

# One sweep must not become a thundering herd of its own.
_BATCH = 200


@celery_app.task(name="app.tasks.notification_sweep.resweep_undelivered")
def resweep_undelivered() -> dict:
    """Re-enqueue deliveries whose `.delay()` was lost.

    Idempotent by `dispatched_at`: a row stamped by a successful send is not
    picked up again, and the stamp is written by the delivery task rather than
    here, so a re-enqueue that also fails simply gets swept again.
    """
    db = SessionLocal()
    now = datetime.now(timezone.utc)
    requeued = skipped_no_channel = abandoned = 0
    try:
        candidates = (
            db.query(Notification)
            .filter(
                Notification.dispatched_at.is_(None),
                Notification.delivery_failed_at.is_(None),
                Notification.created_at < now - _MIN_AGE,
                # A held push is not lost — D5 releases it when its time comes.
                Notification.release_at.is_(None),
            )
            .order_by(Notification.created_at.asc())
            .limit(_BATCH)
            .all()
        )

        for n in candidates:
            try:
                spec = resolve_spec(n.type)
            except Exception:
                # An undeclared type cannot be routed. resolve_spec refusing is
                # correct; a sweep that raises on one bad row and abandons the
                # rest is not.
                logger.warning("sweep: notification %s has an undeclared type %r",
                               n.id, n.type)
                continue

            if not (spec.channels & (Channel.PUSH | Channel.DISCORD)):
                # Never had anything to send. Stamp it so the sweep stops
                # re-reading it every ten minutes forever.
                n.dispatched_at = now
                skipped_no_channel += 1
                continue

            if n.created_at < now - _MAX_AGE:
                n.delivery_failed_at = now
                n.delivery_error = "sweep:too_old_to_resend"
                abandoned += 1
                logger.warning(
                    "sweep: abandoning notification %s (type=%s) — created %s, "
                    "past the %sh resend horizon",
                    n.id, n.type, n.created_at, int(_MAX_AGE.total_seconds() // 3600),
                )
                continue

            _requeue(db, n, spec)
            requeued += 1

        db.commit()
        if requeued or abandoned:
            logger.warning(
                "notification sweep: %d re-enqueued, %d abandoned, %d had no "
                "channel", requeued, abandoned, skipped_no_channel,
            )
        return {
            "requeued": requeued,
            "abandoned": abandoned,
            "no_channel": skipped_no_channel,
        }
    finally:
        db.close()


@celery_app.task(name="app.tasks.notification_sweep.release_held_pushes")
def release_held_pushes() -> dict:
    """Send pushes whose quiet-hours hold has expired (ADR-487 D5).

    `resweep_undelivered` above deliberately EXCLUDES held rows
    (`release_at.is_(None)`) with the comment *"a held push is not lost -- D5
    releases it when its time comes."* This is the thing that does that. Without
    it the exclusion is a leak: a push stamped at 02:00 would be skipped by the
    resweep forever and sent by nothing.

    IDEMPOTENT, in the direction that matters. `send_push` clears `release_at`
    once it has delivered, so a row only appears here while it is still held. A
    run that overlaps the previous one re-enqueues the same row, and the second
    send is a duplicate push rather than a lost one -- the safe direction, and
    the client de-duplicates on `notification_id`.

    NO AGE HORIZON, unlike the resweep. A held push is held on purpose, and the
    longest possible hold is one night -- `release_at` is always today's or
    tomorrow's `shift_start`, never further out. A row whose release is more
    than a day past is a defect worth seeing rather than a stale message worth
    abandoning, so it is logged and still sent.
    """
    from app.tasks.push_delivery_task import send_push

    db = SessionLocal()
    now = datetime.now(timezone.utc)
    released = 0
    try:
        due = (
            db.query(Notification)
            .filter(
                Notification.release_at.isnot(None),
                Notification.release_at <= now,
                Notification.delivery_failed_at.is_(None),
            )
            .order_by(Notification.release_at.asc())
            .limit(_BATCH)
            .all()
        )

        for n in due:
            overdue = now - n.release_at
            if overdue > timedelta(days=1):
                # A hold is at most one night. Longer means something stopped
                # running, and silence about it is how it keeps not running.
                logger.warning(
                    "push: notification %s was held until %s, %s overdue — the "
                    "release sweep may have been down",
                    n.id, n.release_at.isoformat(), overdue,
                )
            send_push.delay(str(n.id))
            released += 1

        if released:
            logger.info("push release sweep: %d held push(es) re-enqueued", released)
        return {"released": released}
    finally:
        db.close()


def _requeue(db, n: Notification, spec) -> None:
    """Hand a lost delivery back to the delivery task.

    Deliberately NOT routed through `_enqueue` in `services.notify`: that one
    takes a `_Dispatch` built pre-commit from live ORM objects, and this one has
    a persisted row. Sharing the function would mean reconstructing a private
    dataclass from a row to satisfy a signature — the duplication here is four
    lines and the coupling it avoids is worse.
    """
    if Channel.DISCORD not in spec.channels:
        return

    # The bot's contract is {"discord_id", "message"} — it 400s on anything
    # else. Here the lookup IS legal (a task, not an after_commit hook), so the
    # sweep resolves it rather than carrying it.
    from app.models.employee import Employee

    discord_id = (
        db.query(Employee.discord_id)
        .filter(Employee.id == n.employee_id,
                Employee.company_id == n.company_id)
        .scalar()
    )
    if not discord_id:
        # Unlinked. Stamp it so the sweep stops re-reading a row it can never
        # deliver — the in-app notification is the channel of record (ADR-324).
        n.dispatched_at = datetime.now(timezone.utc)
        return

    from app.tasks.discord_delivery import send_discord

    send_discord.delay(
        "dm",
        {"discord_id": discord_id, "message": n.message},
        notification_id=str(n.id),
        company_id=str(n.company_id),
    )

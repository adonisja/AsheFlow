"""Send one notification's push, after the commit (ADR-487 D5).

WHY A TASK AND NOT AN INLINE SEND
=================================
ADR-324 found both halves of getting this wrong: a Discord call placed BEFORE
the commit took out the in-app notifications created downstream of it, and an
alert committed WITH the main transaction was discarded when an unrelated
helper called `db.rollback()`. So delivery happens on `after_commit`, and
`after_commit` must not emit SQL -- which means the work goes to a task.

WHAT A HELD PUSH IS
===================
Not a sleeping task. ADR-487 D5 is explicit: a Celery `countdown=` of six hours
holds the task in the broker and a broker restart loses it. So a push that must
wait for the shift to start is NOT enqueued with a delay -- the quiet-hours
check happens HERE, at send time, and a held push simply returns without
sending. The 15-minute notice sweep (ADR-488 D4d) picks it up once
`release_at` has passed.

That makes this task idempotent-by-design: running it during quiet hours is a
no-op that leaves the row for the sweep, and running it twice after release
sends twice to a device that de-duplicates on `notification_id`.

EVERY FAILURE IS SWALLOWED
==========================
Push is additive -- everyone receives every notification in-app regardless.
A push that cannot be sent must never fail the notification it was announcing,
so this classifies and logs rather than raising. The one exception is a
transient AWS error, which retries.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from botocore.exceptions import BotoCoreError

from app.celery_app import celery_app
from app.database import SessionLocal
from app.models.notification import Notification
from app.services.notification_spec import Severity, resolve_spec
from app.models.device_token import DevicePlatform, DeviceToken
from app.services.push_delivery import (
    create_endpoint, live_devices, push_enabled, send_to_device,
)
from app.services.push_quiet_hours import describe, release_at

logger = logging.getLogger(__name__)


@celery_app.task(
    name="app.tasks.push_delivery_task.send_push",
    bind=True,
    # Only transient AWS transport errors retry. A ClientError is handled
    # inside send_to_device, which classifies EndpointDisabled as "revoke the
    # device" rather than "try again" -- retrying that would just re-confirm a
    # deleted app five times.
    autoretry_for=(BotoCoreError,),
    retry_backoff=2,
    retry_backoff_max=300,
    # Not optional: 25 types carry PUSH and several are fan-outs, so one event
    # produces N sends. Without jitter a transient SNS blip retries all of them
    # on the same schedule (the ADR-487 D3 reasoning, same shape).
    retry_jitter=True,
    max_retries=5,
    acks_late=True,
)
def send_push(self, notification_id: str) -> dict:
    """Push one notification to every live device of its recipient.

    Takes only the notification id and re-reads the row, deliberately: the
    after-commit hook must not pass a detached ORM object into a task, and the
    severity and message must be the committed values rather than whatever was
    in memory when the intent was recorded.
    """
    db = SessionLocal()
    try:
        notif = (
            db.query(Notification)
            .filter(Notification.id == notification_id)
            .first()
        )
        if notif is None:
            # The row was deleted between commit and send -- a 3-day prune on a
            # very old queue, or a cleared dispatch. Not an error.
            return {"skipped": "notification_gone"}

        if not push_enabled():
            return {"skipped": "push_not_configured"}

        try:
            spec = resolve_spec(notif.type)
        except Exception:
            # An undeclared type reaching here is a defect worth seeing, but
            # not one worth failing a push over.
            logger.warning(
                "push: notification %s has undeclared type %r; not pushing",
                notification_id, notif.type,
            )
            return {"skipped": "undeclared_type"}

        release = release_at(db, notif.company_id, spec.severity)
        if release is not None:
            # Quiet hours. STAMP the row and return -- the stamp is what makes
            # the hold survivable. Returning without it would leave nothing for
            # the sweep to find, so the push would simply never arrive, which is
            # the silent non-delivery D5 set out to avoid.
            #
            # `Notification.release_at` already exists for this and its own
            # comment says so: "a Celery countdown= of six hours lives in the
            # broker and dies with it. A row survives."
            notif.release_at = release
            db.commit()
            logger.info(
                "push: notification %s (%s/%s) %s",
                notification_id, notif.type, spec.severity.value, describe(release),
            )
            return {"skipped": "quiet_hours", "release_at": release.isoformat()}

        devices = live_devices(db, notif.company_id, notif.employee_id)
        if not devices:
            # No registered device. The common case today and for every web-only
            # user, so debug rather than warning.
            logger.debug(
                "push: employee %s has no live device for notification %s",
                notif.employee_id, notification_id,
            )
            return {"skipped": "no_devices"}

        sent = failed = 0
        for device in devices:
            # ADR-508 D3: the registry icon leads the title; the body no longer
            # carries its own emoji.
            title = f"{spec.icon} {spec.label}" if spec.icon else spec.label
            if send_to_device(db, device, title=title, body=notif.message,
                              data={"notification_id": str(notif.id), "type": notif.type}):
                device.last_seen_at = datetime.now(timezone.utc)
                sent += 1
            else:
                failed += 1

        # Clear the hold now that it has been honoured. Without this the sweep
        # would keep finding a row whose release_at is in the past and push it
        # again every 15 minutes -- the stamp is a QUEUE, not a record.
        notif.release_at = None

        # send_to_device may have revoked a device, and last_seen_at moved.
        db.commit()

        logger.info(
            "push: notification %s -> %d sent, %d failed (%d device(s))",
            notification_id, sent, failed, len(devices),
        )
        return {"sent": sent, "failed": failed, "devices": len(devices)}
    except BotoCoreError:
        db.rollback()
        raise                      # autoretry_for handles it
    except Exception as e:
        db.rollback()
        # type(e).__name__ only: push payloads carry a device token, which is a
        # credential for delivering this person's notifications.
        logger.error(
            "push: send_push failed for notification %s: %s",
            notification_id, type(e).__name__,
        )
        return {"error": type(e).__name__}
    finally:
        db.close()


#: How many devices one backfill run will try. A backlog (every device registered
#: before the ARN existed) drains over several hourly runs rather than one run
#: holding a session open across thousands of SNS calls.
_BACKFILL_BATCH = 200

#: Consecutive refusals that end a run (ADR-500 D2). One is a bad token; three in a
#: row is the platform -- IAM, the FCM credential, or the ARN -- and every further
#: call would only add a warning on top of the one that explains it.
_BACKFILL_STOP_AFTER = 3


@celery_app.task(name="app.tasks.push_delivery_task.backfill_endpoints")
def backfill_endpoints() -> dict:
    """Give live devices with no SNS endpoint one (ADR-500).

    Registration succeeds without an endpoint by design (push is additive), so a
    NULL `endpoint_arn` is normal after any of: the platform ARN being set after
    devices registered, an IAM or credential fault during registration, or a
    transient SNS error. Re-registration on app launch repairs it, but only for
    people who open the app, and the walker with the phone in a van cradle is
    the one push exists for.

    Spans companies like every platform sweep (ADR-500 D4): each write touches
    only that row's own endpoint, so nothing crosses a tenant.

    Writes no audit row (ADR-500 D3): it repairs a delivery address and records
    no one's action. The returned counts are the operator's record.
    """
    enabled = [p for p in (DevicePlatform.ANDROID, DevicePlatform.IOS) if push_enabled(p)]
    if not enabled:
        return {"skipped": "push_not_configured"}

    db = SessionLocal()
    created = failed = consecutive = 0
    stopped = False
    try:
        pending = (
            db.query(DeviceToken)
            .filter(
                DeviceToken.endpoint_arn.is_(None),
                DeviceToken.revoked_at.is_(None),
                DeviceToken.platform.in_([p.value for p in enabled]),
            )
            # Most recently seen first: a bounded batch should spend its calls on
            # people who actually use the app.
            .order_by(DeviceToken.last_seen_at.desc())
            .limit(_BACKFILL_BATCH)
            .all()
        )

        for device in pending:
            arn = create_endpoint(device)      # never raises; logs its own failure
            if arn:
                device.endpoint_arn = arn
                created += 1
                consecutive = 0
                continue
            failed += 1
            consecutive += 1
            if consecutive >= _BACKFILL_STOP_AFTER:
                stopped = True
                logger.warning(
                    "push backfill: stopped after %d consecutive refusals; this is a "
                    "platform-level problem (IAM, credential or ARN), not a per-device "
                    "one. %d created before stopping.",
                    consecutive, created,
                )
                break

        db.commit()

        remaining = (
            db.query(DeviceToken.id)
            .filter(
                DeviceToken.endpoint_arn.is_(None),
                DeviceToken.revoked_at.is_(None),
                DeviceToken.platform.in_([p.value for p in enabled]),
            )
            .count()
        )
        if created or failed:
            logger.info(
                "push backfill: %d created, %d failed, %d still without an endpoint",
                created, failed, remaining,
            )
        return {"created": created, "failed": failed,
                "remaining": remaining, "stopped": stopped}
    except Exception as e:
        db.rollback()
        logger.error("push backfill failed: %s", type(e).__name__)
        return {"error": type(e).__name__}
    finally:
        db.close()

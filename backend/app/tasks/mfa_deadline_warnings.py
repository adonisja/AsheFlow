"""Warn a field employee before their MFA grace period closes (ADR-470 D1).

ADR-377 gives field roles 14 days to enrol; ADR-465 makes the wall unskippable
once that window shuts. Between those two decisions the countdown is rendered
ONLY inside the app -- a nudge banner on web, a skippable modal on mobile.

Field staff are not in the app. Their work arrives through Discord, no mobile
app has shipped, and the clock only starts when they first open a client
(`employees.py`, the mfa-status handler). Measured while writing ADR-470: ZERO
of 16 field employees had a started clock. So the warning that exists is
delivered to an empty room, and the first thing they would learn about the
deadline is the wall itself, at 05:00, at a depot.

This sweep moves the warning to the channel they actually read.

WHAT THIS IS NOT. It does not block, extend, or forgive anything -- enforcement
stays exactly where ADR-465 put it. A walker who ignores both DMs still meets
the wall on day 14. The difference is that it follows a warning instead of
replacing one.
"""
import logging
import os
from datetime import datetime, timedelta, timezone

import requests as http_requests

from app.celery_app import celery_app
from app.database import SessionLocal
from app.models.employee import Employee
from app.models.notification import Notification
from app.services import mfa_status

logger = logging.getLogger(__name__)

# The bands, in days remaining. Two, not five: a deadline warned about daily is
# a deadline nobody reads. 3 gives a weekend to act, 1 is the last call.
#
# Each band carries its own notification `type`, which is what makes the send
# idempotent -- a re-run on the same day finds the row and skips (the
# integration_alerts pattern). A single shared type would let the 1-day warning
# be swallowed by the 3-day one.
BANDS = {
    3: "mfa_deadline_3d",
    1: "mfa_deadline_1d",
}

_MESSAGE = (
    "Heads up: you have {days} to set up two-factor authentication on AsheFlow. "
    "After that you will not be able to use the app until it is done, so it is "
    "worth doing before your next shift rather than at the start of one. "
    "Open AsheFlow and follow the prompt -- you will need an authenticator app "
    "such as Google Authenticator, 1Password or Authy."
)


def _send_dm(discord_id: str, message: str) -> bool:
    """Synchronous, unlike the routers' fire-and-forget `_fire_discord_dm`.

    A request handler cannot wait on Discord and has a user watching, so it
    threads the call and forgets. A task has neither constraint and has the
    opposite need: it must know what was actually delivered, because the whole
    point is that the warning reached them. Returns success rather than raising
    so one unreachable recipient cannot end the sweep for everyone else.
    """
    bot_url = os.environ.get("BOT_INTERNAL_URL", "http://bot:8001")
    secret = os.environ.get("INTERNAL_SECRET", "")
    try:
        resp = http_requests.post(
            f"{bot_url}/internal/dm",
            json={"discord_id": discord_id, "message": message},
            headers={"X-Internal-Secret": secret},
            timeout=5,
        )
        resp.raise_for_status()
        return True
    except Exception as exc:
        # Type only -- never the body, which can echo back identifiers.
        logger.warning("mfa deadline DM failed: %s", type(exc).__name__)
        return False


@celery_app.task(name="app.tasks.mfa_deadline_warnings.warn_before_mfa_deadline")
def warn_before_mfa_deadline() -> dict:
    """DM field employees at 3 and 1 days remaining. Daily.

    Cheap by construction. `days_remaining` derives entirely from
    `mfa_grace_started_at`, a DB column -- no Cognito call -- so the SQL narrows
    to the handful of rows inside a warning band before anything else runs. A
    clock that has never started is a full window and `blocked=False`, so those
    rows are excluded by the NOT NULL term rather than evaluated and discarded.

    Only that shortlist is checked against Cognito, and only to avoid nagging
    somebody who has already enrolled.
    """
    now = datetime.now(timezone.utc)
    grace = mfa_status.DEFAULT_MFA_GRACE_DAYS

    sent = 0
    skipped_enrolled = 0
    skipped_already_warned = 0
    no_discord = 0
    dm_failures = 0

    db = SessionLocal()
    try:
        # Widest band first: everything with a clock running that is at or
        # inside the largest warning threshold, and not yet past the deadline.
        widest = max(BANDS)
        window_opens = now - timedelta(days=grace - widest)
        deadline_at = now - timedelta(days=grace)

        candidates = (
            db.query(Employee)
            .filter(
                Employee.is_active == True,  # noqa: E712
                Employee.mfa_grace_started_at.isnot(None),
                # Inside the warning window ...
                Employee.mfa_grace_started_at <= window_opens,
                # ... and not already past the deadline. Someone past it is
                # blocked NOW and is looking at the wall; a DM telling them to
                # act "before your next shift" would be both late and wrong.
                Employee.mfa_grace_started_at > deadline_at,
            )
            .all()
        )

        for emp in candidates:
            # Role, not group: this task has no token to read groups from.
            if mfa_status.tier_for(emp.role, {emp.role}) != "field":
                # Privileged roles have no grace at all (ADR-377) -- their path
                # is ADR-465's wall from the first sign-in, not a countdown.
                continue

            status = mfa_status.evaluate(
                role=emp.role,
                enrolled=False,          # provisional; confirmed below
                grace_started_at=emp.mfa_grace_started_at,
                grace_days=grace,
                groups={emp.role},
            )
            remaining = status.days_remaining
            if remaining is None:
                continue

            band = next((d for d in sorted(BANDS) if remaining <= d), None)
            if band is None:
                continue

            notif_type = BANDS[band]

            # Idempotent per band per employee. No new column: the notification
            # row IS the record that this band was sent, which is the
            # integration_alerts pattern. Not filtered on is_read -- a warning
            # they read is still a warning they were sent.
            already = (
                db.query(Notification)
                .filter(
                    Notification.company_id == emp.company_id,
                    Notification.employee_id == emp.id,
                    Notification.type == notif_type,
                )
                .first()
            )
            if already is not None:
                skipped_already_warned += 1
                continue

            # Cognito, only for the shortlist. None means "could not read" and
            # is treated as NOT enrolled here -- the opposite of the gating
            # rule, and deliberately so: the cost of a needless warning is mild
            # annoyance, where the cost of a missed one is a walker stopped at
            # 05:00. ADR-377's fail-open protects access, not inboxes.
            enrolled = mfa_status.is_enrolled(emp.cognito_sub, emp.username)
            if enrolled is True:
                skipped_enrolled += 1
                continue

            human = "1 day" if band == 1 else f"{band} days"
            message = _MESSAGE.format(days=human)

            # The in-app notification is written whether or not Discord is
            # reachable: it is the durable record, and the DM is the delivery.
            # Writing it only on a successful send would make a bot outage look
            # like a warning that never happened.
            db.add(Notification(
                company_id=emp.company_id,
                employee_id=emp.id,
                type=notif_type,
                message=message,
            ))
            sent += 1

            if emp.discord_id:
                if not _send_dm(emp.discord_id, message):
                    dm_failures += 1
            else:
                no_discord += 1

        db.commit()
    except Exception as exc:
        logger.error("warn_before_mfa_deadline failed: %s", type(exc).__name__)
        db.rollback()
        raise
    finally:
        db.close()

    result = {
        "warned": sent,
        "skipped_enrolled": skipped_enrolled,
        "skipped_already_warned": skipped_already_warned,
        "no_discord_id": no_discord,
        "dm_failures": dm_failures,
    }
    logger.info("warn_before_mfa_deadline: %s", result)
    return result

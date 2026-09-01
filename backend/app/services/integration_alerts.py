"""Tell an admin when an external integration is down (ADR-323).

Written after a revoked Discord bot token crash-looped the bot for weeks and
nobody was told. The failure WAS logged at every call site and never escalated,
so the only reason it surfaced was a dispatcher happening to hit the one
endpoint that fails loudly rather than degrading.

The lesson this module encodes: "the request should still succeed" and "nobody
should know the integration is down" are different claims. Degrading gracefully
is about the caller; alerting is about the operator. Keeping them separate means
a path can do both.
"""
import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.employee import Employee
from app.models.notification import Notification
from app.models.platform_alert import PlatformAlert

logger = logging.getLogger(__name__)

DISCORD_INTEGRATION_FAILED = "discord_integration_failed"

# ADR-336 D1/D2 — the other two PLATFORM-credential integrations. One type per
# integration, not per call site (D5): the dedup key is (alert_type, company_id),
# so a broad type collapses an outage into one incident instead of fragmenting it
# across every place that noticed.
EMAIL_DELIVERY_FAILED = "email_delivery_failed"
IDENTITY_REVOCATION_FAILED = "identity_revocation_failed"

# ADR-344 D5 — not an integration, but the same shape: a platform-wide
# condition only a super admin can act on, and one nobody sees unless it is
# surfaced. A cron job logging to a file is how the previous backup gap went
# unnoticed for the life of the deployment.
BACKUP_FAILED = "backup_failed"

# Says what is now untrue — the recovery point is stale — rather than naming the
# step that failed. "pg_dump exited 1" does not tell an operator what is at risk.
BACKUP_FAILED_MESSAGE = (
    "The nightly database backup did not complete. Recovery is only possible "
    "back to the last successful backup, so any data written since then is "
    "unprotected until this is fixed."
)

EMAIL_DOWN_MESSAGE = (
    "Outbound email is failing (AWS SES). Registration credentials, invites and "
    "password resets are not reaching recipients until it is restored."
)
# Deliberately says WHAT IS NOW UNTRUE rather than just what failed: an
# offboarded employee retaining access is the fact an operator must act on.
IDENTITY_REVOCATION_MESSAGE = (
    "Cognito access revocation failed. One or more offboarded employees may "
    "still be able to sign in — verify in the Cognito console and disable them "
    "manually."
)

# Names the blast radius, not the endpoint that happened to fail. "The bot is
# down" understates it — every Discord surface stops working at once, and an
# admin sizing the outage from one endpoint's name would under-react.
DISCORD_DOWN_MESSAGE = (
    "Discord messages are not being delivered — the bot could not be reached. "
    "Dispatch posts, crew finalisation and DMs are affected until it is restored."
)


def raise_platform_alert(
    db: Session,
    *,
    alert_type: str = DISCORD_INTEGRATION_FAILED,
    company_id: UUID | None = None,
    message: str = DISCORD_DOWN_MESSAGE,
    severity: str = "warning",
) -> None:
    """Record an infrastructure condition only a super admin can fix (ADR-335).

    Company admins get a Notification (ADR-323); they must know their crews are
    on in-app only. But they cannot rotate a Discord bot token — that is
    platform infrastructure — and a super admin has no Employee row, so a
    Notification cannot reach them at all (`get_super_admin`, deps.py:247).

    ADR-335 D2 — deduped on the OPEN INCIDENT, not on a reader or a time window.
    ADR-323 D4 deduped a Notification on `is_read`, which is right for an inbox:
    an admin already acting on it should not be re-alerted. A platform alert is
    a CONDITION that closes when the integration answers again, so the key is
    "is there an unresolved alert of this type for this tenant".

    `occurrence_count` and `last_seen_at` exist because "first seen 09:12, 47
    occurrences, still failing" is a materially different operational picture
    from "an alert exists", and the two are indistinguishable without them.

    Never raises — this runs on paths that are ALREADY handling a failure.
    """
    try:
        now = datetime.now(timezone.utc)
        q = db.query(PlatformAlert).filter(
            PlatformAlert.alert_type == alert_type,
            PlatformAlert.is_resolved.is_(False),
        )
        # `== None` does not match NULL in SQL; a platform-wide alert must dedup
        # against other platform-wide alerts, so the null case needs `is_()`.
        q = q.filter(PlatformAlert.company_id.is_(None)) if company_id is None \
            else q.filter(PlatformAlert.company_id == company_id)

        existing = q.first()
        if existing is not None:
            existing.occurrence_count += 1
            existing.last_seen_at = now
            return

        db.add(PlatformAlert(
            alert_type=alert_type,
            company_id=company_id,
            message=message,
            severity=severity,
        ))
        logger.warning(
            "platform alert raised: type=%s company=%s", alert_type, company_id,
        )
    except Exception:
        logger.exception("could not raise platform alert type=%s", alert_type)


def clear_integration_alert(
    db: Session,
    *,
    alert_type: str = DISCORD_INTEGRATION_FAILED,
    company_id: UUID | None = None,
) -> int:
    """Close any open alert of this type — the integration answered (ADR-335 D3).

    The natural close for a condition is "it started working again", not
    "someone clicked". A platform alert that only a human can close is stale
    within a day, and a stale incident board teaches its reader to distrust it.

    `resolved_by_sub` stays NULL: nobody resolved this, the condition ended.
    Returns the number closed. Never raises.
    """
    try:
        now = datetime.now(timezone.utc)
        q = db.query(PlatformAlert).filter(
            PlatformAlert.alert_type == alert_type,
            PlatformAlert.is_resolved.is_(False),
        )
        q = q.filter(PlatformAlert.company_id.is_(None)) if company_id is None \
            else q.filter(PlatformAlert.company_id == company_id)

        closed = 0
        for row in q.all():
            row.is_resolved = True
            row.resolved_at = now
            closed += 1
        if closed:
            logger.info(
                "platform alert auto-resolved: type=%s company=%s count=%d",
                alert_type, company_id, closed,
            )
        return closed
    except Exception:
        logger.exception("could not clear platform alert type=%s", alert_type)
        return 0


def alert_admins_integration_down(
    db: Session,
    company_id: UUID,
    *,
    notif_type: str = DISCORD_INTEGRATION_FAILED,
    message: str = DISCORD_DOWN_MESSAGE,
) -> int:
    """Notify this company's active admins that an integration is unreachable.

    Adds to the session; the caller commits. Returns the number of rows added.

    ADR-323 D3 — admins ONLY, deliberately narrower than the ADP precedent
    (`adp.py`), which fans out to ["admin", "management"]. Rotating a bot token
    is an admin task; management has no lever on it, and alerting someone who
    cannot act trains them to dismiss alerts.

    ADR-323 D4 — deduped on UNREAD. A crash-looping bot fails on every call, so
    without this a dispatcher retrying five times mails each admin five rows and
    the alert becomes noise exactly when it matters. Unread rather than
    time-windowed because a dead integration is a continuous condition, not an
    event: an admin already acting on it should not be re-alerted, while one who
    dismissed it without fixing it will be — which is correct.

    Never raises. This runs on paths that are ALREADY handling a failure; an
    alerting bug must not become the thing that breaks the request.
    """
    try:
        admins = (
            db.query(Employee)
            .filter(
                # Dim 1. Without this every admin of every tenant is mailed
                # about one company's outage.
                Employee.company_id == company_id,
                Employee.role == "admin",
                Employee.is_active == True,  # noqa: E712
            )
            .all()
        )

        added = 0
        for admin in admins:
            # Per-recipient: an admin with no unread alert still gets one even
            # when a colleague already has theirs.
            existing = (
                db.query(Notification)
                .filter(
                    Notification.company_id == company_id,
                    Notification.employee_id == admin.id,
                    Notification.type == notif_type,
                    Notification.is_read == False,  # noqa: E712
                )
                .first()
            )
            if existing is not None:
                continue

            db.add(
                Notification(
                    company_id=company_id,
                    employee_id=admin.id,
                    type=notif_type,
                    message=message,
                )
            )
            added += 1

        # ADR-335 D4 — both audiences from one call, for different reasons.
        # Company admins must know their crews are on in-app only; super admins
        # are the only people who can rotate the credential. Raised here rather
        # than at each call site so a future integration cannot alert one
        # audience and forget the other.
        #
        # Deliberately different dedup: the Notification dedups on UNREAD (an
        # inbox), the PlatformAlert on the OPEN INCIDENT (a condition). That
        # difference is why ADR-324 rejected bolting this onto Notification.
        raise_platform_alert(db, alert_type=notif_type, company_id=company_id,
                             message=message)

        if added:
            logger.warning(
                "integration alert: notified %d admin(s) of company=%s type=%s",
                added, company_id, notif_type,
            )
        return added

    except Exception:
        logger.exception(
            "integration alert: could not notify admins of company=%s type=%s",
            company_id, notif_type,
        )
        return 0

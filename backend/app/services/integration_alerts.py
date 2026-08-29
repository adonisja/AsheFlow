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
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.employee import Employee
from app.models.notification import Notification

logger = logging.getLogger(__name__)

DISCORD_INTEGRATION_FAILED = "discord_integration_failed"

# Names the blast radius, not the endpoint that happened to fail. "The bot is
# down" understates it — every Discord surface stops working at once, and an
# admin sizing the outage from one endpoint's name would under-react.
DISCORD_DOWN_MESSAGE = (
    "Discord messages are not being delivered — the bot could not be reached. "
    "Dispatch posts, crew finalisation and DMs are affected until it is restored."
)


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

"""When a push may be sent, in the company's own time (ADR-487 D5).

SEVERITY'S ONLY JOB IN PUSH
===========================
The registry's `PUSH` flag is the entire decision about WHETHER a type pushes --
25 of 86 types carry it, and `INFO` does not mean quiet, it means nothing is
waiting on you (`dispatch_finalized` is INFO that must still reach a crew).

Severity decides only whether a push may break quiet hours:

    URGENT          sent immediately, always
    ACTION, INFO    held until shift_start
    NOTICE          never pushed at all (ADR-488 D8: ticker-only)

URGENT breaking through is the whole point of the tier. If an injury alert can
wait four hours it is not urgent and belongs in ACTION.

QUIET HOURS RESOLVE IN COMPANY-LOCAL TIME
=========================================
A window computed in UTC is wrong for every tenant outside the server's zone --
the defect class ADR-486 was written for and found five instances of. So the
anchor goes through `company_datetime`, never `.replace(tzinfo=utc)`.

AND THE ANCHOR CAN BE NULL
==========================
`CompanyConfig.shift_start` is `Column(Time, nullable=True)` with **no
server_default** -- verified, the "default 09:00" on a sibling column is a
comment, not a default. So the NULL case is real and needs a stated answer.

**The answer is send immediately, not hold indefinitely.** A held push with no
release time is a push that never arrives, and silent non-delivery is worse than
a badly-timed notification. The tenant is reported so the missing config is
visible rather than absorbed -- the same reasoning as ADR-488 D4d's "skip the
tenant and say so", reaching the opposite ACTION because here the failure mode
is silence rather than noise.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from app.models.company import CompanyConfig
from app.services.local_date import company_datetime, company_tz
from app.services.notification_spec import Severity

logger = logging.getLogger(__name__)

#: Severities that may wake someone. Exactly one, deliberately.
_BREAKS_QUIET_HOURS = frozenset({Severity.URGENT})


def release_at(
    db: Session,
    company_id,
    severity: Severity,
    *,
    now: datetime | None = None,
) -> datetime | None:
    """When this push may be sent. `None` means "now".

    Returns a UTC instant in the future only when the push must be HELD. Every
    other case -- URGENT, inside working hours, or no anchor configured --
    returns None, which the caller reads as "send immediately".

    `now` is injectable so a test can pin 02:00 local without freezing the
    clock globally.
    """
    if severity in _BREAKS_QUIET_HOURS:
        return None

    now = now or datetime.now(timezone.utc)

    config = (
        db.query(CompanyConfig)
        .filter(CompanyConfig.company_id == company_id)
        .first()
    )
    # Reads CompanyConfig, NOT Company: `shift_start` and `operating_mode` both
    # live on the config row, and `Company.shift_start` does not exist. That
    # mistake is an AttributeError at request time rather than at import
    # (CLAUDE.md D3, precedent ADR-446).
    shift_start = getattr(config, "shift_start", None) if config else None

    if shift_start is None:
        # No anchor. Send now and say so -- a held push with no release time is
        # a push that never arrives.
        logger.info(
            "push: company %s has no shift_start, so quiet hours cannot be "
            "computed and non-urgent pushes send immediately. Set it in company "
            "settings to hold overnight notifications until the shift starts.",
            company_id,
        )
        return None

    tz = company_tz(db, company_id)
    local_now = now.astimezone(tz)
    today_start = company_datetime(tz, local_now.date(), shift_start)

    if now >= today_start:
        # The shift has started. Inside working hours, so send.
        return None

    # Before today's shift start -- hold until it.
    #
    # Note this covers the 02:00 case AND the 06:00-with-an-08:00-shift case
    # with one comparison. An explicit "is it night?" window would need a
    # second anchor (shift_end) and would be wrong for any tenant whose crews
    # start before the server's idea of morning.
    return today_start


def describe(release: datetime | None) -> str:
    """For a log line or a task result. Never shown to a user."""
    return "now" if release is None else f"held until {release.isoformat()}"

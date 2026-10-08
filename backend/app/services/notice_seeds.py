"""The platform notices every company starts with (ADR-488 D1).

These replace four beat tasks that fired on a fixed SERVER hour. They ship as
ORDINARY `NoticeTemplate` rows, not as a runtime constant, for ADR-485 D8's
reason:

    A special-cased built-in is a second code path that drifts from the one
    admins use -- and the one admins use is the one that gets tested.

So this module is the SEED SOURCE, read at company creation and at backfill. It
is not consulted when a notice fires: the sweep reads rows.

WHAT EACH ONE REPLACES, AND WHY THE TIMING CHANGED
==================================================

    task today                  fired            becomes
    -------------------------   --------------   ---------------------------
    alert_finalization_deadline 09:05 server     DISPATCH_CUTOFF - 5 min
    remind_fuel_log_missing     17:00 + 18:30    SHIFT_END - 15 min, 2 passes
    warn_before_mfa_deadline    16:30 server     FIXED_LOCAL 16:30 (right zone)

THREE, not the four ADR-487 D4d listed. `detect_timecard_mismatches` stays a
task (ADR-488 D5a): it `db.add()`s TimeCardAdjustment rows, so it IS the scan
rather than a reminder that one happened, and as a notice an unconfigured anchor
would silently skip the DETECTION instead of a message. It gets the narrow half
of the fix — its crontab moves to resolve per-tenant local midnight.

    A notice reminds somebody that a time arrived. If skipping it would skip
    WORK rather than a message, it is a task.

One of the three needs no tenant config at all -- the MFA warning keeps its hour
and merely resolves it in the tenant's zone. That is why this migration is not
uniformly expensive: the hard part is only the two that key on columns, and both
columns already exist.
"""
from __future__ import annotations

import uuid
from datetime import date, time
from typing import NamedTuple

from sqlalchemy.orm import Session

from app.models.notice import (
    Anchor, Condition, NoticeOrigin, NoticeSchedule, NoticeTemplate,
)


class SeedNotice(NamedTuple):
    """One platform notice, as a declaration rather than a crontab."""

    seed_key: str
    label: str
    body: str
    anchor: Anchor
    condition: Condition
    audience: str
    offset_minutes: int = 0
    at_local: time | None = None
    # ADR-488 D6a. Only the fuel log needs a second ask, because only its
    # condition can still resolve between passes.
    passes: int = 1
    repeat_after_minutes: int | None = None


PLATFORM_NOTICES: tuple[SeedNotice, ...] = (
    SeedNotice(
        seed_key="dispatch_unfinalized",
        label="Finalize Dispatch",
        # The body names the ACTION, not the failure. ADR-487 D10's rule for an
        # ACTION-shaped message, applied to a notice.
        body=(
            "Dispatch has not been finalized for today. Trucks still open will "
            "not notify their crews until you finalize."
        ),
        anchor=Anchor.DISPATCH_CUTOFF,
        # Five minutes: enough to act, late enough that the list is real.
        offset_minutes=-5,
        condition=Condition.UNFINALIZED_DISPATCH_EXISTS,
        audience="dispatch",
    ),
    SeedNotice(
        seed_key="fuel_log_missing",
        label="Fuel Log",
        body=(
            "Your fuel and mileage log for today has not been submitted. "
            "Please file it before you finish for the day."
        ),
        anchor=Anchor.SHIFT_END,
        # Fifteen minutes before shift end: a driver cannot file before
        # returning, and the old 17:00 fired three hours early for a tenant
        # whose drivers return at 20:00.
        offset_minutes=-15,
        condition=Condition.DRIVER_MISSING_FUEL_LOG,
        audience="driver",
        # The two-pass behaviour the old task had on purpose: "a second pass
        # re-notifies any still-missing drivers, this handles late returns".
        passes=2,
        repeat_after_minutes=90,
    ),
    SeedNotice(
        seed_key="mfa_deadline_warning",
        label="Set Up Two-Factor",
        body=(
            "Two-factor authentication is required soon. Open AsheFlow and "
            "follow the prompt -- after the deadline you will not be able to "
            "use the app until it is done."
        ),
        # The hour was never the problem; the timezone was. 16:30 LOCAL.
        anchor=Anchor.FIXED_LOCAL,
        at_local=time(16, 30),
        condition=Condition.MFA_DEADLINE_WITHIN_WARNING,
        audience="all",
    ),
)


def seed_platform_notices(db: Session, company_id, created_on: date | None = None) -> int:
    """Create any platform notice this company is missing. Idempotent.

    Idempotent by the partial unique index on (company_id, seed_key), and by
    checking first so a re-run is not an IntegrityError the caller has to catch.
    Returns the number created, so a backfill can report what it did.

    Does NOT commit -- the caller owns the transaction, matching
    `write_notification` and the rest of this codebase's service layer.
    """
    existing = {
        key for (key,) in db.query(NoticeTemplate.seed_key).filter(
            NoticeTemplate.company_id == company_id,
            NoticeTemplate.seed_key.isnot(None),
        ).all()
    }
    start = created_on or date.today()
    created = 0

    for seed in PLATFORM_NOTICES:
        if seed.seed_key in existing:
            continue

        notice = NoticeTemplate(
            id=uuid.uuid4(),
            company_id=company_id,
            origin=NoticeOrigin.PLATFORM.value,
            seed_key=seed.seed_key,
            label=seed.label,
            body=seed.body,
            anchor=str(seed.anchor),
            offset_minutes=seed.offset_minutes,
            at_local=seed.at_local,
            condition=str(seed.condition),
            audience=seed.audience,
            is_active=True,
        )
        db.add(notice)
        db.flush()      # assigns the id the schedule needs

        db.add(NoticeSchedule(
            id=uuid.uuid4(),
            company_id=company_id,
            notice_id=notice.id,
            mode="daily",
            starts_on=start,
            # NULL deliberately: a platform notice does not expire, because the
            # condition it reports on recurs indefinitely (ADR-488 D11). The
            # tenant-must-end rule is checked in the router, not here.
            ends_on=None,
            max_fires_per_day=seed.passes,
            repeat_after_minutes=seed.repeat_after_minutes,
        ))
        created += 1

    return created

"""Minting OV ids, atomically (ADR-400 A5d).

`OV####` is unique per company per day and resets daily, so "OV12" means today's
twelfth — which is how a captain says it out loud, and why a Postgres sequence
was rejected: a sequence climbs forever and the id stops meaning anything on the
floor.

The cost of a daily reset is that the next id has to be COMPUTED, and two
captains on different trucks in the same company compute it from the same row
set. `SELECT max(ov_id) + 1` outside a transaction hands both the same number.

The guard is `uq_workforce_ovs_company_date_id` plus a bounded retry: the loser's
INSERT raises IntegrityError, we re-read the max and try again. No advisory lock,
no lock table — this is how the codebase already handles concurrent id
assignment (`uq_routes_assignment_number`, ADR-302 D3a) and how ADR-292's
manual-returns path recovers from a lost unique-constraint race.
"""
from __future__ import annotations

import logging
import re
from datetime import date
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.workforce_ov import WorkforceOV

logger = logging.getLogger(__name__)

OV_PREFIX = "OV"
_OV_RE = re.compile(r"^OV(\d+)$")

# Enough attempts to lose several races in a row, few enough that a genuine
# constraint bug surfaces as an error instead of spinning.
_MAX_ATTEMPTS = 6


def is_ov_id(bag_id: str | None) -> bool:
    """True for "OV0012", false for a tote's "6800".

    Bag ids are bare digits once `parse_bag_label` strips the colour word, so the
    two namespaces cannot collide and this test is total.
    """
    return bool(bag_id) and _OV_RE.match(bag_id.strip()) is not None


def _next_number(db: Session, company_id: UUID, entry_date: date) -> int:
    """Highest OV number used by this company today, plus one.

    Scoped to (company, date) rather than (company, truck): a captain reading
    "OV12" off one truck and "OV12" off another would have no way to tell them
    apart, and the ids travel with packages that get handed between trucks.
    """
    rows = (
        db.query(WorkforceOV.ov_id)
        .filter(
            WorkforceOV.company_id == company_id,
            WorkforceOV.entry_date == entry_date,
        )
        .all()
    )
    highest = 0
    for (ov_id,) in rows:
        m = _OV_RE.match(ov_id or "")
        if m:
            highest = max(highest, int(m.group(1)))
    return highest + 1


def mint(
    db: Session,
    *,
    company_id: UUID,
    truck_id: UUID,
    entry_date: date,
    source: str,
    zone_label: str | None = None,
    size: str | None = None,
    confirmed_at=None,
    confirmed_by: UUID | None = None,
) -> WorkforceOV:
    """Create one OV with the next free id for this company-day.

    Retries on IntegrityError, which is the expected outcome when two captains
    mint at once rather than an exceptional one. The caller gets a flushed row;
    committing is the caller's business, so this composes inside a larger
    transaction (seeding a whole sheet, say).
    """
    for attempt in range(_MAX_ATTEMPTS):
        number = _next_number(db, company_id, entry_date)
        ov = WorkforceOV(
            company_id=company_id,
            truck_id=truck_id,
            entry_date=entry_date,
            ov_id=f"{OV_PREFIX}{number:04d}",
            zone_label=zone_label,
            size=size,
            source=source,
            confirmed_at=confirmed_at,
            confirmed_by=confirmed_by,
        )
        try:
            # SAVEPOINT, not commit: a failed INSERT must not roll back work the
            # caller did before calling us. Without this, losing one race would
            # discard an entire sheet seed.
            #
            # The savepoint opens BEFORE the add. `begin_nested()` takes a
            # snapshot, and taking a snapshot flushes whatever is already
            # pending — so adding first puts our INSERT *outside* the savepoint,
            # where the IntegrityError escapes this except and poisons the
            # caller's transaction. Caught by a race test on 2026-09-09; the
            # earlier version of this block had exactly that bug.
            with db.begin_nested():
                db.add(ov)
                db.flush()
            return ov
        except IntegrityError:
            # No expunge: rolling the savepoint back already evicted `ov` from
            # the session, and expunging an absent instance raises
            # InvalidRequestError — which would surface as a 500 on the retry
            # path that exists to prevent one.
            pass
            if attempt == _MAX_ATTEMPTS - 1:
                raise
            logger.info(
                "workforce_ov_mint_retry",
                extra={"company_id": str(company_id), "attempt": attempt + 1},
            )
    raise RuntimeError("unreachable: the loop returns or raises")

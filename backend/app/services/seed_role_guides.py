"""Seed or re-seed one company's role guides (ADR-494 D4).

Called from three places, all of which want the same three-case behaviour:

  - company creation      -- a new tenant gets all 20 rows
  - the backfill migration -- existing tenants get theirs
  - a platform content revision -- SEED_VERSION bumps, unedited rows follow

THE THREE CASES

    row absent                     -> INSERT
    row present, never edited      -> UPDATE if SEED_VERSION is newer
    row present, EDITED by tenant  -> LEAVE ALONE, always

The third is the one with teeth. A tenant who rewrote their walker guide to match
their own rules must never have it reverted by a platform deploy -- that is a
silent content regression nobody would attribute to us. `edited_at IS NOT NULL`
is the whole test, and the model's CHECK keeps `edited_at`/`edited_by` set
together so it cannot be half-true.

WHY NOT `ON CONFLICT DO UPDATE`

A single upsert cannot express "update only if unedited AND my version is newer"
without a WHERE on the conflict target, and once the statement needs that it is
no shorter than the loop -- while being considerably harder to read and to test
the edited-row case against. The row count here is 20 per company.
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models.role_guide import RoleGuide
from app.services.role_guide_seeds import SEED_VERSION, iter_seeds

logger = logging.getLogger(__name__)


def _version_at_least(stored: str | None, target: str) -> bool:
    """Is `stored` already at or past `target`?

    `seed_version` is String(16) so a future revision can be "1.1" or "2", but
    STRING comparison is wrong for exactly the case that matters: "10" < "9"
    lexically, so a tenth platform revision would stop reaching unedited rows
    and nothing would report it. Compared component-wise as integers instead.

    A stored value that is NULL (pre-versioning row) or unparseable is treated
    as older, so the seed applies -- the safe direction, since the alternative
    is a row frozen at text nobody can account for.
    """
    if not stored:
        return False
    try:
        a = [int(x) for x in str(stored).split(".")]
        b = [int(x) for x in str(target).split(".")]
    except ValueError:
        return False
    # Pad so "1" and "1.0" compare equal rather than by length.
    width = max(len(a), len(b))
    a += [0] * (width - len(a))
    b += [0] * (width - len(b))
    return a >= b


def seed_role_guides(db: Session, company_id) -> dict[str, int]:
    """Bring one company's role guides up to SEED_VERSION.

    Flushes but does NOT commit -- the caller owns the transaction, so this can
    run inside company creation's existing one. (ADR-490: a service that commits
    inside someone else's transaction splits an atomic write in half.)

    Returns counts for the caller's audit detail.
    """
    existing = {
        g.seed_key: g
        for g in db.query(RoleGuide).filter(RoleGuide.company_id == company_id).all()
        if g.seed_key is not None
    }

    counts = {"inserted": 0, "updated": 0, "skipped_edited": 0, "skipped_current": 0}

    for role, mode, title, body, key in iter_seeds():
        row = existing.get(key)

        if row is None:
            db.add(RoleGuide(
                company_id=company_id,
                role=role,
                operating_mode=mode,
                title=title,
                body=body,
                seed_key=key,
                seed_version=SEED_VERSION,
            ))
            counts["inserted"] += 1
            continue

        # The tenant's words win, permanently.
        if row.edited_at is not None:
            counts["skipped_edited"] += 1
            continue

        if _version_at_least(row.seed_version, SEED_VERSION):
            counts["skipped_current"] += 1
            continue

        row.title = title
        row.body = body
        row.seed_version = SEED_VERSION
        counts["updated"] += 1

    db.flush()
    logger.info(
        "role guides seeded for company=%s version=%s %s",
        company_id, SEED_VERSION, counts,
    )
    return counts

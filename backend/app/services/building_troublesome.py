"""Troublesome-building decaying score (ADR-218).

Distills the RTS "troublesome address" signal into a decaying score per door
(`troublesome_doors`, ADR-584 D6; it was on BuildingProfile) so the company-wide
troublesome list reads off the door — no delivery-row retention needed to
recompute it (which is what frees ADR-219 to null the delivery address at 48h).

Model:
  - bump per RTS, weighted by type (reattemptable = transient/lighter);
  - nightly decay with a ~30-day half-life;
  - a captain resolution note dampens the score once (not to zero — buildings
    regress);
  - "troublesome" for display = score >= TROUBLESOME_THRESHOLD.

Starting values — tune from real RTS volume once observed.
"""
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.orm import Session


# Reattemptable RTS reasons are often transient (timing / access) → lighter bump.
# Harder failures (refused, cancelled, damaged, future) signal real building
# friction → full bump.
_REATTEMPTABLE_BUMP = 0.5
_HARD_BUMP = 1.0
_REATTEMPTABLE_TYPES = {"no_access", "business_closed", "inclement_weather"}

# 30-day half-life: score *= 0.5 ** (1/30) per night ≈ 0.977.
DECAY_PER_NIGHT = 0.5 ** (1 / 30)
DECAY_FLOOR = 0.1              # below this, snap to 0 (no infinite tiny decimals)
RESOLUTION_DAMPEN = 0.5       # one-time multiply when a resolution note is added

TROUBLESOME_THRESHOLD = 2.5   # score at/above which a building surfaces


def bump_for_rts_type(rts_type: str) -> float:
    return _REATTEMPTABLE_BUMP if rts_type in _REATTEMPTABLE_TYPES else _HARD_BUMP


def record_rts_incident(
    db: Session,
    company_id: UUID,
    normalised_address: str | None,
    block_key: str | None,
    rts_type: str,
    borough: str | None = None,
) -> None:
    """Bump the door's troublesome score for one RTS (ADR-218 scoring, ADR-584 D6
    storage). Keyed by door identity (company, borough, canonical address) in
    `troublesome_doors`; no stub BuildingProfile is created any more.
    Company-scoped. Does NOT commit — caller owns the txn.

    `block_key` is kept in the signature for the existing caller; the door
    identity no longer needs it.
    """
    from app.models.troublesome_door import TroublesomeDoor

    if not normalised_address:
        return  # no door to attribute to (address unresolved)

    q = db.query(TroublesomeDoor).filter(
        TroublesomeDoor.company_id == company_id,
        TroublesomeDoor.address == normalised_address,
    )
    door = (q.filter(TroublesomeDoor.borough == borough).first() if borough
            else q.filter(TroublesomeDoor.borough.is_(None)).first())
    if door is None and borough:
        # A score copied before ADR-584 has no borough; claim it for this door.
        door = q.filter(TroublesomeDoor.borough.is_(None)).first()
        if door is not None:
            door.borough = borough
    if door is None:
        door = TroublesomeDoor(company_id=company_id, borough=borough,
                               address=normalised_address, score=0.0)
        db.add(door)
        # Sessions run autoflush=False (ADR-510), so without this a second RTS
        # for the same door in one transaction can't see this row and adds a
        # duplicate, which fails the unique key at commit.
        db.flush()

    door.score = (door.score or 0.0) + bump_for_rts_type(rts_type)
    door.last_incident_at = datetime.now(timezone.utc)


def apply_resolution(db: Session, bp) -> None:
    """One-time dampen when a captain records a resolution note on a building
    profile: the doors at that address, in that company. Not zero — a resolved
    building can regress. Caller owns the txn."""
    from app.models.troublesome_door import TroublesomeDoor

    now = datetime.now(timezone.utc)
    for door in db.query(TroublesomeDoor).filter(
        TroublesomeDoor.company_id == bp.company_id,
        TroublesomeDoor.address == bp.normalised_address,
    ).all():
        door.score = (door.score or 0.0) * RESOLUTION_DAMPEN
        door.resolved_at = now


def troublesome_doors(db: Session, company_id: UUID, limit: int = 5):
    """The company's troublesome doors, worst first (score at or above the
    threshold). Read by My Performance."""
    from app.models.troublesome_door import TroublesomeDoor
    return (db.query(TroublesomeDoor)
            .filter(TroublesomeDoor.company_id == company_id,
                    TroublesomeDoor.score >= TROUBLESOME_THRESHOLD)
            .order_by(TroublesomeDoor.score.desc())
            .limit(limit).all())


def scores_by_address(db: Session, company_id: UUID) -> dict[str, float]:
    """address → highest score for the company (a door in two boroughs keeps
    the worse one). Read by run_sort.get_building_info."""
    from app.models.troublesome_door import TroublesomeDoor
    out: dict[str, float] = {}
    for addr, score in db.query(TroublesomeDoor.address, TroublesomeDoor.score).filter(
            TroublesomeDoor.company_id == company_id, TroublesomeDoor.score > 0).all():
        out[addr] = max(out.get(addr, 0.0), score or 0.0)
    return out


def decay_all(db: Session) -> int:
    """Nightly decay across full-mode companies' troublesome doors. Returns rows touched.

    ADR-293: scoped to companies with `operating_mode='full'`, NOT all companies.

    The decay rate is calibrated against daily delivery evidence refreshing the score.
    In workforce mode there are no delivery rows, so accrual drops by orders of
    magnitude while decay would continue at full rate — every score would fade to zero
    unopposed and real operational intelligence would be erased by a background job
    nobody is watching. Freezing is the honest state.
    """
    from app.models.troublesome_door import TroublesomeDoor
    from app.services.company_config import full_mode_company_ids

    full_mode = full_mode_company_ids(db)
    if not full_mode:
        return 0

    rows = (
        db.query(TroublesomeDoor)
        .filter(TroublesomeDoor.score > 0, TroublesomeDoor.company_id.in_(full_mode))
        .all()
    )
    for door in rows:
        decayed = (door.score or 0.0) * DECAY_PER_NIGHT
        door.score = 0.0 if decayed < DECAY_FLOOR else decayed
    return len(rows)

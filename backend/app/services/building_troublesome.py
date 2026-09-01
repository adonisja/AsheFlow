"""Troublesome-building decaying score (ADR-218).

Distills the RTS "troublesome address" signal into a decaying score on the
company BuildingProfile so the company-wide troublesome list reads off the
building — no delivery-row retention needed to recompute it (which is what frees
ADR-219 to null the delivery address at 48h).

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

from app.models.building_profile import BuildingProfile

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
) -> None:
    """Bump the building's troublesome score for one RTS. Creates a pending stub
    BuildingProfile if the address has none yet (consistent with how profiles are
    otherwise born). Company-scoped. Does NOT commit — caller owns the txn.
    """
    if not normalised_address:
        return  # no building to attribute to (address unresolved)

    bp = (
        db.query(BuildingProfile)
        .filter(
            BuildingProfile.company_id == company_id,
            BuildingProfile.normalised_address == normalised_address,
        )
        .first()
    )
    now = datetime.now(timezone.utc)
    if bp is None:
        # Cold building — create a pending stub carrying just enough to hold the
        # signal. building_type/workload_class default like any unprofiled row.
        bp = BuildingProfile(
            company_id=company_id,
            normalised_address=normalised_address,
            block_key=block_key or "",
            building_type="walkup",           # neutral default; gets corrected on real profiling
            workload_class="standard",
            building_type_status="pending",
            # ADR-277 D1: 'resolved', not the 'pending' default. This address
            # did NOT come from a human typing — it is the enriched manifest's
            # normalised_address, already canonicalised by GeoClient upstream.
            # Leaving it 'pending' would queue a redundant geocode of a string
            # GeoClient itself produced, and (worse) a transport failure could
            # then flip a real building to 'rejected'.
            address_status="resolved",
            submitted_by_name="system:rts",
            troublesome_score=0.0,
        )
        db.add(bp)

    bp.troublesome_score = (bp.troublesome_score or 0.0) + bump_for_rts_type(rts_type)
    bp.troublesome_last_incident_at = now


def apply_resolution(db: Session, bp: BuildingProfile) -> None:
    """One-time dampen when a captain records a resolution note. Not zero —
    a resolved building can regress. Caller owns the txn."""
    bp.troublesome_score = (bp.troublesome_score or 0.0) * RESOLUTION_DAMPEN
    bp.troublesome_resolved_at = datetime.now(timezone.utc)


def decay_all(db: Session) -> int:
    """Nightly decay across full-mode building profiles. Returns rows touched.

    ADR-293: scoped to companies with `operating_mode='full'`, NOT all companies.

    The decay rate is calibrated against daily delivery evidence refreshing the score.
    In workforce mode there are no delivery rows, so accrual drops by orders of
    magnitude while decay would continue at full rate — every score would fade to zero
    unopposed and real operational intelligence would be erased by a background job
    nobody is watching. The building does not become less troublesome; only our record
    of it does.

    Freezing is the honest state: a rate tuned for evidence that stopped arriving has
    no correct value. Scores hold at their last delivery-informed value and decay
    resumes if the tenant returns to full mode.
    """
    from app.services.company_config import full_mode_company_ids

    full_mode = full_mode_company_ids(db)
    if not full_mode:
        return 0

    rows = (
        db.query(BuildingProfile)
        .filter(
            BuildingProfile.troublesome_score > 0,
            BuildingProfile.company_id.in_(full_mode),
        )
        .all()
    )
    for bp in rows:
        decayed = (bp.troublesome_score or 0.0) * DECAY_PER_NIGHT
        bp.troublesome_score = 0.0 if decayed < DECAY_FLOOR else decayed
    return len(rows)

"""persist_zones — write TruckZone rows to the database.

Pipeline position:
    cluster_packages() → assign_clusters() → tier1_verify() → persist_zones()

Called only after tier1_verify() confirms no misaligned totes (or dispatch
explicitly overrides). Deactivates any prior zones for the same company + date
before inserting new ones, so re-runs are safe (idempotent per sort day).

Input:  AssignmentProposal + zone_date + actor context
Output: list[TruckZone] — newly created rows (flushed, not yet committed)
        Caller owns the session and commits.
"""
from __future__ import annotations

import uuid
from datetime import date
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.truck_zone import TruckZone
from app.services.assign_clusters import AssignmentProposal


def persist_zones(
    proposal: AssignmentProposal,
    zone_date: date,
    company_id: UUID,
    created_by: UUID,
    created_by_name: str,
    db: Session,
) -> list[TruckZone]:
    """Write one TruckZone row per ClusterAssignment to the database.

    Existing zones for (company_id, zone_date) are deactivated before
    inserting new ones. The caller must commit the session after this returns.

    Overflow clusters (is_overflow=True) are included — they are labelled
    distinctly so dispatch can identify them in the UI.

    Args:
        proposal:         Output of assign_clusters().
        zone_date:        The sort day these zones belong to.
        company_id:       Tenant scope.
        created_by:       Employee ID of the dispatch user triggering the sort.
        created_by_name:  Display name stored for audit trail.
        db:               SQLAlchemy session — caller owns commit/rollback.

    Returns:
        List of newly added TruckZone instances (added to session, not committed).
    """
    # Deactivate any zones already persisted for this company + date (re-run safety)
    db.query(TruckZone).filter(
        TruckZone.company_id == company_id,
        TruckZone.zone_date == zone_date,
        TruckZone.is_active.is_(True),
    ).update({"is_active": False}, synchronize_session="fetch")

    new_zones: list[TruckZone] = []

    # Track how many clusters each truck gets so we can label multi-cluster trucks
    truck_cluster_counts: dict[UUID, int] = {}
    for assignment in proposal.assignments:
        truck_cluster_counts[assignment.truck_id] = truck_cluster_counts.get(assignment.truck_id, 0) + 1

    # Per-truck sequence counter for multi-cluster labelling
    truck_seq: dict[UUID, int] = {}

    for assignment in proposal.assignments:
        tid = assignment.truck_id
        seq = truck_seq.get(tid, 0) + 1
        truck_seq[tid] = seq

        count = truck_cluster_counts[tid]
        if assignment.is_overflow:
            label = f"{assignment.truck_name} (overflow)"
        elif count > 1:
            label = f"{assignment.truck_name} ({seq}/{count})"
        else:
            label = assignment.truck_name

        tbas = [p["tba"] for p in assignment.cluster.packages if p.get("tba")]

        zone = TruckZone(
            id              = uuid.uuid4(),
            company_id      = company_id,
            truck_id        = tid,
            truck_polygon   = assignment.cluster.polygon,
            package_tbas    = tbas,
            zone_label      = label[:50],   # column is VARCHAR(50)
            zone_date       = zone_date,
            is_active       = True,
            created_by      = created_by,
            created_by_name = created_by_name,
        )
        db.add(zone)
        new_zones.append(zone)

    db.flush()
    return new_zones

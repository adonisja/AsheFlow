"""tier1_verify — post-dispatch tote verification.

Runs after assign_clusters + persist_zones. Uses the day's package assignments
to detect misloads before trucks leave the station.

Pipeline position:
    cluster_packages() → assign_clusters() → tier1_verify() → persist_zones()
    (tier1_verify is a read-only check; persist_zones writes the DB)

Input:  AssignmentProposal (from assign_clusters) + per-tote package lists
Output: VerificationResult — classification per tote, notification payload for dispatch
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

from app.services.assign_clusters import AssignmentProposal, ClusterAssignment
from app.services.cluster_packages import Cluster

ToteClassification = Literal["clean", "stray", "uncertain", "misaligned"]

_SIGMA_MULTIPLIER = 0.30   # internal constant — not tunable per company


# ── data structures ───────────────────────────────────────────────────────────

@dataclass
class ToteResult:
    tote_id: str
    truck_id: UUID
    classification: ToteClassification
    total_packages: int
    outside_packages: int
    outside_pct: float
    outside_tbas: list[str]
    suggested_truck_id: UUID | None   # if stray packages belong to a known zone
    unresolvable: bool


@dataclass
class VerificationResult:
    tote_results: list[ToteResult]
    flagged: list[ToteResult]          # non-clean results only
    all_clean: bool


# ── geometry helpers ──────────────────────────────────────────────────────────

def _point_in_polygon(lat: float, lng: float, polygon: list[dict]) -> bool:
    """Ray casting algorithm — returns True if (lat, lng) is inside polygon."""
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]["lng"], polygon[i]["lat"]
        xj, yj = polygon[j]["lng"], polygon[j]["lat"]
        if ((yi > lat) != (yj > lat)) and (lng < (xj - xi) * (lat - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def _bounding_box_contains(lat: float, lng: float, polygon: list[dict]) -> bool:
    lats = [v["lat"] for v in polygon]
    lngs = [v["lng"] for v in polygon]
    return min(lats) <= lat <= max(lats) and min(lngs) <= lng <= max(lngs)


def _polygon_span(polygon: list[dict]) -> float:
    """Return max(lat_span, lng_span) of the polygon's bounding box in degrees."""
    lats = [v["lat"] for v in polygon]
    lngs = [v["lng"] for v in polygon]
    return max(max(lats) - min(lats), max(lngs) - min(lngs))


def _tote_centroid_and_sigma(packages: list[dict]) -> tuple[float, float, float, float]:
    """Return (mean_lat, mean_lng, sigma_lat, sigma_lng)."""
    lats = [p["lat"] for p in packages]
    lngs = [p["lng"] for p in packages]
    n = len(packages)
    m_lat = sum(lats) / n
    m_lng = sum(lngs) / n
    s_lat = math.sqrt(sum((x - m_lat) ** 2 for x in lats) / n) if n > 1 else 0.0
    s_lng = math.sqrt(sum((x - m_lng) ** 2 for x in lngs) / n) if n > 1 else 0.0
    return m_lat, m_lng, s_lat, s_lng


def _package_in_zone(pkg: dict, polygon: list[dict]) -> bool:
    lat, lng = pkg["lat"], pkg["lng"]
    if not _bounding_box_contains(lat, lng, polygon):
        return False
    return _point_in_polygon(lat, lng, polygon)


# ── classification logic ──────────────────────────────────────────────────────

def _classify_tote(
    outside: int,
    total: int,
    cfg,
) -> ToteClassification:
    if outside == 0:
        return "clean"

    pct = outside / total

    if total < cfg.tier1_small_tote_cutoff:
        if outside <= cfg.tier1_small_stray_max:
            return "stray"
        if outside <= cfg.tier1_small_uncertain_max:
            return "uncertain"
        return "misaligned"
    else:
        if pct <= cfg.tier1_stray_pct:
            return "stray"
        if pct <= cfg.tier1_uncertain_pct:
            return "uncertain"
        return "misaligned"


# ── main function ─────────────────────────────────────────────────────────────

def tier1_verify(
    proposal: AssignmentProposal,
    totes: list[dict],    # [{"tote_id": str, "truck_id": UUID, "packages": [{"tba", "lat", "lng"}]}]
    cfg,                  # CompanyConfig row
) -> VerificationResult:
    """Verify tote placements against the day's zone polygons.

    proposal.assignments provides the polygon for each truck's zone cluster.
    Packages are checked against their truck's polygon(s); failures trigger
    a search of other trucks' zones to determine where they belong.
    """
    # Build truck_id → list[polygon] (a truck may have multiple clusters)
    zones_by_truck: dict[UUID, list[list[dict]]] = {}
    for assignment in proposal.assignments:
        tid = assignment.truck_id
        polygon = assignment.cluster.polygon
        zones_by_truck.setdefault(tid, []).append(polygon)

    results: list[ToteResult] = []

    for tote in totes:
        tote_id = tote["tote_id"]
        truck_id = tote["truck_id"]
        packages = tote["packages"]

        if not packages:
            results.append(ToteResult(
                tote_id=tote_id, truck_id=truck_id,
                classification="clean", total_packages=0,
                outside_packages=0, outside_pct=0.0,
                outside_tbas=[], suggested_truck_id=None, unresolvable=False,
            ))
            continue

        own_zones = zones_by_truck.get(truck_id, [])
        m_lat, m_lng, s_lat, s_lng = _tote_centroid_and_sigma(packages)

        outside_pkgs: list[dict] = []

        for pkg in packages:
            in_own_zone = False
            for polygon in own_zones:
                # Bounding box pre-filter
                if not _bounding_box_contains(pkg["lat"], pkg["lng"], polygon):
                    continue
                # High-sigma totes: use centroid check; otherwise full point-in-polygon
                span = _polygon_span(polygon)
                high_sigma = (s_lat > _SIGMA_MULTIPLIER * span) or (s_lng > _SIGMA_MULTIPLIER * span)
                if high_sigma:
                    in_own_zone = _bounding_box_contains(m_lat, m_lng, polygon)
                else:
                    in_own_zone = _point_in_polygon(pkg["lat"], pkg["lng"], polygon)
                if in_own_zone:
                    break

            if not in_own_zone:
                outside_pkgs.append(pkg)

        outside = len(outside_pkgs)
        total = len(packages)
        outside_pct = outside / total
        classification = _classify_tote(outside, total, cfg)

        # Find which truck's zone the outside packages belong to
        suggested_truck_id: UUID | None = None
        unresolvable = False

        if outside_pkgs:
            # Count votes for each other truck's zone
            truck_votes: dict[UUID, int] = {}
            for pkg in outside_pkgs:
                for assignment in proposal.assignments:
                    if assignment.truck_id == truck_id:
                        continue
                    if _package_in_zone(pkg, assignment.cluster.polygon):
                        truck_votes[assignment.truck_id] = truck_votes.get(assignment.truck_id, 0) + 1
                        break

            if truck_votes:
                suggested_truck_id = max(truck_votes, key=lambda k: truck_votes[k])
            else:
                unresolvable = True

        results.append(ToteResult(
            tote_id=tote_id,
            truck_id=truck_id,
            classification=classification,
            total_packages=total,
            outside_packages=outside,
            outside_pct=outside_pct,
            outside_tbas=[p["tba"] for p in outside_pkgs],
            suggested_truck_id=suggested_truck_id,
            unresolvable=unresolvable,
        ))

    flagged = [r for r in results if r.classification != "clean"]

    return VerificationResult(
        tote_results=results,
        flagged=flagged,
        all_clean=len(flagged) == 0,
    )

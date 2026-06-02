from __future__ import annotations
import math
from dataclasses import dataclass
from uuid import UUID

from shapely.geometry import Point, Polygon

from app.services.cluster_packages import Cluster, ClusterResult

WORKLOAD_PRIORITY = {
    "high_touch": 3.0,
    "high_wait":  2.0,
    "standard":   1.0,
    "bulk_drop":  0.0,
}


@dataclass
class ClusterAssignment:
    cluster: Cluster
    truck_id: UUID
    truck_name: str
    match_type: str       # "historical" | "sequential" | "overflow"
    workload_score: float | None
    is_overflow: bool


@dataclass
class AssignmentProposal:
    assignments: list[ClusterAssignment]
    unassigned_clusters: list[Cluster]
    outliers: list[dict]


# ── helpers ───────────────────────────────────────────────────────────────────

def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def _bounding_box_span_km(cluster: Cluster) -> float:
    bb = cluster.bounding_box
    lat_span = _haversine_km(bb.min_lat, bb.min_lng, bb.max_lat, bb.min_lng)
    lng_span = _haversine_km(bb.min_lat, bb.min_lng, bb.min_lat, bb.max_lng)
    return max(lat_span, lng_span)


def _centroid_inside_boundary(centroid: dict, boundary: list[dict]) -> bool:
    if not boundary:
        return True
    poly = Polygon([(v["lng"], v["lat"]) for v in boundary])
    pt = Point(centroid["lng"], centroid["lat"])
    return poly.contains(pt)


def _score_cluster(
    cluster: Cluster,
    profiles_by_block: dict[str, str],  # block_key → workload_class (highest resolved)
) -> float | None:
    weights = []
    for pkg in cluster.packages:
        block_key = pkg.get("block_key")
        if not block_key:
            continue
        wc = profiles_by_block.get(block_key)
        if wc is None:
            continue
        w = WORKLOAD_PRIORITY.get(wc)
        if w is not None:
            weights.append(w)

    if not weights:
        return None

    return sum(weights) / len(weights)


# ── main function ─────────────────────────────────────────────────────────────

def assign_clusters(
    result: ClusterResult,
    trucks: list[dict],            # [{"id": UUID, "name": str}, ...]
    recent_zones: list[dict],      # [{"truck_id": UUID, "centroid": {"lat", "lng"}, ...}, ...]
    company_boundary: list[dict],  # polygon vertices [{"lat": float, "lng": float}, ...]
    location_profiles: list[dict], # [{"block_key": str, "workload_class": str}, ...]
) -> AssignmentProposal:
    if not trucks:
        return AssignmentProposal(
            assignments=[],
            unassigned_clusters=result.clusters,
            outliers=result.outliers,
        )

    # Build block_key → highest workload_class lookup (mixed-block resolution: take highest)
    profiles_by_block: dict[str, str] = {}
    for lp in location_profiles:
        bk = lp["block_key"]
        wc = lp["workload_class"]
        existing = profiles_by_block.get(bk)
        if existing is None or WORKLOAD_PRIORITY.get(wc, 0) > WORKLOAD_PRIORITY.get(existing, 0):
            profiles_by_block[bk] = wc

    trucks_by_id = {t["id"]: t for t in trucks}
    truck_ids = [t["id"] for t in sorted(trucks, key=lambda t: t["name"])]
    assigned_truck_ids: set[UUID] = set()
    assignments: list[ClusterAssignment] = []
    unassigned: list[Cluster] = []

    # Separate overflow clusters (centroid outside company boundary)
    normal_clusters: list[Cluster] = []
    overflow_clusters: list[Cluster] = []
    for cluster in result.clusters:
        if _centroid_inside_boundary(cluster.centroid, company_boundary):
            normal_clusters.append(cluster)
        else:
            overflow_clusters.append(cluster)

    # Score all normal clusters
    scored: list[tuple[Cluster, float | None]] = [
        (c, _score_cluster(c, profiles_by_block)) for c in normal_clusters
    ]

    # ── Pass 1: historical zone matching ──────────────────────────────────────
    # Match each cluster to the truck whose most recent zone centroid is closest,
    # within a threshold of 1× the cluster's bounding box span.
    remaining: list[tuple[Cluster, float | None]] = []
    used_truck_ids: set[UUID] = set()

    for cluster, score in scored:
        threshold_km = max(_bounding_box_span_km(cluster), 0.5)
        clat = cluster.centroid["lat"]
        clng = cluster.centroid["lng"]

        best_truck_id: UUID | None = None
        best_dist = float("inf")

        for zone in recent_zones:
            tid = zone["truck_id"]
            if tid in used_truck_ids or tid not in trucks_by_id:
                continue
            zlat = zone["centroid"]["lat"]
            zlng = zone["centroid"]["lng"]
            dist = _haversine_km(clat, clng, zlat, zlng)
            if dist < threshold_km and dist < best_dist:
                best_dist = dist
                best_truck_id = tid

        if best_truck_id is not None:
            used_truck_ids.add(best_truck_id)
            assigned_truck_ids.add(best_truck_id)
            assignments.append(ClusterAssignment(
                cluster=cluster,
                truck_id=best_truck_id,
                truck_name=trucks_by_id[best_truck_id]["name"],
                match_type="historical",
                workload_score=score,
                is_overflow=False,
            ))
        else:
            remaining.append((cluster, score))

    # ── Pass 2: sequential assignment (north-to-south, trucks by name) ────────
    available_trucks = [tid for tid in truck_ids if tid not in used_truck_ids]
    remaining_sorted = sorted(remaining, key=lambda t: -t[0].centroid["lat"])  # north first

    for (cluster, score), truck_id in zip(remaining_sorted, available_trucks):
        used_truck_ids.add(truck_id)
        assigned_truck_ids.add(truck_id)
        assignments.append(ClusterAssignment(
            cluster=cluster,
            truck_id=truck_id,
            truck_name=trucks_by_id[truck_id]["name"],
            match_type="sequential",
            workload_score=score,
            is_overflow=False,
        ))

    # Any clusters still without a truck (more clusters than trucks)
    assigned_clusters = {a.cluster.cluster_id for a in assignments}
    for cluster, score in remaining_sorted:
        if cluster.cluster_id not in assigned_clusters:
            unassigned.append(cluster)

    # ── Pass 3: overflow clusters → nearest truck ─────────────────────────────
    for cluster in overflow_clusters:
        score = _score_cluster(cluster, profiles_by_block)
        clat = cluster.centroid["lat"]
        clng = cluster.centroid["lng"]

        nearest_truck_id: UUID | None = None
        nearest_dist = float("inf")
        for tid in truck_ids:
            # Find this truck's assigned cluster centroid as reference point
            ref = next((a for a in assignments if a.truck_id == tid), None)
            if ref is None:
                continue
            dist = _haversine_km(clat, clng, ref.cluster.centroid["lat"], ref.cluster.centroid["lng"])
            if dist < nearest_dist:
                nearest_dist = dist
                nearest_truck_id = tid

        if nearest_truck_id is not None:
            assignments.append(ClusterAssignment(
                cluster=cluster,
                truck_id=nearest_truck_id,
                truck_name=trucks_by_id[nearest_truck_id]["name"],
                match_type="overflow",
                workload_score=score,
                is_overflow=True,
            ))
        else:
            unassigned.append(cluster)

    return AssignmentProposal(
        assignments=assignments,
        unassigned_clusters=unassigned,
        outliers=result.outliers,
    )

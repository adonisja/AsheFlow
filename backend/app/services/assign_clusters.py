from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from app.services.cluster_packages import Cluster, ClusterResult

WORKLOAD_PRIORITY = {
    "high_touch": 3.0,
    "high_wait": 2.0,
    "standard": 1.0,
    "bulk_drop": 0,
}

@dataclass
class ClusterAssignment:
    cluster: Cluster
    truck_id: UUID
    truck_name: str
    match_type: str     # "historical" | "sequential" | "overflow"
    workload_score: float | None
    is_overflow: bool

@dataclass
class AssignmentProposal:
    assignments: list[ClusterAssignment]
    unassigned_clusters: list[Cluster]
    outliers: list[dict]

def _score_cluster(
    cluster: Cluster,
    profiles_by_block: dict[str, list[str]],
) -> float | None:
    # 1. Collect all workload_class values
    for pkg in packages:
        
    

def assign_clusters(
    result: ClusterResult,
    trucks: list[dict],            # [{"id": UUID, "name": str}, ...]
    recent_zones: list[dict],      # [{"truck_id": UUID, "centroid": dict, "polygon": list, "zone_date": date}, ...]
    company_boundary: list[dict],  # polygon vertices [{"lat": float, "lng": float}, ...]
    location_profiles: list[dict], # locked profiles [{"block_key": str, "workload_class": str}, ...]
    cfg,                           # CompanyConfig row — accesses tier1 fields directly
) -> AssignmentProposal:
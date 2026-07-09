from datetime import date, datetime
from uuid import UUID
from typing import Optional, Literal
from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Capacity constants (half-slot units ×2)
# ---------------------------------------------------------------------------

EFFORT_CAPACITY: dict[str, int] = {
    "easy":     12,   # 6 slots × 2
    "standard": 12,   # 6 slots × 2
    "heavy":    8,    # 4 slots × 2
}

EFFORT_CAPACITY_PAIRED: dict[str, int] = {
    "easy":     18,   # 9 slots × 2
    "standard": 18,   # 9 slots × 2
    "heavy":    12,   # 6 slots × 2
}

# workload_class → effort_class (from BuildingProfile / BuildingProfileLibrary)
WORKLOAD_TO_EFFORT: dict[str, str] = {
    "bulk_drop":  "easy",
    "standard":   "standard",
    "high_wait":  "heavy",
    "high_touch": "heavy",
}

# OV half-slot costs
OV_HALF_SLOTS: dict[str, int] = {
    "S": 1,
    "M": 2,
    "L": 3,
    "XL": 4,
}

# A tote costs 2 HALF-slots — i.e. exactly ONE full cart slot. All capacity
# arithmetic is in half-slots (×2) to keep OV fractions integral; don't read
# this as "a tote takes two slots". OVs add half-slots per OV_HALF_SLOTS.
TOTE_HALF_SLOTS = 2


# ---------------------------------------------------------------------------
# Sort request — addresses are ephemeral, never stored
# ---------------------------------------------------------------------------

class PackageInput(BaseModel):
    tba_number: str
    bag_id: str
    block_key: Optional[str] = None            # pre-computed from enriched Redis manifest
    normalised_address: Optional[str] = None   # from GeoClient — used for BuildingProfile lookup
    package_type: Optional[str] = None         # "OV_S"|"OV_M"|"OV_L"|"OV_XL"|"standard"|None
    lat: Optional[float] = None
    lng: Optional[float] = None
    first_cross_street: Optional[str] = None   # from GeoClient — used for BFS adjacency
    second_cross_street: Optional[str] = None  # from GeoClient — used for BFS adjacency


class SortRequest(BaseModel):
    truck_assignment_id: UUID
    route_date: date
    packages: list[PackageInput]
    # walker_count removed — routes are computed first, people assigned second
    # ovs removed — OV pairings are derived server-side from bag_id + package_type


# ---------------------------------------------------------------------------
# Sort result — no addresses in any output
# ---------------------------------------------------------------------------

class MisroutedPackageOut(BaseModel):
    tba_number: Optional[str] = None
    current_bag_id: Optional[str] = None
    destination_block_key: Optional[str] = None        # block_key it belongs to
    suggested_route_number: Optional[int] = None       # None = needs captain review


class RouteOut(BaseModel):
    """One cart trip — the output unit of the sort algorithm."""
    route_number: int
    block_keys: list[str]
    tote_ids: list[str]
    tba_numbers: list[str]
    slot_cost: int                  # half-slots
    capacity_limit: int             # half-slots
    effort_class: str               # easy|standard|heavy|very_heavy
    effort_score: float = 0.0       # weighted normalized score snapshot
    workload_source: str            # address_profile|block_profile|flag|default
    package_count: int
    coverage_pct: float = 0.0       # fraction of packages with locked BuildingProfile
    normalised_addresses: list[str] = []
    misrouted_packages: list[MisroutedPackageOut] = []


class SortResult(BaseModel):
    truck_assignment_id: UUID
    route_date: date
    routes: list[RouteOut]
    unassigned_misroutes: list[MisroutedPackageOut]   # no destination route found


# ---------------------------------------------------------------------------
# Wave distribution — assigning people to routes
# ---------------------------------------------------------------------------

class WaveAssignmentEntry(BaseModel):
    route_number: int
    employee_id: UUID


class WaveDistributionRequest(BaseModel):
    """Assign routes to confirmed staff at the anchor point.

    When auto_assign=True the server returns a WaveDistributionProposal without
    committing anything. The trainer reviews, adjusts, then resubmits with
    auto_assign=False and the finalized assignments list.
    When auto_assign=False (default) assignments must be fully populated.
    """
    truck_assignment_id: UUID
    route_date: date
    assignments: list[WaveAssignmentEntry] = []
    # Optional at the schema level: auto_assign=True is a PROPOSAL-ONLY call
    # (ADR-139 §5 — nothing is committed; the auto branch never reads
    # trainer_id) and the frontend sends null/omits it there. Requiring a UUID
    # here 422'd every auto-propose. The endpoint enforces trainer_id where it
    # is actually consumed: the manual branch's trainee-pairing sync.
    trainer_id: Optional[UUID] = None
    trainee_id: Optional[UUID] = None
    trainee_phase: Optional[int] = Field(None, ge=1, le=5)
    auto_assign: bool = False


class RouteReassignRequest(BaseModel):
    """Move a single route from its current assignee to a new one."""
    new_employee_id: UUID
    new_employee_name: str


# ---------------------------------------------------------------------------
# Arrival confirmation — triggers 1.5× rebalance
# ---------------------------------------------------------------------------

class ArrivalConfirmRequest(BaseModel):
    truck_assignment_id: UUID
    route_date: date
    trainer_id: UUID
    trainee_id: UUID


class ArrivalConfirmResponse(BaseModel):
    sort_not_yet_committed: bool
    paired_route: Optional["RouteResponse"]
    absorbed_route_numbers: list[int]
    trimmed_route_numbers: list[int]
    paired_capacity_limit: int


# ---------------------------------------------------------------------------
# DB response schemas
# ---------------------------------------------------------------------------

class RouteResponse(BaseModel):
    id: UUID
    truck_assignment_id: UUID
    route_date: date
    route_number: int
    wave_number: int = 1
    block_keys: list[str]
    tote_ids: list[str]
    tba_numbers: list[str]
    normalised_addresses: list[str] = []
    slot_cost: int
    capacity_limit: int
    capacity_limit_paired: Optional[int] = None
    package_count: int
    effort_class: str
    effort_score: Optional[float] = None
    workload_source: str
    coverage_pct: Optional[float] = None
    assigned_to: Optional[UUID] = None
    assigned_to_name: Optional[str] = None
    paired_trainee_id: Optional[UUID] = None
    trainee_phase: Optional[int] = None
    phase4_solo_opted_in: bool
    status: str
    departed_at: Optional[datetime] = None
    returned_at: Optional[datetime] = None
    created_at: datetime
    misrouted_packages: list["MisroutedPackageFlagResponse"] = []
    model_config = ConfigDict(from_attributes=True)


class RouteStatusPatch(BaseModel):
    status: Literal["assigned", "in_progress", "completed"]


# ---------------------------------------------------------------------------
# Wave pool — second-wave return mechanic
# ---------------------------------------------------------------------------

class ReturnedWalkerRoute(BaseModel):
    route_number: int
    wave_number: int
    package_count: int
    effort_class: str


class ReturnedWalker(BaseModel):
    employee_id: UUID
    employee_name: str
    injury_status: Optional[str] = None
    completed_routes: list[ReturnedWalkerRoute]


class UnassignedRouteEntry(BaseModel):
    route_id: UUID
    route_number: int
    effort_class: str
    package_count: int
    slot_cost: int
    wave_number: int


class WaveStatusCounts(BaseModel):
    assigned: int = 0
    in_progress: int = 0
    completed: int = 0
    unassigned: int = 0


class WaveSummary(BaseModel):
    """Per-wave status breakdown, keyed by wave number (1-based string key).

    Returned as {"1": {...}, "2": {...}, ...} — clients iterate over keys
    rather than hardcoded field names so any number of waves is supported.
    """
    waves: dict[str, WaveStatusCounts]
    total_routes: int


class WavePoolResponse(BaseModel):
    returned_walkers: list[ReturnedWalker]
    unassigned_routes: list[UnassignedRouteEntry]
    wave_summary: WaveSummary


# ---------------------------------------------------------------------------
# Wave distribution — auto_assign proposal mode
# ---------------------------------------------------------------------------

class ProposedAssignmentEntry(BaseModel):
    route_number: int
    route_id: UUID
    employee_id: UUID
    employee_name: str
    effort_class: str
    auto_proposed: bool = False


class WaveDistributionProposal(BaseModel):
    """Returned when auto_assign=True — trainer reviews before confirming."""
    proposed_assignments: list[ProposedAssignmentEntry]
    conflicts: list[str]   # human-readable strings when injury constraints can't be fully satisfied


# ---------------------------------------------------------------------------
# Commit sort — persist Route rows from SortResult
# ---------------------------------------------------------------------------

class CommitSortRequest(BaseModel):
    """Commit a route sort for a truck assignment.

    Server loads packages from the enriched Redis manifest via TruckZone.package_tbas.
    OV pairings are derived server-side from bag_id grouping + package_type — the
    trainer does not need to supply them.
    """
    truck_assignment_id: UUID
    route_date: date


class CommitSortResponse(BaseModel):
    routes: list[RouteResponse]
    packages_sorted: int
    packages_dropped: int
    dropped_tbas: list[str]
    unassigned_misroutes: list[MisroutedPackageOut]


# ---------------------------------------------------------------------------
# Difficulty flags and misroutes
# ---------------------------------------------------------------------------

class LocationDifficultyFlagCreate(BaseModel):
    block_key: str
    difficulty_tier: Literal["standard", "moderate", "heavy"]
    notes: Optional[str] = Field(None, max_length=500)


class LocationDifficultyFlagResponse(BaseModel):
    id: UUID
    block_key: str
    difficulty_tier: str
    flagged_by: Optional[UUID] = None
    flagged_at: datetime
    notes: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


class MisroutedPackageFlagResponse(BaseModel):
    id: UUID
    route_id: UUID
    tba_number: str
    current_bag_id: str
    destination_block_key: Optional[str] = None
    suggested_route_id: Optional[UUID] = None
    resolved: bool
    resolved_by: Optional[UUID] = None
    resolved_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


class MisrouteResolveRequest(BaseModel):
    destination_route_id: UUID


# Phase 4 opt-in
class Phase4OptInRequest(BaseModel):
    route_number: int
    truck_assignment_id: UUID
    route_date: date



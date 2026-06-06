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

# workload_class → effort_class (from LocationProfile)
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

TOTE_HALF_SLOTS = 2


# ---------------------------------------------------------------------------
# Sort request — addresses are ephemeral, never stored
# ---------------------------------------------------------------------------

class OVInput(BaseModel):
    sort_zone: str = Field(..., description="Warehouse staging locator, e.g. 'A-12'")
    size_tier: Literal["XL", "L", "M", "S"]
    paired_bag_id: str = Field(..., description="Bag ID this OV accompanies, e.g. 'Green 5270'")


class PackageInput(BaseModel):
    tba_number: str
    tag_number: Optional[str] = None
    bag_id: str
    address: str        # ephemeral — used only during sort, never persisted
    lat: Optional[float] = None
    lng: Optional[float] = None


class SortRequest(BaseModel):
    truck_assignment_id: UUID
    route_date: date
    packages: list[PackageInput]
    ovs: list[OVInput] = []
    # walker_count removed — routes are computed first, people assigned second


# ---------------------------------------------------------------------------
# Sort result — no addresses in any output
# ---------------------------------------------------------------------------

class MisroutedPackageOut(BaseModel):
    tba_number: str
    tag_number: Optional[str]
    current_bag_id: str
    destination_block_key: Optional[str]        # block_key it belongs to
    suggested_route_number: Optional[int]       # None = needs captain review


class RouteOut(BaseModel):
    """One cart trip — the output unit of the sort algorithm."""
    route_number: int
    block_keys: list[str]
    tote_ids: list[str]
    tba_numbers: list[str]
    tag_numbers: list[str]
    slot_cost: int                  # half-slots
    capacity_limit: int             # half-slots
    effort_class: str               # easy|standard|heavy
    workload_source: str            # profile|flag|default
    package_count: int
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

    The client sends the final assignment map after the trainer reviews the
    auto-distribution and makes any manual adjustments.
    """
    truck_assignment_id: UUID
    route_date: date
    assignments: list[WaveAssignmentEntry]
    trainer_id: UUID
    trainee_id: Optional[UUID] = None
    trainee_phase: Optional[int] = Field(None, ge=1, le=5)


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


class RebalanceOffer(BaseModel):
    """Presented for heavy routes — trainer must explicitly accept."""
    route_number: int
    effort_class: str
    workload_source: str
    current_slot_cost: int
    paired_capacity_limit: int
    absorbable_tote_ids: list[str]
    absorbable_package_count: int


class ArrivalConfirmResponse(BaseModel):
    rebalanced_route_numbers: list[int]        # standard/easy routes auto-rebalanced
    heavy_offers: list[RebalanceOffer]         # heavy routes needing manual accept


class AcceptRebalanceRequest(BaseModel):
    route_number: int
    truck_assignment_id: UUID
    route_date: date


# ---------------------------------------------------------------------------
# DB response schemas
# ---------------------------------------------------------------------------

class RouteResponse(BaseModel):
    id: UUID
    truck_assignment_id: UUID
    route_date: date
    route_number: int
    block_keys: list[str]
    tote_ids: list[str]
    tba_numbers: list[str]
    tag_numbers: list[str]
    slot_cost: int
    capacity_limit: int
    capacity_limit_paired: Optional[int] = None
    package_count: int
    effort_class: str
    workload_source: str
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


class WalkerRouteResponse(BaseModel):
    id: UUID
    truck_assignment_id: UUID
    route_date: date
    employee_id: UUID
    total_routes: int
    total_packages: int
    total_bags: int
    total_slot_cost: int
    created_at: datetime
    routes: list[RouteResponse] = []
    model_config = ConfigDict(from_attributes=True)


class RouteStatusPatch(BaseModel):
    status: Literal["assigned", "in_progress", "completed"]


# ---------------------------------------------------------------------------
# Commit sort — persist Route rows from SortResult
# ---------------------------------------------------------------------------

class CommitSortRequest(BaseModel):
    """Commit a route sort for a truck assignment.

    Server loads packages from the enriched Redis manifest via
    TruckZone.package_tbas. OV pairings require physical observation by the
    trainer and are supplied by the client.
    """
    truck_assignment_id: UUID
    route_date: date
    ovs: list[OVInput] = []


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
    tag_number: Optional[str] = None
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


# ---------------------------------------------------------------------------
# Walker assignment — pairing walkers to committed routes
# ---------------------------------------------------------------------------

class AssignWalkersRequest(BaseModel):
    """Map sorted walker routes to real employees.

    walker_ids must be ordered to match walker_index values from the sort
    result (index 0 → first walker ID, etc.).
    """
    walker_ids: list[UUID]


# ---------------------------------------------------------------------------
# Walker trip schemas
# ---------------------------------------------------------------------------

class WalkerTripResponse(BaseModel):
    id: UUID
    company_id: UUID
    walker_route_id: UUID
    trip_number: int
    status: str
    departed_at: Optional[datetime] = None
    returned_at: Optional[datetime] = None
    suggested_walker_route_id: Optional[UUID] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class WalkerTripStatusPatch(BaseModel):
    status: Literal["in_progress", "completed"]

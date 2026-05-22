from datetime import date, datetime
from uuid import UUID
from typing import Optional, Literal
from pydantic import BaseModel, ConfigDict, Field


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
    address: str  # ephemeral — used only during sort, never persisted


class SortRequest(BaseModel):
    truck_assignment_id: UUID
    route_date: date
    walker_count: int = Field(..., ge=1, le=30)
    packages: list[PackageInput]
    ovs: list[OVInput] = []


# ---------------------------------------------------------------------------
# Sort result — no addresses in any output
# ---------------------------------------------------------------------------

class MisroutedPackageOut(BaseModel):
    tba_number: str
    tag_number: Optional[str]
    current_bag_id: str
    suggested_cluster_index: Optional[int]  # None = needs captain review


class TripOut(BaseModel):
    trip_number: int
    bag_ids: list[str]
    tba_numbers: list[str]
    tag_numbers: list[str]
    package_count: int
    difficulty_tier: str


class WalkerRouteOut(BaseModel):
    walker_index: int               # 0-based position in walker list
    total_packages: int
    total_bags: int
    total_ovs: int
    planned_trips: int
    trips: list[TripOut]
    misrouted_packages: list[MisroutedPackageOut]


class SortResult(BaseModel):
    truck_assignment_id: UUID
    route_date: date
    walker_routes: list[WalkerRouteOut]
    unassigned_misroutes: list[MisroutedPackageOut]  # no cluster match anywhere in manifest


# ---------------------------------------------------------------------------
# DB response schemas
# ---------------------------------------------------------------------------

class WalkerTripResponse(BaseModel):
    id: UUID
    walker_route_id: UUID
    trip_number: int
    bag_ids: list[str]
    tba_numbers: list[str]
    tag_numbers: list[str]
    status: str
    departed_at: Optional[datetime] = None
    returned_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


class WalkerRouteResponse(BaseModel):
    id: UUID
    truck_assignment_id: UUID
    route_date: date
    walker_id: UUID
    total_packages: int
    total_bags: int
    total_ovs: int
    planned_trips: int
    actual_trips: Optional[int] = None
    completed_at: Optional[datetime] = None
    created_at: datetime
    trips: list[WalkerTripResponse] = []
    model_config = ConfigDict(from_attributes=True)


class WalkerTripStatusPatch(BaseModel):
    status: Literal["pending", "in_progress", "completed"]


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
    walker_route_id: UUID
    tba_number: str
    tag_number: Optional[str] = None
    current_bag_id: str
    suggested_walker_route_id: Optional[UUID] = None
    resolved: bool
    resolved_by: Optional[UUID] = None
    resolved_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


class AssignWalkersRequest(BaseModel):
    """After a sort preview is accepted, bind the walker_route rows to real walker IDs."""
    walker_ids: list[UUID] = Field(..., description="Ordered list matching walker_index in SortResult")

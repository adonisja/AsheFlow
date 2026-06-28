from datetime import datetime, time
from typing import Optional, Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# RTS Package
# ---------------------------------------------------------------------------

RtsType = Literal[
    "no_access",
    "business_closed",
    "package_damaged",
    "inclement_weather",
    "customer_requested_future_delivery",
    "customer_cancelled_order",
]

MissingResolutionStatus = Literal[
    "unresolved",
    "found_misroute",
    "found_other",
    "confirmed_missing",
]

ReattemptStatus = Literal[
    "pending",
    "assigned",
    "attempted",
    "delivered",
    "failed_again",
]


class RTSPackageCreate(BaseModel):
    route_id: UUID
    tba_number: str
    rts_type: RtsType
    rts_explanation: str = Field(..., min_length=1)


class RTSPackageResponse(BaseModel):
    id: UUID
    company_id: UUID
    route_id: UUID
    truck_assignment_id: UUID
    tba_number: str
    normalised_address: Optional[str] = None
    rts_type: str
    rts_explanation: str
    is_reattemptable: bool
    walker_id: Optional[UUID] = None
    walker_name: Optional[str] = None
    recorded_at: datetime
    delivery_stop_id: Optional[UUID] = None
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Missing Package
# ---------------------------------------------------------------------------

class MissingPackageCreate(BaseModel):
    route_id: UUID
    tba_number: str


class MissingPackageResolveRequest(BaseModel):
    resolution_status: Literal["found_misroute", "found_other", "confirmed_missing"]
    misroute_flag_id: Optional[UUID] = None   # required when found_misroute
    resolution_notes: Optional[str] = None    # required when found_other or confirmed_missing


class MissingPackageResponse(BaseModel):
    id: UUID
    company_id: UUID
    route_id: UUID
    truck_assignment_id: UUID
    tba_number: str
    normalised_address: Optional[str] = None
    walker_id: Optional[UUID] = None
    walker_name: Optional[str] = None
    reported_at: datetime
    resolution_status: str
    misroute_flag_id: Optional[UUID] = None
    resolution_notes: Optional[str] = None
    resolved_by: Optional[UUID] = None
    resolved_by_name: Optional[str] = None
    resolved_at: Optional[datetime] = None
    delivery_stop_id: Optional[UUID] = None
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Route Handoff
# ---------------------------------------------------------------------------

class RouteHandoffResponse(BaseModel):
    id: UUID
    company_id: UUID
    route_id: UUID
    truck_assignment_id: UUID
    walker_id: Optional[UUID] = None
    walker_name: Optional[str] = None
    driver_id: Optional[UUID] = None
    driver_name: Optional[str] = None
    rts_count: int
    missing_count: int
    rts_package_ids: list[UUID]
    driver_confirmed_at: Optional[datetime] = None
    discrepancy_flagged: bool
    discrepancy_notes: Optional[str] = None
    discrepancy_resolved_by: Optional[UUID] = None
    discrepancy_resolved_by_name: Optional[str] = None
    discrepancy_resolved_at: Optional[datetime] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class RouteHandoffConfirmRequest(BaseModel):
    """Driver confirms receipt or flags a discrepancy. Not mutually exclusive."""
    discrepancy_flagged: bool = False
    discrepancy_notes: Optional[str] = None


class RouteHandoffResolveRequest(BaseModel):
    """Dispatch resolves a flagged discrepancy."""
    pass   # resolved_by derived from caller; no extra fields needed


# ---------------------------------------------------------------------------
# Reattempt Assignment
# ---------------------------------------------------------------------------

class ReattemptAssignmentCreate(BaseModel):
    rts_package_id: UUID
    assigned_to: Optional[UUID] = None


class ReattemptAssignmentUpdate(BaseModel):
    assigned_to: Optional[UUID] = None
    route_id: Optional[UUID] = None
    status: Optional[ReattemptStatus] = None
    outcome_notes: Optional[str] = None


class ReattemptAssignmentResponse(BaseModel):
    id: UUID
    company_id: UUID
    rts_package_id: UUID
    truck_assignment_id: UUID
    assigned_by: Optional[UUID] = None
    assigned_by_name: Optional[str] = None
    original_walker_id: Optional[UUID] = None
    original_walker_name: Optional[str] = None
    assigned_to: Optional[UUID] = None
    assigned_to_name: Optional[str] = None
    route_id: Optional[UUID] = None
    status: str
    bundle_suggested_at: Optional[datetime] = None
    cutoff_at: datetime
    outcome_notes: Optional[str] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class BundleSuggestion(BaseModel):
    """Proximity-based bundle suggestion returned to the captain/driver."""
    rts_package_ids: list[UUID]
    tba_numbers: list[str]
    block_keys: list[str]
    package_count: int


# ---------------------------------------------------------------------------
# Building profile operating hours (patch schema)
# ---------------------------------------------------------------------------

class OperatingHoursPatch(BaseModel):
    opens_at: Optional[time] = None
    closes_at: Optional[time] = None
    break_start: Optional[time] = None
    break_end: Optional[time] = None
    days_open: Optional[list[str]] = None   # ["Mon","Tue","Wed","Thu","Fri"]
    hours_timezone: Optional[str] = Field(None, max_length=50)


# ---------------------------------------------------------------------------
# Delivery Stop
# ---------------------------------------------------------------------------

class DeliveryStopCreate(BaseModel):
    route_id: UUID
    tba_numbers: list[str] = Field(..., min_length=1)
    completed_at: datetime


class DeliveryStopResponse(BaseModel):
    id: UUID
    company_id: UUID
    route_id: UUID
    truck_assignment_id: UUID
    walker_id: Optional[UUID] = None
    walker_name: Optional[str] = None
    normalised_address: str
    block_key: str
    tba_numbers: list[str]
    completed_at: datetime
    stop_sequence: int
    packages_total: int
    packages_delivered: int
    rts_count: int
    missing_count: int
    effort_class: str
    workload_class: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


class StopSignal(BaseModel):
    """One priority signal attached to a suggested next stop."""
    signal: str          # closing_soon | break_approaching | not_open_yet | closed_today | high_wait | rts_history
    reason: str          # human-readable string surfaced to the walker
    urgency: int         # 1 (highest) – 5 (lowest), used for sorting


class BagGroup(BaseModel):
    """TBA numbers grouped by their physical bag/tote container."""
    bag_id: str
    tba_numbers: list[str]


class NextStopSuggestion(BaseModel):
    """One uncompleted stop entry in the next-suggestion list."""
    normalised_address: str
    block_key: str
    tba_numbers: list[str]
    bags: list[BagGroup]           # packages grouped by bag_id for dock-side prep
    packages_total: int
    signals: list[StopSignal]
    urgency_score: int             # sum of signal urgency values; lower = more urgent
    # BuildingProfile / library join — null when no profile exists for this address
    building_type:      Optional[str] = None
    workload_class:     Optional[str] = None
    operational_note:   Optional[str] = None
    protocol_reminder:  Optional[str] = None
    has_locked_profile: bool = False

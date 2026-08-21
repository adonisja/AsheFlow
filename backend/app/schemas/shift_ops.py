from datetime import date, datetime, time
from uuid import UUID
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Crew Compliance
# ---------------------------------------------------------------------------

class CrewComplianceEntry(BaseModel):
    employee_id: UUID
    arrival_time: Optional[time] = None
    uniform_pass: bool = True
    cart_cover_pass: bool = True


class CrewComplianceCreate(BaseModel):
    driver_id: UUID
    date: date
    entries: List[CrewComplianceEntry] = Field(..., min_length=1)


class CrewComplianceResponse(BaseModel):
    id: UUID
    driver_id: UUID
    employee_id: UUID
    date: date
    arrival_time: Optional[time] = None
    uniform_pass: bool
    cart_cover_pass: bool
    status: str = "submitted"   # draft | submitted (ADR-228)
    submitted_at: datetime
    model_config = ConfigDict(from_attributes=True)


class CrewComplianceDraftUpsert(BaseModel):
    """One member's uniform/cart-cover, saved live on the shared Crew Roster page
    as a DRAFT (ADR-228). The record is keyed to the truck's DRIVER, but that is
    resolved server-side from the caller's own assignment (any captain may record
    it) — no driver_id is accepted from the client (anti-spoof)."""
    date: date
    employee_id: UUID
    uniform_pass: bool
    cart_cover_pass: bool
    arrival_time: Optional[time] = None


# ---------------------------------------------------------------------------
# Driver Check-In
# ---------------------------------------------------------------------------

class DriverCheckInCreate(BaseModel):
    driver_id: UUID
    date: date
    check_in_number: int = Field(..., ge=1, le=4)
    routes_remaining: int = Field(..., ge=0)
    help_requested: bool = False
    working_crew_count: int = Field(..., ge=0)
    ncns_count: int = Field(0, ge=0)


class DriverCheckInResponse(BaseModel):
    id: UUID
    driver_id: UUID
    date: date
    check_in_number: int
    routes_remaining: int
    help_requested: bool
    working_crew_count: int
    ncns_count: int
    submitted_at: datetime
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# RTS Report (field submission — dispatch approval gate)
# ---------------------------------------------------------------------------

class RTSPackageEntry(BaseModel):
    reason: str = Field(..., min_length=1, max_length=100)
    count: int = Field(..., ge=0)


class RTSReportCreate(BaseModel):
    driver_id: UUID
    date: date
    crew_confirmed: int = Field(..., ge=0, description="Number of crew members accounted for on the truck")
    rts_packages: List[RTSPackageEntry]


class RTSReportReview(BaseModel):
    status: str  # "approved" | "rejected"
    dispatch_notes: Optional[str] = Field(None, max_length=500)


class RTSReportResponse(BaseModel):
    id: UUID
    driver_id: UUID
    date: date
    crew_confirmed: int
    rts_packages: List[Dict[str, Any]]
    total_rts: int
    status: str
    dispatch_notes: Optional[str] = None
    reviewed_by: Optional[UUID] = None
    reviewed_by_name: Optional[str] = None
    submitted_at: datetime
    reviewed_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Station Handoff (physical return at the station — closes the loop)
# ---------------------------------------------------------------------------

class StationHandoffCreate(BaseModel):
    driver_id: UUID
    date: date
    totes_returned: int = Field(..., ge=0)
    rts_count: int = Field(..., ge=0, description="Physical RTS packages handed back at the station")
    notes: Optional[str] = Field(None, max_length=500)


class StationHandoffResponse(BaseModel):
    id: UUID
    driver_id: UUID
    date: date
    totes_returned: int
    rts_count: int
    missing_count: int = 0
    notes: Optional[str] = None
    submitted_at: datetime
    model_config = ConfigDict(from_attributes=True)

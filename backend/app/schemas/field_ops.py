from datetime import date, datetime
from uuid import UUID
from typing import Optional, Dict, List
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

# Base64-encoded images can be large; cap at 5 MB (as a UTF-8 string length).
# A 5 MB binary image becomes ~6.7 MB as base64 — this cap is intentionally
# generous to allow high-res photos while preventing unbounded DB writes.
_MAX_PHOTO_BYTES = 5 * 1024 * 1024  # 5 MB


def _validate_photo_url(v: Optional[str]) -> Optional[str]:
    if v is not None and len(v.encode("utf-8")) > _MAX_PHOTO_BYTES:
        raise ValueError("photo_url exceeds the 5 MB size limit.")
    return v


class CheckInCreate(BaseModel):
    employee_id: UUID
    date: date
    photo_url: Optional[str] = None

    @field_validator("photo_url")
    @classmethod
    def check_photo_size(cls, v):
        return _validate_photo_url(v)


class CheckInResponse(CheckInCreate):
    id: UUID
    checked_in_at: datetime
    model_config = ConfigDict(from_attributes=True)


class DepartureCreate(BaseModel):
    employee_id: UUID
    date: date
    itinerary_photo_url: Optional[str] = None

    @field_validator("itinerary_photo_url")
    @classmethod
    def check_photo_size(cls, v):
        return _validate_photo_url(v)


class DepartureResponse(DepartureCreate):
    id: UUID
    departed_at: datetime
    returned_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


class WalkerRatingCreate(BaseModel):
    """Peer rating (ADR-201). rater is the authenticated caller — never trusted
    from the body. Attendance is roll call's job now, so a rating is stars+comment."""
    ratee_id: UUID
    date: date
    stars: int = Field(..., ge=1, le=5)
    comment: Optional[str] = Field(None, max_length=500)


class WalkerRatingResponse(BaseModel):
    id: UUID
    rater_id: UUID
    ratee_id: UUID
    date: date
    stars: int
    comment: Optional[str] = None
    rated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class FuelMileageLogCreate(BaseModel):
    driver_id: UUID
    date: date
    odometer_start: float
    notes: Optional[str] = Field(None, max_length=500)


class FuelMileageLogPatch(BaseModel):
    odometer_end: Optional[float] = None
    fuel_added: Optional[float] = None
    notes: Optional[str] = Field(None, max_length=500)


class FuelMileageLogResponse(BaseModel):
    id: UUID
    driver_id: UUID
    truck_id: Optional[UUID] = None
    date: date
    odometer_start: float
    odometer_end: Optional[float] = None
    fuel_added: Optional[float] = None
    notes: Optional[str] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class FuelMileageSummaryItem(BaseModel):
    log_id: UUID
    driver_name: str
    truck_name: Optional[str]
    date: date
    odometer_start: float
    odometer_end: Optional[float]
    distance: Optional[float]   # odometer_end - odometer_start
    fuel_added: Optional[float]


class VehicleInspectionCreate(BaseModel):
    driver_id: UUID
    date: date
    inspection_type: str = "pre_trip"  # "pre_trip" | "eod"
    # item_name → True (pass) / False (fail); StrictBool rejects int/string coercion
    items: Dict[str, StrictBool]
    notes: Optional[str] = Field(None, max_length=500)


class VehicleInspectionResponse(BaseModel):
    id: UUID
    driver_id: UUID
    truck_id: Optional[UUID] = None
    date: date
    inspection_type: str
    items: Dict[str, bool]
    has_failures: bool
    notes: Optional[str] = None
    submitted_at: datetime
    model_config = ConfigDict(from_attributes=True)


class VehicleInspectionSummaryItem(BaseModel):
    inspection_id: UUID
    driver_name: str
    truck_name: Optional[str]
    date: date
    inspection_type: str
    has_failures: bool
    submitted_at: datetime
    failed_items: List[str]


class StationArrivalCreate(BaseModel):
    employee_id: UUID
    date: date
    arrival_type: str  # "loading" | "return"
    # Staging check — only relevant for "loading" arrivals
    was_staged: Optional[bool] = None
    missing_items: Optional[List[str]] = None  # subset of STAGING_ITEMS


class StationArrivalResponse(BaseModel):
    id: UUID
    driver_id: UUID
    date: date
    arrival_type: str
    arrived_at: datetime
    was_staged: Optional[bool] = None
    missing_items: Optional[List[str]] = None
    model_config = ConfigDict(from_attributes=True)


class ManifestAcknowledgeResponse(BaseModel):
    id: UUID
    truck_id: UUID
    date: date
    tote_count: int
    ov_count: int
    notes: Optional[str] = None
    submitted_by: Optional[UUID] = None
    submitted_at: datetime
    acknowledged_by: Optional[UUID] = None
    acknowledged_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


class DockAssignmentCreate(BaseModel):
    driver_id: UUID
    date: date
    dock_zone: str = Field(..., min_length=1, max_length=50)


class DockAssignmentPatch(BaseModel):
    dock_zone: str = Field(..., min_length=1, max_length=50)


class DockAssignmentResponse(BaseModel):
    id: UUID
    driver_id: UUID
    date: date
    dock_zone: str
    assigned_by: Optional[UUID] = None
    assigned_at: datetime
    model_config = ConfigDict(from_attributes=True)

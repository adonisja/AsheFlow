from datetime import date, datetime
from uuid import UUID
from typing import Optional, Dict, List
from pydantic import BaseModel, ConfigDict


class CheckInCreate(BaseModel):
    employee_id: UUID
    date: date
    photo_url: Optional[str] = None


class CheckInResponse(CheckInCreate):
    id: UUID
    checked_in_at: datetime
    model_config = ConfigDict(from_attributes=True)


class DepartureCreate(BaseModel):
    employee_id: UUID
    date: date
    itinerary_photo_url: Optional[str] = None


class DepartureResponse(DepartureCreate):
    id: UUID
    departed_at: datetime
    returned_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


class WalkerRatingCreate(BaseModel):
    driver_id: UUID
    walker_id: UUID
    date: date
    present: bool = True
    stars: Optional[int] = None   # null for no-shows
    comment: Optional[str] = None


class WalkerRatingResponse(WalkerRatingCreate):
    id: UUID
    rated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class FuelMileageLogCreate(BaseModel):
    driver_id: UUID
    date: date
    odometer_start: int
    notes: Optional[str] = None


class FuelMileageLogPatch(BaseModel):
    odometer_end: Optional[int] = None
    fuel_added: Optional[int] = None
    notes: Optional[str] = None


class FuelMileageLogResponse(BaseModel):
    id: UUID
    driver_id: UUID
    truck_id: Optional[UUID] = None
    date: date
    odometer_start: int
    odometer_end: Optional[int] = None
    fuel_added: Optional[int] = None
    notes: Optional[str] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class FuelMileageSummaryItem(BaseModel):
    log_id: UUID
    driver_name: str
    truck_name: Optional[str]
    date: date
    odometer_start: int
    odometer_end: Optional[int]
    distance: Optional[int]   # odometer_end - odometer_start
    fuel_added: Optional[int]


class VehicleInspectionCreate(BaseModel):
    driver_id: UUID
    date: date
    # item_name → True (pass) / False (fail)
    items: Dict[str, bool]
    notes: Optional[str] = None


class VehicleInspectionResponse(BaseModel):
    id: UUID
    driver_id: UUID
    truck_id: Optional[UUID] = None
    date: date
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
    has_failures: bool
    submitted_at: datetime
    failed_items: List[str]

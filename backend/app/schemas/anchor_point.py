from datetime import date, datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, field_validator


class AnchorPointCreate(BaseModel):
    truck_id: UUID
    date: date
    location: str            # cross street or address — geocoded server-side (ADR-206)
    eta: str                 # mandatory (ADR-206) — driver's stated arrival time
    borough: Optional[str] = None  # geocode override; falls back to CompanyConfig → manhattan
    notes: Optional[str] = None
    expected_departure_at: Optional[datetime] = None  # relocation only — when driver expects to leave current AP

    @field_validator("location", "eta")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must not be empty")
        return v.strip()


class AnchorPointArriveUpdate(BaseModel):
    location: Optional[str] = None   # driver may update location on arrival
    notes: Optional[str] = None


class AnchorPointDepartUpdate(BaseModel):
    pass  # no body needed — departure time is server-stamped


class AnchorPointResponse(BaseModel):
    id: UUID
    truck_id: UUID
    driver_id: UUID
    date: date
    sequence: int
    is_initial: bool
    status: str
    location: str
    lat: Optional[float] = None
    lng: Optional[float] = None
    eta: Optional[str] = None
    notes: Optional[str] = None
    submitted_at: datetime
    arrived_at: Optional[datetime] = None
    expected_departure_at: Optional[datetime] = None
    actual_departed_at: Optional[datetime] = None
    is_running_late: bool = False
    running_late_flagged_at: Optional[datetime] = None
    confirmed_by: Optional[UUID] = None
    confirmed_by_name: Optional[str] = None
    confirmed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}

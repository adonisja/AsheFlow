from datetime import date, datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel


class AnchorPointCreate(BaseModel):
    truck_id: UUID
    date: date
    location: str
    eta: Optional[str] = None
    notes: Optional[str] = None
    expected_departure_at: Optional[datetime] = None  # relocation only — when driver expects to leave current AP


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
    eta: Optional[str] = None
    notes: Optional[str] = None
    submitted_at: datetime
    arrived_at: Optional[datetime] = None
    expected_departure_at: Optional[datetime] = None
    actual_departed_at: Optional[datetime] = None
    is_running_late: bool = False
    running_late_flagged_at: Optional[datetime] = None
    confirmed_by: Optional[UUID] = None
    confirmed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}

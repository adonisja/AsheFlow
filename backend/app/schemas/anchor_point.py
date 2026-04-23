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


class AnchorPointResponse(BaseModel):
    id: UUID
    truck_id: UUID
    driver_id: UUID
    date: date
    location: str
    eta: Optional[str] = None
    notes: Optional[str] = None
    submitted_at: datetime
    confirmed_by: Optional[UUID] = None
    confirmed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}

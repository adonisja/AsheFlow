from datetime import date
from pydantic import BaseModel
from typing import Optional
from uuid import UUID


class TruckAssignmentCreate(BaseModel):
    truck_id: UUID
    date: date


class TruckAssignmentUpdate(BaseModel):
    status: Optional[str] = None


class TruckAssignmentResponse(BaseModel):
    id: UUID
    truck_id: UUID
    truck_name: str = ""
    date: date
    status: str

    model_config = {"from_attributes": True}

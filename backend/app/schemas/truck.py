from pydantic import BaseModel
from typing import Optional
from uuid import UUID


class TruckCreate(BaseModel):
    name: str


class TruckUpdate(BaseModel):
    name: Optional[str] = None


class TruckResponse(BaseModel):
    id: UUID
    name: str
    is_active: bool

    model_config = {"from_attributes": True}

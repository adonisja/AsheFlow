from pydantic import BaseModel, Field
from typing import Optional
from uuid import UUID


class TruckCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    discord_channel_id: Optional[int] = None


class TruckUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    discord_channel_id: Optional[int] = None


class TruckResponse(BaseModel):
    id: UUID
    name: str
    is_active: bool
    discord_channel_id: Optional[int] = None

    model_config = {"from_attributes": True}

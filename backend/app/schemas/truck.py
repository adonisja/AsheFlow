from pydantic import BaseModel
from typing import Optional
from uuid import UUID


class TruckCreate(BaseModel):
    name: str
    discord_channel_id: Optional[int] = None


class TruckUpdate(BaseModel):
    name: Optional[str] = None
    discord_channel_id: Optional[int] = None


class TruckResponse(BaseModel):
    id: UUID
    name: str
    is_active: bool
    discord_channel_id: Optional[int] = None

    model_config = {"from_attributes": True}

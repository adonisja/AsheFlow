from pydantic import BaseModel, Field, field_serializer
from typing import Optional
from uuid import UUID
from datetime import datetime


class TruckCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    discord_channel_id: Optional[int] = None


class TruckUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    discord_channel_id: Optional[int] = None


class TruckAnchorPatch(BaseModel):
    address: Optional[str] = Field(None, max_length=300)
    borough: Optional[str] = Field(None, max_length=30)


class TruckResponse(BaseModel):
    id: UUID
    name: str
    is_active: bool
    discord_channel_id: Optional[int] = None
    initial_anchor_address: Optional[str] = None
    initial_anchor_display_address: Optional[str] = None
    initial_anchor_lat: Optional[float] = None
    initial_anchor_lng: Optional[float] = None
    initial_anchor_set_at: Optional[datetime] = None

    model_config = {"from_attributes": True}

    @field_serializer("discord_channel_id")
    def serialize_snowflake(self, v: Optional[int]) -> Optional[str]:
        # Discord snowflake IDs exceed Number.MAX_SAFE_INTEGER; return as string.
        return str(v) if v is not None else None

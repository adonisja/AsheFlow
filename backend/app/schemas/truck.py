from pydantic import BaseModel, Field, field_serializer
from typing import Optional
from uuid import UUID
from datetime import datetime


class TruckCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    # ADR-274: a hub is excluded from run_dispatch and staffed by hand. Set at
    # creation on the trucks admin page, where discord_channel_id is already
    # configured — so the hub's Discord room needs no separate setting.
    is_hub: bool = False
    discord_channel_id: Optional[int] = None


class TruckUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    is_hub: Optional[bool] = None
    discord_channel_id: Optional[int] = None


class TruckAnchorPatch(BaseModel):
    address: Optional[str] = Field(None, max_length=300)
    borough: Optional[str] = Field(None, max_length=30)


class TruckAnchor2Patch(BaseModel):
    """Set or clear anchor point 2. Pass address=None to remove it."""
    address: Optional[str] = Field(None, max_length=300)
    borough: Optional[str] = Field(None, max_length=30)


class TruckResponse(BaseModel):
    id: UUID
    name: str
    is_active: bool
    is_hub: bool = False
    discord_channel_id: Optional[int] = None
    initial_anchor_address: Optional[str] = None
    initial_anchor_display_address: Optional[str] = None
    initial_anchor_lat: Optional[float] = None
    initial_anchor_lng: Optional[float] = None
    initial_anchor_set_at: Optional[datetime] = None
    initial_anchor2_address: Optional[str] = None
    initial_anchor2_display_address: Optional[str] = None
    initial_anchor2_lat: Optional[float] = None
    initial_anchor2_lng: Optional[float] = None
    initial_anchor2_set_at: Optional[datetime] = None

    model_config = {"from_attributes": True}

    @field_serializer("discord_channel_id")
    def serialize_snowflake(self, v: Optional[int]) -> Optional[str]:
        # Discord snowflake IDs exceed Number.MAX_SAFE_INTEGER; return as string.
        return str(v) if v is not None else None

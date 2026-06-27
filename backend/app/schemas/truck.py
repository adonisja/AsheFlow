from pydantic import BaseModel, Field, field_serializer
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

    @field_serializer("discord_channel_id")
    def serialize_snowflake(self, v: Optional[int]) -> Optional[str]:
        # Discord snowflake IDs exceed Number.MAX_SAFE_INTEGER; return as string.
        return str(v) if v is not None else None

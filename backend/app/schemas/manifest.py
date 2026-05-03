from datetime import date, datetime
from uuid import UUID
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class PackageManifestCreate(BaseModel):
    truck_id: UUID
    date: date
    tote_count: int = Field(0, ge=0)
    ov_count: int = Field(0, ge=0)
    notes: Optional[str] = Field(None, max_length=500)


class PackageManifestPatch(BaseModel):
    tote_count: Optional[int] = Field(None, ge=0)
    ov_count: Optional[int] = Field(None, ge=0)
    notes: Optional[str] = Field(None, max_length=500)


class PackageManifestResponse(BaseModel):
    id: UUID
    truck_id: UUID
    date: date
    tote_count: int
    ov_count: int
    notes: Optional[str] = None
    submitted_by: Optional[UUID] = None
    submitted_at: datetime
    model_config = ConfigDict(from_attributes=True)

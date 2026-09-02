"""Crew pin request/response schemas (ADR-357).

Request models carry concrete types, bounded lengths and extra="forbid" —
CLAUDE.md Dimension 9: a request body is attacker-controlled input, and `Any` or
an unbounded string is accepted unvalidated.
"""
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CrewPinCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=80)
    driver_id: UUID
    # A crew larger than a truck holds is a data-entry error, not a request.
    member_ids: List[UUID] = Field(default_factory=list, max_length=30)


class CrewPinUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(None, min_length=1, max_length=80)
    member_ids: Optional[List[UUID]] = Field(None, max_length=30)
    is_active: Optional[bool] = None


class CrewPinMemberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    employee_id: UUID
    name: Optional[str] = None
    role: Optional[str] = None


class CrewPinResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    driver_id: UUID
    driver_name: Optional[str] = None
    is_active: bool
    inactive_reason: Optional[str] = None
    created_at: datetime
    members: List[CrewPinMemberResponse] = Field(default_factory=list)

from datetime import date, datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, Field


class RollCallCreate(BaseModel):
    employee_id: UUID
    date: date
    notes: Optional[str] = None
    # status is not accepted from the client — derived server-side from time.
    # NCNS is the one exception: caller must explicitly pass ncns=True.
    ncns: bool = False


class RollCallConfirm(BaseModel):
    pass  # no body needed — identity comes from the auth token


class RollCallOverride(BaseModel):
    """Dispatch/admin only — update status or notes on an existing record."""
    status: str = Field(..., pattern="^(early|present|late|ncns)$")
    notes: Optional[str] = None


class RollCallResponse(BaseModel):
    id: UUID
    company_id: UUID
    submitted_by_id: Optional[UUID]
    employee_id: UUID
    date: date
    status: str
    notes: Optional[str]
    submitted_at: datetime
    updated_at: Optional[datetime]
    updated_by_id: Optional[UUID]
    confirmed: bool
    confirmed_at: Optional[datetime]

    model_config = {"from_attributes": True}


class RollCallSummaryEntry(BaseModel):
    """One row in the dispatch summary view — includes employee name and role.

    id and submitted_at are None when no roll call record exists yet for this
    crew member (status='pending' is a synthetic state, not a DB row).
    """
    id: Optional[UUID]
    employee_id: UUID
    employee_name: str
    role: str
    truck_name: Optional[str]
    status: str  # 'early' | 'present' | 'late' | 'ncns' | 'pending' (not yet submitted)
    confirmed: bool
    submitted_by_name: Optional[str]
    submitted_at: Optional[datetime]
    notes: Optional[str]

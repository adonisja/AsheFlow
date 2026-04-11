from pydantic import BaseModel, ConfigDict
from uuid import UUID
from datetime import date, datetime
from typing import Optional


class AssignmentChangeRequestCreate(BaseModel):
    employee_id: UUID
    requested_date: date
    reason: Optional[str] = None


class AssignmentChangeRequestResponse(BaseModel):
    id: UUID
    employee_id: UUID
    requested_date: date
    reason: Optional[str] = None
    status: str
    reviewed_by: Optional[UUID] = None
    created_at: datetime
    resolved_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

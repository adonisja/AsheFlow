from pydantic import BaseModel, ConfigDict
from uuid import UUID
from datetime import datetime
from typing import Optional


class ContinuationRequestCreate(BaseModel):
    trainee_id: UUID
    trainer_id: UUID


class ContinuationRequestResponse(BaseModel):
    id: UUID
    trainee_id: UUID
    trainer_id: UUID
    status: str
    priority: Optional[int] = None
    created_at: datetime
    resolved_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class PriorityUpdate(BaseModel):
    # None clears the priority (sets to unranked)
    priority: Optional[int] = None

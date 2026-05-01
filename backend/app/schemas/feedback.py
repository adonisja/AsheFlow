from pydantic import BaseModel, Field
from typing import Optional
from uuid import UUID
from datetime import datetime

class FeedbackBase(BaseModel):
    employee_id: Optional[UUID] = None
    type: str = Field(..., description="Type of feedback: bug, feature_request, general")
    message: str = Field(..., max_length=2000, description="The feedback message")

class FeedbackCreate(FeedbackBase):
    pass

class FeedbackResponse(FeedbackBase):
    id: UUID
    status: str
    created_at: datetime
    sender_name: Optional[str] = None

    class Config:
        from_attributes = True


class FeedbackStatusUpdate(BaseModel):
    status: str

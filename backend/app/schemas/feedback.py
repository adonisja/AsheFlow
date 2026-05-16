from pydantic import BaseModel, Field
from typing import Optional, Literal
from uuid import UUID
from datetime import datetime

class FeedbackBase(BaseModel):
    employee_id: Optional[UUID] = None
    type: Literal["bug", "feature_request", "general"] = Field(..., description="Type of feedback: bug, feature_request, general")
    message: str = Field(..., max_length=2000, description="The feedback message")

class FeedbackCreate(FeedbackBase):
    pass

class FeedbackResponse(FeedbackBase):
    id: UUID
    status: Literal["new", "in_progress", "resolved"]
    created_at: datetime
    sender_name: Optional[str] = None

    model_config = {"from_attributes": True}


class FeedbackStatusUpdate(BaseModel):
    status: Literal["new", "in_progress", "resolved"]


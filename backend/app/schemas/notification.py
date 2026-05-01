from datetime import datetime, date
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict


class NotificationResponse(BaseModel):
    id: UUID
    employee_id: UUID
    type: str
    message: str
    is_read: bool
    created_at: datetime
    dispatch_date: Optional[date] = None

    model_config = ConfigDict(from_attributes=True)

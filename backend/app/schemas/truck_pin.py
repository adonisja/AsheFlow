"""Truck pin request/response schemas (ADR-358)."""
from datetime import datetime
from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Weekday = Literal[
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"
]


class TruckPinCreate(BaseModel):
    """Pin one employee to one truck on one or more weekdays.

    `days` is a Literal, not a free string: an unrecognised weekday would pass a
    length check and then fail the DB CHECK as a 500 instead of a 422.
    """

    model_config = ConfigDict(extra="forbid")

    employee_id: UUID
    truck_id: UUID
    days: List[Weekday] = Field(..., min_length=1, max_length=7)


class TruckPinResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    employee_id: UUID
    employee_name: Optional[str] = None
    employee_role: Optional[str] = None
    truck_id: UUID
    truck_name: Optional[str] = None
    day_of_week: str
    created_at: datetime

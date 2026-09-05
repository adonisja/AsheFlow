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


class TruckPinRetruck(BaseModel):
    """Move every one of an employee's truck pins to a different truck (ADR-373).

    Only `truck_id`. Not the employee -- changing who a pin is for is not an edit
    of that pin, it is a different pin, and silently reassigning one detaches it
    from its audit trail. Not the days either: those are added and removed
    individually, which is what the day chips already do.
    """

    model_config = ConfigDict(extra="forbid")

    truck_id: UUID


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

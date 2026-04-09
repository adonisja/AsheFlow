import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

class ManualAssignmentCreate(BaseModel):
    """Schema for manually assigning an employee to a truck for a specific date."""
    employee_id: UUID = Field(..., description="UUID of the employee to assign")
    truck_id: UUID = Field(..., description="UUID of the truck")
    role: Literal["driver", "trainer", "walker"] = Field(..., description="Role for the assignment")
    date: datetime.date = Field(..., description="Date of the assignment")

class ManualAssignmentUpdate(BaseModel):
    """Schema for swapping an employee to a different truck or role on a specific date."""
    employee_id: UUID = Field(..., description="UUID of the employee to move")
    date: datetime.date = Field(..., description="Date of the assignment being modified")
    new_truck_id: UUID = Field(..., description="UUID of the destination truck")
    new_role: Literal["driver", "trainer", "walker"] | None = Field(None, description="Optional new role for the assignment")



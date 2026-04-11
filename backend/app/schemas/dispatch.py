import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

class DispatchConfig(BaseModel):
    date: Optional[datetime.date] = Field(None, description="Date to run dispatch for")
    total_employees: Optional[int] = Field(None, description="Total number of employees to assign across all trucks")
    total_trucks: Optional[int] = Field(None, description="Total amount of trucks to dispatch")

class ManualAssignmentCreate(BaseModel):
    """Schema for manually assigning an employee to a truck for a specific date."""
    employee_id: UUID = Field(..., description="UUID of the employee to assign")
    truck_id: UUID = Field(..., description="UUID of the truck")
    role: Literal["driver", "trainer", "trainee", "walker"] = Field(..., description="Role for the assignment")
    date: datetime.date = Field(..., description="Date of the assignment")

class ManualAssignmentUpdate(BaseModel):
    """Schema for swapping an employee to a different truck or role on a specific date."""
    employee_id: UUID = Field(..., description="UUID of the employee to move")
    date: datetime.date = Field(..., description="Date of the assignment being modified")
    new_truck_id: UUID = Field(..., description="UUID of the destination truck")
    new_role: Optional[Literal["driver", "trainer", "trainee", "walker"]] = Field(None, description="Optional new role for the assignment")



import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

class DispatchConfig(BaseModel):
    date: Optional[datetime.date] = Field(None, description="Date to run dispatch for")
    total_employees: Optional[int] = Field(None, description="Total number of employees to assign across all trucks")
    total_trucks: Optional[int] = Field(None, description="DEPRECATED fallback — first-N trucks by name. Prefer truck_ids.")
    truck_ids: Optional[list[UUID]] = Field(None, description="Explicit trucks to dispatch (ADR-202). Seeds exactly these; count is derived.")

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


# ── ADR-199 Phase B: trainer-absent day-of reassignment (dispatch only) ─────────

class AvailableTrainer(BaseModel):
    """A trainee-less trainer dispatch can reassign an orphaned trainee to."""
    trainer_id: UUID
    trainer_name: Optional[str] = None
    truck_assignment_id: UUID
    truck_id: UUID
    truck_name: Optional[str] = None
    same_truck: bool = Field(..., description="True if this trainer is on the trainee's current truck (no transfer needed)")
    has_route: bool = Field(..., description="True if this trainer already has a route to join (post-sort)")


class AvailableTrainersResponse(BaseModel):
    trainee_id: UUID
    trainee_name: Optional[str] = None
    current_trainer_id: Optional[UUID] = None
    suggestions: list[AvailableTrainer]


class ReassignTraineeRequest(BaseModel):
    """Dispatch confirms moving an orphaned trainee to a chosen new trainer."""
    trainee_id: UUID = Field(..., description="Trainee whose trainer is late/absent")
    new_trainer_id: UUID = Field(..., description="Chosen trainer (must be trainee-less; from the suggestion list)")
    date: datetime.date = Field(..., description="Dispatch date")


class ReassignTraineeResponse(BaseModel):
    trainee_id: UUID
    new_trainer_id: UUID
    new_truck_assignment_id: UUID
    transferred: bool = Field(..., description="True if the trainee was moved to a different truck")
    joined_route: bool = Field(..., description="True if the new trainer had a committed route the trainee joined")
    paired_capacity_limit: Optional[int] = None



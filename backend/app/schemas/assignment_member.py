from pydantic import BaseModel, Field
from typing import Literal, Optional
from uuid import UUID
from datetime import datetime, date


class AssignmentMemberCreate(BaseModel):
    assignment_id: UUID
    employee_id: UUID
    role: str


class AssignmentMemberResponse(BaseModel):
    id: UUID
    company_id: UUID
    assignment_id: UUID
    employee_id: UUID
    role: str
    paired_trainer_id: Optional[UUID] = None
    status: str = "active"
    departed_at: Optional[datetime] = None
    trip_count: int = 0            # ADR-199 D3: completed-and-returned runs today

    model_config = {"from_attributes": True}


class AssignmentMemberStatusUpdate(BaseModel):
    """Dispatch/captain marks a crew member departed or transferred (ADR-197)."""
    status: Literal["departed", "transferred"]
    reason: Optional[str] = Field(None, max_length=500)


class CrewAvailabilityEntry(BaseModel):
    """Derived per-member availability (ADR-197 Phase 0b): membership status +
    route-execution progress, so F5 route-creation knows who can take a route."""
    employee_id: UUID
    name: Optional[str] = None
    role: str
    membership_status: str                    # active | departed | transferred
    # available    = active, no in-progress route → can take a route now
    # on_route_early = active, on a route ≤ threshold complete → NOT available this wave
    # on_route_returning = active, on a route > threshold complete → route can wait for them
    # done         = active, finished & back at truck → available
    # off_crew     = departed/transferred → not counted
    availability: str
    route_completion_pct: Optional[float] = None


class CrewAvailabilityResponse(BaseModel):
    entries: list[CrewAvailabilityEntry]
    active_crew: int                 # members with membership_status = active
    available_for_route: int         # count that can take a NEW route this wave
    completion_threshold: float      # the pct above which an on-route walker counts as returning


# ── Crew Status page (ADR-197 Phase B) — enriched, fleet-aware ──────────────────

class CrewStatusMember(BaseModel):
    """One crew member on the Crew Status page: availability (ADR-197 Phase 0b) +
    trip count (ADR-199 D3) + pairing (with an orphaned-trainee flag → Phase B
    reassignment). member_id is the AssignmentMember row id (for the depart/status
    action); it is None only if the membership row is missing (should not happen)."""
    member_id: Optional[UUID] = None
    employee_id: UUID
    name: Optional[str] = None
    role: str
    membership_status: str                    # active | departed | transferred
    availability: str                         # not_arrived|available|on_route_early|on_route_returning|done|off_crew
    route_completion_pct: Optional[float] = None
    trip_count: int = 0
    # Pairing (ADR-199): trainee → their trainer; trainer → their trainee.
    paired_trainer_id: Optional[UUID] = None
    paired_trainer_name: Optional[str] = None
    paired_trainee_id: Optional[UUID] = None
    paired_trainee_name: Optional[str] = None
    # True for a trainee whose paired trainer is not present on the truck (not an
    # active member, or has not arrived at the AP while the trainee has). Drives
    # the "Reassign" entry point to the Phase B dispatch reassignment.
    orphaned: bool = False


class CrewStatusTruck(BaseModel):
    truck_assignment_id: UUID
    truck_id: UUID
    truck_name: Optional[str] = None
    active_crew: int
    available_for_route: int
    members: list[CrewStatusMember]


class CrewStatusResponse(BaseModel):
    date: date
    completion_threshold: float
    trucks: list[CrewStatusTruck]

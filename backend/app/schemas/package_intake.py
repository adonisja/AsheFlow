"""Unregistered package intake (ADR-246).

No address fields anywhere in a response. Dimension 7 forbids addresses in
output schemas, and ADR-219 nulls them 48h post-route regardless — the TBA and
the route number are what an operator needs to act. Addresses are accepted on
*input* (the walker read one off a label) but never returned.
"""
from datetime import date, datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class IntakeCandidate(BaseModel):
    """A route that could take the package."""
    route_id: UUID
    route_number: Optional[int] = None
    walker_name: Optional[str] = None
    status: Optional[str] = None
    can_accept: bool
    match: str                       # address | block_key | none
    is_adders_route: bool = False


class IntakeAssessmentOut(BaseModel):
    """What the system decided, before anything was written.

    Returned by the dry-run preview and echoed on a completed intake, so the
    caller can show *why* a package landed where it did.
    """
    in_zone: bool
    decidable: bool
    zone_reason: Optional[str] = None      # no_coords | no_boundary | outside
    best_fit: Optional[IntakeCandidate] = None
    adders_route: Optional[IntakeCandidate] = None
    candidates: List[IntakeCandidate] = Field(default_factory=list)
    absorbed_reason: Optional[str] = None


class PackageIntakeRequest(BaseModel):
    """A package found in a tote that was never registered.

    `block_key` and `normalised_address` come from the label capture step; both
    are optional because a geocode failure still has to reach dispatch rather
    than being rejected at the edge (ADR-246).
    """
    tba: str = Field(..., min_length=4, max_length=50)
    block_key: Optional[str] = Field(None, max_length=120)
    normalised_address: Optional[str] = Field(None, max_length=300)
    lat: Optional[float] = Field(None, ge=-90, le=90)
    lng: Optional[float] = Field(None, ge=-180, le=180)
    route_date: Optional[date] = None
    # Walker override: "I know Route 7 is a better fit, I am taking it anyway."
    # Advisory best-fit is a warning, not a gate (ADR-246).
    accept_override: bool = False


class DispatchAssignRequest(PackageIntakeRequest):
    """Dispatch may name the target route instead of accepting the best fit."""
    route_id: Optional[UUID] = None


class PackageIntakeResponse(BaseModel):
    """What actually happened.

    `outcome` is the branch the caller must switch on:
      added          — on a route, stop opened
      duplicate      — already registered; holder named, nothing written
      removal        — not ours; PackageRemoval opened for the custody chain
      needs_dispatch — undecidable (no coords/boundary, or no accepting route)
    """
    outcome: str
    tba: str
    route_id: Optional[UUID] = None
    route_number: Optional[int] = None
    walker_name: Optional[str] = None
    stop_id: Optional[UUID] = None
    removal_id: Optional[UUID] = None
    reason: Optional[str] = None
    # Populated on outcome="duplicate" — naming the holder is the point, a bare
    # refusal makes the walker go find out who has it (ADR-246).
    existing_holder: Optional[str] = None
    existing_route_number: Optional[int] = None
    assessment: Optional[IntakeAssessmentOut] = None


class FieldAddedPackage(BaseModel):
    """One field-added package, for dispatch oversight."""
    tba: str
    route_id: Optional[UUID] = None
    route_number: Optional[int] = None
    walker_name: Optional[str] = None
    added_by_name: Optional[str] = None
    added_at: datetime
    outcome: str
    is_unplanned: bool = True


class FieldAddedResponse(BaseModel):
    """Dispatch's oversight feed.

    Answers "what got added to my routes today", which is dispatch's actual
    question — not "what happened", which is what the audit log answers and
    which dispatch cannot read anyway (GET /audit is management+admin).
    """
    route_date: date
    total: int
    packages: List[FieldAddedPackage] = Field(default_factory=list)

"""Operational package lookup (ADR-245).

Dispatch needs to answer "who has this package?" from a TBA alone. Every
existing read is route-scoped, so locating a package meant already knowing its
route — backwards for the question actually being asked.

Distinct from /scorecards/packages/search, which serves appeal evidence and is
Tier 3 (management/admin). This is operational tracking: dispatch-visible,
and it reports a package's whole timeline rather than only its exceptions.
"""
from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel


class AssignmentTrace(BaseModel):
    """The package was planned onto a route. True before any delivery happens.

    walker_name is the route's EXECUTOR (ADR-212/244) — the person the route
    belongs to, which is who dispatch means by "who has it".
    """
    route_id: str
    route_number: Optional[int] = None
    route_date: date
    route_status: Optional[str] = None
    walker_id: Optional[str] = None
    walker_name: Optional[str] = None
    truck_name: Optional[str] = None


class DeliveryTrace(BaseModel):
    """A stop covering this package.

    walker_name is the stop's executor; recorded_by is whoever actually
    completed it, which differs during supervision or peer coverage (ADR-244).
    """
    stop_id: str
    status: str                              # planned | in_progress | completed
    stop_sequence: Optional[int] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    walker_id: Optional[str] = None
    walker_name: Optional[str] = None
    recorded_by_name: Optional[str] = None
    packages_delivered: Optional[int] = None


class ExceptionTrace(BaseModel):
    """An RTS, missing or damaged record for this package.

    No normalised_address: Dimension 7 forbids addresses in output schemas, and
    ADR-219 nulls them 48h post-route regardless. The TBA identifies the package
    without exposing a customer's location.
    """
    source: str                              # rts | missing | damaged
    recorded_at: Optional[datetime] = None
    route_date: Optional[date] = None
    walker_name: Optional[str] = None
    recorded_by_name: Optional[str] = None
    rts_type: Optional[str] = None
    rts_explanation: Optional[str] = None
    is_reattemptable: Optional[bool] = None
    resolution_status: Optional[str] = None
    damage_stage: Optional[str] = None
    notes: Optional[str] = None


class PackageTimeline(BaseModel):
    """Everything known about one TBA, oldest signal first.

    `current_holder` is the single answer to "who has it" — resolved from the
    most specific trace available: a completed stop beats an in-progress one,
    which beats the route assignment. None when nothing is known.
    """
    tba_number: str
    current_holder_name: Optional[str] = None
    current_holder_id: Optional[str] = None
    holder_basis: Optional[str] = None       # delivered | in_progress | assigned | exception
    assignments: List[AssignmentTrace] = []
    deliveries: List[DeliveryTrace] = []
    exceptions: List[ExceptionTrace] = []


class PackageLookupResponse(BaseModel):
    query: str
    matched_on: str                          # suffix | exact | none
    ambiguous: bool = False                  # suffix matched >1 distinct TBA
    results: List[PackageTimeline] = []

"""Unregistered package intake (ADR-246).

Dimension 7: no address is returned by any schema that describes a ROUTE or a
STOP. ADR-219 nulls those 48h post-route regardless, and the TBA plus the route
number are what an operator needs to act on. Addresses are accepted on *input*
and never echoed back by the intake or oversight responses.

The one exception is `LabelReadResponse`, and it is deliberate: it hands back
the text just OCR'd from a photo the caller took seconds earlier, to the same
caller, so they can correct it before anything is written. It is not persisted,
not audited, and not logged — the address exists only for the life of that one
request, which is the ephemeral case Dimension 7 allows. `lines` carries the
other label text for the same reason, so a bad read can be fixed without a
second Textract call. Nothing here may be stored without revisiting that.
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
    match: str                       # address | block_key | near_segment | near_block
    # Distance in the unit of the tier that matched: graph hops for
    # near_segment, hundred-blocks for near_block. None on an exact match
    # (ADR-260). Separate from `match` so the UI states the unit rather than
    # implying a precision the tier does not have.
    distance: Optional[float] = None
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
    # Whether ANY route exists for the date (ADR-260). Lets the UI say "the day
    # is not sorted yet" rather than "no route is near", which would send a
    # dispatcher hunting a routing problem that is really a not-yet-run sort.
    routes_exist: bool = False


class PackageIntakeRequest(BaseModel):
    """A package found in a tote that was never registered.

    `block_key` and `normalised_address` come from the label capture step; both
    are optional because a geocode failure still has to reach dispatch rather
    than being rejected at the edge (ADR-246).
    """
    tba: str = Field(..., min_length=4, max_length=50)
    # No ov_size: a found package attaches to an existing stop, and DeliveryStop
    # has no size column to put it in. Accepting a field the server discards is
    # worse than not offering one — the dispatcher would believe they had
    # recorded something. Revisit if stop-level package sizing is ever added.
    block_key: Optional[str] = Field(None, max_length=120)
    normalised_address: Optional[str] = Field(None, max_length=300)
    lat: Optional[float] = Field(None, ge=-90, le=90)
    lng: Optional[float] = Field(None, ge=-180, le=180)
    # No route_date: the server always uses today (ADR-260). A found package is
    # in someone's hand now, so a client-chosen date has no physical meaning —
    # and accepting one let a caller write onto a closed day's routes.
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
      needs_dispatch — undecidable (no coords/boundary), or no route is near
                       enough / able to take it — a dispatch decision
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


class LabelReadResponse(BaseModel):
    """What OCR thinks is on the label — a SUGGESTION, never a commitment.

    The walker confirms both fields before anything is written. `confidence`
    and `needs_manual_entry` exist so the UI can flag a shaky read instead of
    presenting it as fact, and `lines` lets them pick a different line without
    a second Textract call.
    """
    tba: Optional[str] = None
    address_line: Optional[str] = None
    confidence: Optional[float] = None
    needs_manual_entry: bool
    lines: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


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

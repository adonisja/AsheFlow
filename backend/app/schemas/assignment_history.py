"""Past assignment history (ADR-268).

Response-only. There is no request body anywhere in this feature — the inputs
are a date range and, for the dispatch-scoped read, an employee id.

Dimension 7 note: `normalised_address` appears on RTSDetailOut and nowhere
else. It is a customer address, and it is returned ONLY while ADR-219's 48h
retention window is open; after that the column is null and the block key on
the stop is what survives. `address_detail` tells the client which it is
looking at, so a UI can say "block only" rather than appearing to lose data.
"""
from datetime import date
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class CrewMemberOut(BaseModel):
    """Someone else on the same truck that day."""
    name: str
    # The SLOT held that day (AssignmentMember.role), not the job title — a
    # captain-titled employee may ride as a walker (ADR-256 D2).
    role: str

    # Required on the NESTED models too, not just the outer ones. The service
    # returns dataclasses; without this Pydantic refuses to coerce them and the
    # endpoint 500s with "Input should be a valid dictionary or instance of
    # CrewMemberOut". The outer model having it is not inherited.
    model_config = ConfigDict(from_attributes=True)


class RTSDetailOut(BaseModel):
    tba_number: str
    rts_type: str
    rts_explanation: str
    is_reattemptable: bool
    # Null once ADR-219 has run. Not an error — see `address_detail`.
    normalised_address: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class AssignmentDayOut(BaseModel):
    route_date: date
    truck_name: Optional[str] = None
    slot_role: str
    crew: List[CrewMemberOut] = Field(default_factory=list)
    route_numbers: List[int] = Field(default_factory=list)

    stops_total: int = 0
    packages_total: int = 0
    packages_delivered: int = 0
    rts_count: int = 0
    missing_count: int = 0

    effort_class: Optional[str] = None
    rts_rate: Optional[float] = None
    # rts_rate / the company rate for the same effort_class.
    # 1.0 = exactly typical for a route of that difficulty.
    #
    # THIS is the fair cross-person comparison. Raw rts_rate ranks whoever drew
    # the hard routes worst: measured 2.10% easy vs 10.81% heavy on staging, a
    # 5x spread the walker does not control. Null when the class lacks the
    # volume to be a trustworthy denominator.
    rts_rate_vs_class: Optional[float] = None

    rts_details: List[RTSDetailOut] = Field(default_factory=list)
    address_detail: Literal["street", "block"] = "block"

    # Whose numbers the counts above are.
    #   "truck"  driver/captain — they answer for the whole load
    #   "own"    walker/trainer/trainee — only the stops they executed
    # The UI MUST label this. A walker's 142 and a driver's 2,865 are different
    # measurements, and showing them identically was the original bug.
    counts_scope: Literal["truck", "own"] = "own"

    model_config = ConfigDict(from_attributes=True)


class AssignmentHistoryResponse(BaseModel):
    employee_id: str
    start_date: date
    end_date: date
    days: List[AssignmentDayOut] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)

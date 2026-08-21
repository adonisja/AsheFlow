"""Read-only reconstruction of a past dispatch day (ADR-268).

Response-only; the endpoint takes a date in the path and nothing else.

No addresses appear anywhere here. The per-truck view reports RTS by REASON
(counts per rts_type), not by package — the individual TBAs and their
addresses live on the per-person view, and only inside ADR-219's 48h window.
A dispatcher scanning six trucks wants the shape of the day, not 200 rows.
"""
from datetime import date
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class MemberOutcomeOut(BaseModel):
    employee_id: str
    name: str
    slot_role: str
    packages_total: int = 0
    packages_delivered: int = 0
    rts_count: int = 0
    missing_count: int = 0
    # True for driver/captain. Their line is the TRUCK's load, not their own
    # stops, because they answer for the vehicle — the UI must say so, or the
    # row reads as one person who delivered thirty times more than the others.
    is_truck_lead: bool = False

    model_config = ConfigDict(from_attributes=True)


class TruckOutcomeOut(BaseModel):
    truck_id: str
    truck_name: Optional[str] = None
    route_numbers: List[int] = Field(default_factory=list)
    stops_total: int = 0
    packages_total: int = 0
    packages_delivered: int = 0
    rts_count: int = 0
    missing_count: int = 0
    effort_class: Optional[str] = None
    crew: List[MemberOutcomeOut] = Field(default_factory=list)
    # {rts_type: count} for the whole truck — the drill-down a dispatcher
    # reaches for after seeing a high return count.
    rts_reasons: Dict[str, int] = Field(default_factory=dict)

    model_config = ConfigDict(from_attributes=True)


class DayReplayOut(BaseModel):
    route_date: date
    trucks: List[TruckOutcomeOut] = Field(default_factory=list)
    # Summed from the TRUCK rows, never from the crew lines: a lead's line
    # already contains the whole load, so adding crew together double-counts
    # every package.
    packages_total: int = 0
    packages_delivered: int = 0
    rts_count: int = 0
    missing_count: int = 0

    model_config = ConfigDict(from_attributes=True)
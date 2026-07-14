"""Crew availability derivation (ADR-197 Phase 0b).

Combines the two axes of a person's day into "can they take a route this wave":
  - membership (AssignmentMember.status) — are they still on this truck?
  - route execution (Route.status/returned_at + DeliveryStop completion %) —
    are they free, or too deep into a route to take another?

F5 route-creation reads `available_for_route` to size the number of routes to
build (walker count is a CEILING, not a target — ADR-197). The completion
threshold decides whether a walker mid-route counts as available: below it they
can't take another route this wave; above it their next route can wait for them.

Pure-logic core (`derive_availability`) so it is unit-testable without a DB; the
router does the queries and passes plain rows in.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from uuid import UUID

# A walker more than this fraction through their current route counts as
# "returning" — a next route can be built to wait for them. At or below it they
# are still out for a while and don't count toward this wave's route capacity.
DEFAULT_COMPLETION_THRESHOLD = 0.65


@dataclass
class MemberProgress:
    """Flattened per-member inputs for availability (router builds these)."""
    employee_id: UUID
    name: Optional[str]
    role: str
    membership_status: str          # active | departed | transferred
    has_active_route: bool          # assigned/in_progress route not yet returned
    route_completion_pct: Optional[float]   # completed stops / total, None if no active route
    # Presence axis (ADR-198/199 roll call). None = on the crew but roll call has
    # not marked them present yet → 'not_arrived' (NOT available). True once a
    # ShiftRollCall marks them early/present/late. False = explicitly absent
    # (ncns) → off_crew. Default True keeps the F5 / route-sizing callers that do
    # not pass presence unchanged (commit-sort runs pre-arrival, roll call is not
    # its gate there).
    present: Optional[bool] = True


@dataclass
class Availability:
    employee_id: UUID
    name: Optional[str]
    role: str
    membership_status: str
    availability: str               # not_arrived | available | on_route_early | on_route_returning | done | off_crew
    route_completion_pct: Optional[float]


def classify_member(m: MemberProgress, threshold: float = DEFAULT_COMPLETION_THRESHOLD) -> Availability:
    if m.membership_status != "active" or m.present is False:
        # Departed/transferred, or explicitly absent (ncns) → not crew today.
        avail = "off_crew"
    elif m.present is None:
        # On the crew but roll call has not marked them present yet → Not Arrived.
        # Excluded from the available-for-route count until they are marked in.
        avail = "not_arrived"
    elif not m.has_active_route:
        # active + present, no route out → free to take one (freshly in, or done & back)
        avail = "available"
    elif m.route_completion_pct is not None and m.route_completion_pct > threshold:
        avail = "on_route_returning"   # near done — a next route can wait for them
    else:
        avail = "on_route_early"       # too early — not available this wave
    return Availability(
        employee_id=m.employee_id, name=m.name, role=m.role,
        membership_status=m.membership_status, availability=avail,
        route_completion_pct=m.route_completion_pct,
    )


def derive_availability(
    members: list[MemberProgress],
    threshold: float = DEFAULT_COMPLETION_THRESHOLD,
) -> tuple[list[Availability], int, int]:
    """Return (per-member availability, active_crew, available_for_route).

    available_for_route counts members who can take a NEW route this wave:
    `available` (free now) + `on_route_returning` (route can wait for them).
    Drivers are crew but not route-takers, so they are excluded from the
    route-taker count (they run the truck, not a walking route).
    """
    entries = [classify_member(m, threshold) for m in members]
    active_crew = sum(1 for e in entries if e.membership_status == "active")
    available_for_route = sum(
        1 for e in entries
        if e.role != "driver" and e.availability in ("available", "on_route_returning")
    )
    return entries, active_crew, available_for_route

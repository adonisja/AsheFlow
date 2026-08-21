"""What a past day actually ran — dispatch's read-only reconstruction (ADR-268).

`GET /dispatch/{date}` already returns the board for any date, but only the
PLAN: crews, zones, package_count. It says nothing about how the day went.

This adds the outcome half — delivered vs total, RTS, missing — per truck AND
per crew member, so dispatch can answer "what did we actually run on the 7th"
rather than "who did we intend to send".

WHY PER-MEMBER COUNTS ARE SCOPED
Same rule as assignment_history: a walker's numbers are the stops they
executed (DeliveryStop.walker_id, the EXECUTOR per ADR-244), and the truck
total is the sum over the whole load. Presenting a walker's line with the
truck's 2,865 packages was the bug that produced this rule; the per-member
breakdown exists precisely so the difference is visible.

Public module: read-only aggregation, no routing algorithm.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.assignment_member import AssignmentMember
from app.models.delivery_stop import DeliveryStop
from app.models.employee import Employee
from app.models.rts import RTSPackage
from app.models.truck import Truck
from app.models.truck_assignment import TruckAssignment
from app.models.walker_route import Route
from app.services.constants import TRUCK_SCOPED_ROLES

logger = logging.getLogger(__name__)


@dataclass
class MemberOutcome:
    employee_id: str
    name: str
    slot_role: str
    packages_total: int = 0
    packages_delivered: int = 0
    rts_count: int = 0
    missing_count: int = 0
    # True for driver/captain: their line is the truck's load, not their own
    # stops, because they answer for the vehicle. Without this flag a
    # driver's row looks like a walker who delivered 30x more.
    is_truck_lead: bool = False


@dataclass
class TruckOutcome:
    truck_id: str
    truck_name: Optional[str]
    route_numbers: list = field(default_factory=list)
    stops_total: int = 0
    packages_total: int = 0
    packages_delivered: int = 0
    rts_count: int = 0
    missing_count: int = 0
    effort_class: Optional[str] = None
    crew: list = field(default_factory=list)          # [MemberOutcome]
    # {rts_type: count} for the whole truck — the drill-down dispatch asks for
    # after seeing a high return count.
    rts_reasons: dict = field(default_factory=dict)


@dataclass
class DayReplay:
    route_date: date
    trucks: list = field(default_factory=list)
    packages_total: int = 0
    packages_delivered: int = 0
    rts_count: int = 0
    missing_count: int = 0


def get_day_replay(db: Session, company_id: UUID, day: date) -> DayReplay:
    """Reconstruct one past day: every truck, its crew, and how it went."""
    replay = DayReplay(route_date=day)

    assignments = (
        db.query(TruckAssignment)
        .filter(
            TruckAssignment.company_id == company_id,
            TruckAssignment.date == day,
        )
        .all()
    )
    if not assignments:
        return replay

    for ta in assignments:
        truck = db.query(Truck).filter(
            Truck.id == ta.truck_id, Truck.company_id == company_id).first()

        routes = (
            db.query(Route)
            .filter(
                Route.company_id == company_id,
                Route.truck_assignment_id == ta.id,
                Route.route_date == day,
            )
            .all()
        )
        route_ids = [r.id for r in routes]

        out = TruckOutcome(
            truck_id=str(ta.truck_id),
            truck_name=truck.name if truck else None,
            route_numbers=sorted(r.route_number for r in routes if r.route_number),
            effort_class=next((r.effort_class for r in routes if r.effort_class), None),
        )

        stops = []
        if route_ids:
            stops = (
                db.query(DeliveryStop)
                .filter(
                    DeliveryStop.company_id == company_id,
                    DeliveryStop.route_id.in_(route_ids),
                )
                .all()
            )
            out.stops_total = len(stops)
            out.packages_total = sum(s.packages_total or 0 for s in stops)
            out.packages_delivered = sum(s.packages_delivered or 0 for s in stops)
            out.rts_count = sum(s.rts_count or 0 for s in stops)
            out.missing_count = sum(s.missing_count or 0 for s in stops)

            # Why packages came back, for the whole truck. Counts rather than
            # rows: the individual TBAs are on the per-person view, and a
            # dispatcher scanning six trucks wants the shape, not 200 lines.
            for r in (
                db.query(RTSPackage)
                .filter(
                    RTSPackage.company_id == company_id,
                    RTSPackage.route_id.in_(route_ids),
                )
                .all()
            ):
                out.rts_reasons[r.rts_type] = out.rts_reasons.get(r.rts_type, 0) + 1

        # Per-member. Stops are grouped once in Python rather than one query
        # per crew member — a 33-person truck would otherwise be 33 queries.
        by_walker: dict = {}
        for s in stops:
            if s.walker_id:
                by_walker.setdefault(str(s.walker_id), []).append(s)

        members = (
            db.query(AssignmentMember, Employee)
            .join(Employee, Employee.id == AssignmentMember.employee_id)
            .filter(
                AssignmentMember.assignment_id == ta.id,
                AssignmentMember.company_id == company_id,
            )
            .all()
        )
        for am, emp in members:
            lead = am.role in TRUCK_SCOPED_ROLES
            mine = stops if lead else by_walker.get(str(emp.id), [])
            out.crew.append(MemberOutcome(
                employee_id=str(emp.id),
                name=emp.name,
                slot_role=am.role,
                packages_total=sum(s.packages_total or 0 for s in mine),
                packages_delivered=sum(s.packages_delivered or 0 for s in mine),
                rts_count=sum(s.rts_count or 0 for s in mine),
                missing_count=sum(s.missing_count or 0 for s in mine),
                is_truck_lead=lead,
            ))

        # Leads first, then the biggest workloads — a dispatcher scanning for
        # "who had a rough day" reads top-down.
        out.crew.sort(key=lambda m: (not m.is_truck_lead, -m.packages_total))
        replay.trucks.append(out)

        # Day totals come from the TRUCK rows, never from summing crew: a
        # driver's line already contains the whole load, so adding crew
        # together would count every package twice.
        replay.packages_total += out.packages_total
        replay.packages_delivered += out.packages_delivered
        replay.rts_count += out.rts_count
        replay.missing_count += out.missing_count

    replay.trucks.sort(key=lambda t: (t.truck_name or ""))
    return replay
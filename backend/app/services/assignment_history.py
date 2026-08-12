"""What a person actually worked on a past day (ADR-268).

Public by design: this is a read-only aggregation over completed records — no
routing algorithm, no dispatch weighting, nothing proprietary. It joins
AssignmentMember -> TruckAssignment -> Route -> DeliveryStop / RTSPackage and
counts.

TWO THINGS THAT SHAPE THE OUTPUT

1. Addresses expire. `null_expired_delivery_addresses` (ADR-219) nulls
   normalised_address on stops and RTS rows 48h after the route date, keeping
   block_key forever. So a recent day shows street addresses and an older one
   shows blocks. `address_detail` reports which, so a UI can say "block only"
   rather than looking like it lost data.

2. Difficulty is a confound. RTS rate on staging measures 2.10% on easy routes
   and 10.81% on heavy ones — 5x, for reasons the walker does not control. Any
   consumer comparing people MUST use rts_rate_vs_class, not rts_rate.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
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

# Beyond this age the address columns are null by policy, not by accident.
ADDRESS_RETENTION_HOURS = 48

# Company-wide RTS rate per effort class, used to normalise an individual's
# rate. Computed from the data rather than hardcoded: a fixed baseline would
# drift the moment the operation changes.
_MIN_CLASS_PACKAGES = 200   # below this the baseline is noise, so do not divide by it


@dataclass
class RTSDetail:
    tba_number: str
    rts_type: str
    rts_explanation: str
    is_reattemptable: bool
    # Street address while it exists (<=48h), else None — block_key is on the
    # stop and survives.
    normalised_address: Optional[str] = None


@dataclass
class AssignmentDay:
    route_date: date
    truck_name: Optional[str]
    slot_role: str                       # the role held THAT day, not the job title
    crew: list = field(default_factory=list)      # [{name, role}] excluding the caller
    route_numbers: list = field(default_factory=list)

    stops_total: int = 0
    packages_total: int = 0
    packages_delivered: int = 0
    rts_count: int = 0
    missing_count: int = 0

    effort_class: Optional[str] = None
    rts_rate: Optional[float] = None
    # rts_rate / company rate for the same effort_class. 1.0 = exactly typical
    # for a route of that difficulty. This is the ONLY fair cross-person
    # comparison; rts_rate alone punishes whoever drew the hard routes.
    rts_rate_vs_class: Optional[float] = None

    rts_details: list = field(default_factory=list)
    # "street" while addresses survive, "block" once ADR-219 has nulled them.
    address_detail: str = "block"
    # Whose numbers the counts above represent.
    #   "truck"  driver/captain — the whole load is theirs to answer for
    #   "own"    walker/trainer/trainee — only the stops they executed
    # Reported so the UI can label it. Without this a walker's 142 and a
    # driver's 2,865 look like the same measurement.
    counts_scope: str = "own"


def _class_baselines(db: Session, company_id: UUID) -> dict:
    """{effort_class: rts_rate} company-wide, for normalisation.

    Returns only classes with enough volume to be a meaningful denominator —
    dividing by a 12-package baseline would produce ratios that swing wildly on
    one return.
    """
    rows = (
        db.query(
            DeliveryStop.effort_class,
            DeliveryStop.rts_count,
            DeliveryStop.packages_total,
        )
        .filter(
            DeliveryStop.company_id == company_id,
            DeliveryStop.status == "completed",
            DeliveryStop.effort_class.isnot(None),
        )
        .all()
    )
    agg: dict = {}
    for effort, rts, pkgs in rows:
        a = agg.setdefault(effort, [0, 0])
        a[0] += rts or 0
        a[1] += pkgs or 0
    return {
        cls: rts / pkgs
        for cls, (rts, pkgs) in agg.items()
        if pkgs >= _MIN_CLASS_PACKAGES and pkgs > 0
    }


def get_assignment_history(
    db: Session,
    company_id: UUID,
    employee_id: UUID,
    start_date: date,
    end_date: date,
) -> list:
    """Past assignment days for one employee, newest first.

    Caller is responsible for authorisation — the endpoint decides whether
    `employee_id` may be someone other than the caller.
    """
    members = (
        db.query(AssignmentMember, TruckAssignment)
        .join(TruckAssignment, AssignmentMember.assignment_id == TruckAssignment.id)
        .filter(
            AssignmentMember.company_id == company_id,
            AssignmentMember.employee_id == employee_id,
            TruckAssignment.company_id == company_id,
            TruckAssignment.date >= start_date,
            TruckAssignment.date <= end_date,
        )
        .order_by(TruckAssignment.date.desc())
        .all()
    )
    if not members:
        return []

    baselines = _class_baselines(db, company_id)
    today = date.today()
    out: list = []

    for member, ta in members:
        truck = db.query(Truck).filter(
            Truck.id == ta.truck_id, Truck.company_id == company_id).first()

        # Who else was on that truck. Excludes the caller — they know they were
        # there — and reads names from Employee so a renamed person is current.
        crew_rows = (
            db.query(AssignmentMember, Employee)
            .join(Employee, Employee.id == AssignmentMember.employee_id)
            .filter(
                AssignmentMember.assignment_id == ta.id,
                AssignmentMember.company_id == company_id,
                AssignmentMember.employee_id != employee_id,
            )
            .all()
        )

        routes = (
            db.query(Route)
            .filter(
                Route.company_id == company_id,
                Route.truck_assignment_id == ta.id,
                Route.route_date == ta.date,
            )
            .all()
        )
        route_ids = [r.id for r in routes]

        day = AssignmentDay(
            route_date=ta.date,
            truck_name=truck.name if truck else None,
            slot_role=member.role,
            crew=[{"name": e.name, "role": m.role} for m, e in crew_rows],
            route_numbers=sorted(r.route_number for r in routes if r.route_number),
            effort_class=next((r.effort_class for r in routes if r.effort_class), None),
        )

        if route_ids:
            # WHOSE numbers are these?
            #
            # A driver or captain owns the truck: the whole load is theirs to
            # answer for, so they see every stop on it. A walker, trainer or
            # trainee carries their OWN stops — showing them the truck's 2,865
            # packages as if they delivered them is simply false, and it makes
            # every crew member on a truck look identical.
            #
            # walker_id is the stop's EXECUTOR (ADR-244) — "the walker the stop
            # belongs to", which is the same field get_my_performance scopes by.
            # Deliberately NOT recorded_by: a trainer completing a trainee's
            # stop during supervision does not make it the trainer's stop.
            stop_q = db.query(DeliveryStop).filter(
                DeliveryStop.company_id == company_id,
                DeliveryStop.route_id.in_(route_ids),
            )
            truck_wide = member.role in TRUCK_SCOPED_ROLES
            day.counts_scope = "truck" if truck_wide else "own"
            if not truck_wide:
                stop_q = stop_q.filter(DeliveryStop.walker_id == employee_id)
            stops = stop_q.all()
            day.stops_total = len(stops)
            day.packages_total = sum(s.packages_total or 0 for s in stops)
            day.packages_delivered = sum(s.packages_delivered or 0 for s in stops)
            day.rts_count = sum(s.rts_count or 0 for s in stops)
            day.missing_count = sum(s.missing_count or 0 for s in stops)

            rts_q = db.query(RTSPackage).filter(
                RTSPackage.company_id == company_id,
                RTSPackage.route_id.in_(route_ids),
            )
            if not truck_wide:
                # Same rule as the stops above: the packages THIS person carried
                # back, not everything that returned on the truck.
                rts_q = rts_q.filter(RTSPackage.walker_id == employee_id)
            rts_rows = rts_q.all()
            day.rts_details = [
                RTSDetail(
                    tba_number=r.tba_number,
                    rts_type=r.rts_type,
                    rts_explanation=r.rts_explanation,
                    is_reattemptable=r.is_reattemptable,
                    normalised_address=r.normalised_address,
                )
                for r in rts_rows
            ]

        if day.packages_total:
            day.rts_rate = day.rts_count / day.packages_total
            base = baselines.get(day.effort_class or "")
            if base:
                # Ratio, not difference: "1.4x typical for a heavy route" reads
                # correctly whatever the underlying rate is.
                day.rts_rate_vs_class = round(day.rts_rate / base, 2)

        # Derived from the RETENTION WINDOW, not from whether an address
        # happens to be present: "did we find one" would report "block" for a
        # recent day that simply had no RTS, which is a different fact.
        #
        # ADR-219 nulls addresses 48h after the route date, so a route_date
        # within the last 2 days still has them.
        cutoff = today - timedelta(days=ADDRESS_RETENTION_HOURS // 24)
        day.address_detail = "street" if ta.date > cutoff else "block"
        out.append(day)

    return out

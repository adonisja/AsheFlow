"""Operational signals for the At-Risk list (ADR-268).

WHY THIS EXISTS
`WalkerPerformance.tsx` computes At-Risk as, entirely:

    walkers.filter(w => w.grade === 'D' || w.grade === 'F')

Peer grade is the ONLY input. That is a popularity-adjacent measure standing
alone on a page with consequences attached, while the system already records
outcomes the person actually controls.

WHAT QUALIFIES AS A SIGNAL HERE
Outcomes, not opinions, and only ones the individual can influence:

  * RTS rate      packages coming back
  * missing count packages that never arrived anywhere

`Route.help_requested_at` was considered and REJECTED. Asking for help is
behaviour to encourage; counting it against someone teaches them to stop asking.

THE THING THAT MAKES RTS RATE USABLE AT ALL
It is confounded by route difficulty — measured 2.10% on easy routes against
10.81% on heavy, a 5x spread the walker does not choose. Ranking on the raw
rate puts whoever drew the hard work at the bottom. So this reports
`rts_rate_vs_class`: the person's rate divided by the company rate for the same
effort class. 1.0 is exactly typical for work of that difficulty.

Public module: read-only aggregation over completed records.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.delivery_stop import DeliveryStop

logger = logging.getLogger(__name__)

# Below this a person's own rate is noise: one bad stop on a light day swings
# it wildly, and flagging someone on 8 packages would be indefensible.
MIN_PACKAGES_FOR_SIGNAL = 100

# Same reasoning for the denominator — a class baseline built on a handful of
# packages is not a baseline.
_MIN_CLASS_PACKAGES = 200

# How far back the signals look. A quarter is long enough to accumulate volume
# and short enough that someone who has improved is not judged on last spring.
DEFAULT_LOOKBACK_DAYS = 90

# vs_class above this is "materially worse than peers on comparable work".
# 1.5 rather than 1.1: the point is to surface people who need support, not to
# rank everyone against the mean.
AT_RISK_VS_CLASS = 1.5


@dataclass
class OutcomeSignal:
    employee_id: str
    packages_total: int = 0
    packages_delivered: int = 0
    rts_count: int = 0
    missing_count: int = 0
    rts_rate: Optional[float] = None
    # rts_rate / company rate for the same effort_class, volume-weighted across
    # the classes this person actually worked. THE fair comparison.
    rts_rate_vs_class: Optional[float] = None
    # False when the person has not worked enough packages for any of this to
    # mean anything. A consumer MUST check this before flagging anyone.
    has_enough_volume: bool = False

    @property
    def is_at_risk(self) -> bool:
        """Materially worse than peers on comparable work.

        Deliberately a property rather than a stored flag: the thresholds are
        policy, and burying them in a column would make them invisible to
        whoever next asks "why is this person flagged".
        """
        return (
            self.has_enough_volume
            and self.rts_rate_vs_class is not None
            and self.rts_rate_vs_class >= AT_RISK_VS_CLASS
        )


def _class_baselines(db: Session, company_id: UUID, since: date) -> dict:
    """{effort_class: rts_rate} company-wide over the window."""
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


def get_outcome_signals(
    db: Session,
    company_id: UUID,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> dict:
    """{employee_id: OutcomeSignal} for everyone with completed stops.

    One pass over the window rather than a query per employee — the At-Risk
    list is rendered for the whole roster at once.
    """
    since = date.today() - timedelta(days=lookback_days)
    baselines = _class_baselines(db, company_id, since)

    stops = (
        db.query(DeliveryStop)
        .filter(
            DeliveryStop.company_id == company_id,
            DeliveryStop.status == "completed",
            DeliveryStop.walker_id.isnot(None),
        )
        .all()
    )

    # Per person, and per person PER CLASS: comparing someone's overall rate to
    # a single baseline would mis-rank anyone whose mix of easy and heavy work
    # differs from the company average. Their expected returns are computed from
    # the classes they actually worked.
    per_person: dict = {}
    per_person_class: dict = {}
    for s in stops:
        eid = str(s.walker_id)
        sig = per_person.setdefault(eid, OutcomeSignal(employee_id=eid))
        sig.packages_total += s.packages_total or 0
        sig.packages_delivered += s.packages_delivered or 0
        sig.rts_count += s.rts_count or 0
        sig.missing_count += s.missing_count or 0
        if s.effort_class:
            k = per_person_class.setdefault(eid, {}).setdefault(s.effort_class, 0)
            per_person_class[eid][s.effort_class] = k + (s.packages_total or 0)

    for eid, sig in per_person.items():
        sig.has_enough_volume = sig.packages_total >= MIN_PACKAGES_FOR_SIGNAL
        if sig.packages_total:
            sig.rts_rate = sig.rts_count / sig.packages_total

        # Expected returns = sum over the classes they worked of
        # (their packages in that class x the company rate for that class).
        expected = 0.0
        counted = 0
        for cls, pkgs in per_person_class.get(eid, {}).items():
            base = baselines.get(cls)
            if base is None:
                continue
            expected += pkgs * base
            counted += pkgs
        if expected > 0 and counted:
            sig.rts_rate_vs_class = round(sig.rts_count / expected, 2)

    return per_person

# ── Coverage depth (ADR-268) ─────────────────────────────────────────────────

@dataclass
class CoverageDepth:
    """How many people are CALLABLE beyond those already rostered, per role.

    Answers "are we one flu away from a stranded truck". A today number, which
    is why it belongs as a field on the management dashboard rather than a page
    of its own.

    Driver and captain are called out separately because either being short
    strands a whole vehicle (TRUCK_SCOPED_ROLES, ADR-256), where a walker short
    is a slower route.
    """
    assigned_drivers: int = 0
    spare_drivers: int = 0
    assigned_captains: int = 0
    spare_captains: int = 0
    assigned_walkers: int = 0
    spare_walkers: int = 0
    assigned_trainers: int = 0
    spare_trainers: int = 0
    at_capacity_risk: bool = False


def get_coverage_depth(db: Session, company_id: UUID, day: date) -> CoverageDepth:
    """Assigned vs spare per role for `day`.

    Spare = active field staff of that role who are NOT on a truck and NOT
    excluded by approved PTO or a recurring day off. Reuses the same exclusion
    rules as the dispatch pool so the two cannot disagree about who is
    available (ADR-267).
    """
    from app.models.assignment_member import AssignmentMember
    from app.models.employee import Employee
    from app.models.employee_off_day import EmployeeOffDay
    from app.models.time_off_request import TimeOffRequest
    from app.models.truck_assignment import TruckAssignment

    out = CoverageDepth()
    roles = ("driver", "captain", "walker", "trainer")

    staff = (
        db.query(Employee)
        .filter(
            Employee.company_id == company_id,
            Employee.is_active == True,           # noqa: E712
            Employee.role.in_(roles),
        )
        .all()
    )
    if not staff:
        return out
    ids = [e.id for e in staff]

    assigned = {
        r.employee_id
        for r in db.query(AssignmentMember)
        .join(TruckAssignment, AssignmentMember.assignment_id == TruckAssignment.id)
        .filter(
            TruckAssignment.company_id == company_id,
            TruckAssignment.date == day,
            AssignmentMember.employee_id.in_(ids),
        )
        .all()
    }

    # ilike on the weekday: the availability endpoint and the emergency pool
    # both compare case-insensitively, and disagreeing here would make the
    # dashboard contradict the pool it is meant to summarise.
    unavailable = {
        r.employee_id
        for r in db.query(TimeOffRequest).filter(
            TimeOffRequest.date == day,
            TimeOffRequest.status == "approved",
            TimeOffRequest.employee_id.in_(ids),
        ).all()
    } | {
        r.employee_id
        for r in db.query(EmployeeOffDay).filter(
            EmployeeOffDay.day_of_week.ilike(day.strftime("%A")),
            EmployeeOffDay.status == "approved",
            EmployeeOffDay.employee_id.in_(ids),
        ).all()
    }

    for e in staff:
        on_truck = e.id in assigned
        spare = not on_truck and e.id not in unavailable
        if e.role == "driver":
            out.assigned_drivers += on_truck
            out.spare_drivers += spare
        elif e.role == "captain":
            out.assigned_captains += on_truck
            out.spare_captains += spare
        elif e.role == "walker":
            out.assigned_walkers += on_truck
            out.spare_walkers += spare
        elif e.role == "trainer":
            out.assigned_trainers += on_truck
            out.spare_trainers += spare

    # Only the truck-critical roles raise the flag. Zero spare walkers is a
    # thin day; zero spare drivers means the next decline strands a vehicle.
    out.at_capacity_risk = (
        (out.assigned_drivers > 0 and out.spare_drivers == 0)
        or (out.assigned_captains > 0 and out.spare_captains == 0)
    )
    return out

"""Where the operation loses capacity to declines (ADR-268).

A decline rate on its own is ambiguous: "declined 4 of 12" reads identically
whether someone is unreliable or is repeatedly handed a shift they cannot make.
The operator resolved that rather than accepting it:

  > Raw decline rates especially on the same days is a scheduling conflict that
  > should be surfaced, we are creating a per truck visibility so we can get a
  > bit more indepth with these to make easier assumptions on the ambiguity

So CLUSTERING is the disambiguator, and the analysis is sliced three ways:

  by weekday   four declines all landing on Fridays is a ROTA signal — the fix
               is to stop rostering that person on Fridays
  by truck     declines concentrated on one truck point at the truck (start
               time, route, crew), not at the people
  by person    only interpretable ALONGSIDE the two above

THE VOLUME GATE
A rate needs enough observations to mean anything. The operator set the bar:

  > Require a full cycle of that weekday (4+)

so a weekday slice reports a bare COUNT until that weekday has been observed at
least four times — roughly a month. Below that the pattern could be one bad
week. `rate` is None in that case rather than a number nobody should trust; a
consumer that renders `rate ?? count` cannot accidentally publish a 1-sample
percentage as a finding.

Public module: read-only aggregation.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.assignment_member import AssignmentMember
from app.models.dispatch_confirmation import DispatchConfirmation
from app.models.employee import Employee
from app.models.truck import Truck
from app.models.truck_assignment import TruckAssignment

logger = logging.getLogger(__name__)

# A weekday needs this many OCCURRENCES — not this many declines — before a
# rate is reported. Four Fridays is roughly a month: long enough that a pattern
# has to persist rather than reflect one bad week.
MIN_WEEKDAY_OCCURRENCES = 4

# Trucks and people are not weekly cycles, so they use a plain sample floor.
MIN_SAMPLE = 10


@dataclass
class Slice:
    key: str
    declines: int = 0
    total: int = 0
    # Distinct dates this slice was observed. The GATE for weekday slices:
    # 12 confirmations across 2 Fridays is not 12 observations of "Friday".
    occurrences: int = 0
    # None until the slice clears its gate. Deliberately not 0.0 — a consumer
    # rendering `rate ?? count` then cannot publish a 1-sample percentage.
    rate: Optional[float] = None
    gated: bool = True


@dataclass
class DeclineAnalysis:
    start_date: date
    end_date: date
    total_confirmations: int = 0
    total_declines: int = 0
    by_weekday: list = field(default_factory=list)
    by_truck: list = field(default_factory=list)
    by_person: list = field(default_factory=list)


def _finish(slices: dict, *, min_units: int, unit: str) -> list:
    """Apply the gate and sort worst-first."""
    out = []
    for s in slices.values():
        have = s.occurrences if unit == "occurrences" else s.total
        if have >= min_units and s.total > 0:
            s.rate = round(s.declines / s.total, 4)
            s.gated = False
        out.append(s)
    # Ungated slices last: a slice with no rate cannot be ranked against one
    # that has a rate, and floating it to the top on decline count alone would
    # be the noise the gate exists to suppress.
    out.sort(key=lambda s: (s.gated, -(s.rate or 0), -s.declines))
    return out


def get_decline_analysis(
    db: Session,
    company_id: UUID,
    start_date: date,
    end_date: date,
) -> DeclineAnalysis:
    """Decline rates sliced by weekday, truck and person."""
    analysis = DeclineAnalysis(start_date=start_date, end_date=end_date)

    confirmations = (
        db.query(DispatchConfirmation)
        .filter(
            DispatchConfirmation.company_id == company_id,
            DispatchConfirmation.date >= start_date,
            DispatchConfirmation.date <= end_date,
        )
        .all()
    )
    if not confirmations:
        return analysis

    analysis.total_confirmations = len(confirmations)
    analysis.total_declines = sum(1 for c in confirmations if c.status == "declined")

    # Which truck each person was on, per date — a decline is attributable to
    # the truck they were rostered on, which is what makes "this shift keeps
    # getting refused" answerable.
    truck_by_person_date: dict = {}
    for am, ta, truck in (
        db.query(AssignmentMember, TruckAssignment, Truck)
        .join(TruckAssignment, AssignmentMember.assignment_id == TruckAssignment.id)
        .join(Truck, Truck.id == TruckAssignment.truck_id)
        .filter(
            TruckAssignment.company_id == company_id,
            TruckAssignment.date >= start_date,
            TruckAssignment.date <= end_date,
        )
        .all()
    ):
        truck_by_person_date[(str(am.employee_id), ta.date)] = truck.name

    names = {
        str(e.id): e.name
        for e in db.query(Employee).filter(Employee.company_id == company_id).all()
    }

    weekday: dict = {}
    truck_s: dict = {}
    person: dict = {}
    weekday_dates: dict = {}
    truck_dates: dict = {}

    for c in confirmations:
        declined = c.status == "declined"

        wd = c.date.strftime("%A")
        w = weekday.setdefault(wd, Slice(key=wd))
        w.total += 1
        w.declines += declined
        weekday_dates.setdefault(wd, set()).add(c.date)

        tname = truck_by_person_date.get((str(c.employee_id), c.date))
        if tname:
            t = truck_s.setdefault(tname, Slice(key=tname))
            t.total += 1
            t.declines += declined
            truck_dates.setdefault(tname, set()).add(c.date)

        pid = str(c.employee_id)
        p = person.setdefault(pid, Slice(key=names.get(pid, pid)))
        p.total += 1
        p.declines += declined

    for wd, dates in weekday_dates.items():
        weekday[wd].occurrences = len(dates)
    for tn, dates in truck_dates.items():
        truck_s[tn].occurrences = len(dates)

    # Weekday gates on OCCURRENCES of that weekday — the operator's "full cycle
    # (4+)". Truck and person gate on sample size instead: neither is a weekly
    # cycle, so counting distinct dates would be the wrong unit.
    analysis.by_weekday = _finish(weekday, min_units=MIN_WEEKDAY_OCCURRENCES,
                                  unit="occurrences")
    analysis.by_truck = _finish(truck_s, min_units=MIN_SAMPLE, unit="total")
    analysis.by_person = _finish(person, min_units=MIN_SAMPLE, unit="total")
    return analysis
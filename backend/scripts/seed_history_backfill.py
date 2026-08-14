"""Generate 36 months of operating history so the drill-down has depth (ADR-271).

WHY THIS EXISTS
Staging holds ONE MONTH of routes (2026-07-04 -> 2026-08-04). The My Stats
drill-down has five levels and a trend rule that needs a COMPLETED PRIOR
PERIOD, so with one month:

    Year   -> 1 bar, no prior year  -> no trend
    Month  -> 1 bar, no prior month -> no trend
    Week   -> ~4 bars               -> works
    Day    ->                          works

Three of five levels have nothing to show, and the trend — the thing that tells
a worker whether they are improving — is suppressed everywhere.

WHAT IT GENERATES
Whole operating days backwards from the existing data: TruckAssignment ->
AssignmentMember -> Route -> DeliveryStop -> RTSPackage, plus DamagedPackage on
the truck. Everything past-dated; today and the future are never touched.

VARIANCE IS THE POINT, AND IT IS LAYERED
The operator's requirement was explicit — "Jun 2025 shouldn't have the same
data as Jun 2026". So no single factor repeats across years:

  1. YEAR ARC        the operation grows: 2023 is a smaller business than 2026
  2. SEASON          December peaks, February troughs (shape repeats)
  3. YEAR x SEASON   a per-(year,month) jitter so the SAME month differs
                     between years — without this every June is identical and
                     the year-over-year comparison is theatre
  4. WEEKDAY         Mon/Fri heavier, Sunday mostly off
  5. DAY SHOCK       storms, vehicle-down days, surge days
  6. PERSON          a stable per-employee skill from a HASH of their id, so a
                     strong walker stays strong across runs and screenshots
                     remain reproducible

EDGE CASES DELIBERATELY INCLUDED, because a UI that has only seen clean data
breaks on real data:
  * days with an assignment but NO routes (rostered, nothing delivered)
  * routes with zero RTS, and routes that returned almost everything
  * a walker's first-ever day (no prior period -> the trend must render nothing)
  * gaps: holidays, and people who joined partway through
  * one deliberately terrible week per year
  * missing packages, which are rarer than RTS and easy to forget

IDEMPOTENT: a date that already has assignments is skipped, so this can be
re-run and will not double-write. Existing July 2026 data is left alone.

Run from inside the container:
    docker compose exec backend python scripts/seed_history_backfill.py --dry-run
    docker compose exec backend python scripts/seed_history_backfill.py --months 36
"""
import argparse
import hashlib
import os
import random
import sys
import uuid
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import func                                 # noqa: E402

from app.database import SessionLocal                       # noqa: E402
from app.models.assignment_member import AssignmentMember   # noqa: E402
from app.models.company import Company                      # noqa: E402
from app.models.delivery_stop import DeliveryStop           # noqa: E402
from app.models.employee import Employee                    # noqa: E402
from app.models.rts import (                                # noqa: E402
    DamagedPackage, MissingPackage, RTSPackage, RTS_TYPES, is_reattemptable,
)
from app.models.truck import Truck                          # noqa: E402
from app.models.truck_assignment import TruckAssignment     # noqa: E402
from app.models.walker_route import Route                   # noqa: E402

# ── shape, measured from the existing month on staging ──────────────────────
_STOPS_PER_ROUTE = (18, 30)      # observed avg 23.5
_CAPACITY = 12                   # observed
_RTS_RATE = {"easy": 0.02, "standard": 0.05, "heavy": 0.11}
_EFFORT_CHOICES = ["easy"] * 2 + ["standard"] * 5 + ["heavy"] * 3

_SEASON = {
    1: 0.82, 2: 0.64, 3: 0.94, 4: 1.02, 5: 0.91, 6: 0.75,
    7: 0.98, 8: 1.12, 9: 0.93, 10: 1.06, 11: 0.88, 12: 1.48,
}
# The business grows. Without this every year is the same size and the
# year-over-year chart says nothing.
_YEAR_ARC = {2023: 0.55, 2024: 0.72, 2025: 0.90, 2026: 1.00}
_WEEKDAY = {0: 1.10, 1: 0.95, 2: 0.98, 3: 1.00, 4: 1.12, 5: 0.70, 6: 0.10}

_EXPLANATIONS = {
    "no_access":                          "Gate code did not work, no answer on buzzer.",
    "business_closed":                    "Business shut when attempted, no safe drop.",
    "package_damaged":                    "Box crushed in transit, contents exposed.",
    "inclement_weather":                  "Heavy rain, no covered drop point.",
    "customer_requested_future_delivery": "Customer asked for delivery tomorrow.",
    "customer_cancelled_order":           "Customer cancelled at the door.",
}
_DAMAGE_STAGES = ("station_sort", "truck_load", "in_truck")
_DAMAGE_NOTES = {
    "station_sort": "Crushed corner found on the sort line.",
    "truck_load":   "Box split while loading, contents visible.",
    "in_truck":     "Shifted in transit and torn open.",
}
_STREETS = ["W_37_St", "W_49_St", "E_14_St", "W_23_St", "E_58_St", "W_72_St",
            "Broadway", "Amsterdam_Ave", "Columbus_Ave", "Lexington_Ave"]

# US holidays where the operation stands down. Real gaps matter: a chart with
# no zero days looks synthetic, and the UI must survive them.
_HOLIDAYS = {(1, 1), (7, 4), (11, 27), (12, 25), (12, 24)}


def _year_month_jitter(y: int, m: int) -> float:
    """Stable per-(year, month) multiplier.

    THE KEY FUNCTION for the operator's requirement. Season alone repeats
    identically every year; this makes June 2025 differ from June 2026 while
    staying deterministic across runs.
    """
    h = hashlib.sha256(f"ym-{y}-{m}".encode()).digest()
    return 0.78 + (h[0] / 255) * 0.50          # 0.78 .. 1.28


def _person(emp_id) -> dict:
    h = hashlib.sha256(f"person-{emp_id}".encode()).digest()
    return {
        "volume": 0.70 + (h[0] / 255) * 0.60,
        "care":   0.55 + (h[1] / 255) * 0.95,   # <1 is better than average
        "damage": 0.40 + (h[2] / 255) * 1.70,
        # Tenure: some people joined partway through, so their history starts
        # late and their first day legitimately has no prior period.
        "start_frac": (h[3] / 255),
    }


def main(months: int, dry_run: bool) -> None:
    db = SessionLocal()
    company = db.query(Company).first()
    if company is None:
        print("No company — nothing to do.")
        return
    cid = company.id

    trucks = db.query(Truck).filter(Truck.company_id == cid).all()
    if not trucks:
        print("No trucks — cannot build assignments.")
        return

    field = (
        db.query(Employee)
        .filter(
            Employee.company_id == cid,
            Employee.is_active == True,                      # noqa: E712
            Employee.role.in_(["walker", "driver", "trainer", "trainee", "captain"]),
        )
        .all()
    )
    drivers = [e for e in field if e.role in ("driver", "captain")]
    carriers = [e for e in field if e.role in ("walker", "trainee", "trainer")]
    if not drivers or not carriers:
        print(f"Need drivers and carriers; have {len(drivers)}/{len(carriers)}.")
        return

    earliest = db.query(func.min(TruckAssignment.date)).filter(
        TruckAssignment.company_id == cid).scalar() or date.today()
    end = earliest - timedelta(days=1)
    start = end - timedelta(days=months * 30)

    existing_dates = {
        d for (d,) in db.query(TruckAssignment.date)
        .filter(TruckAssignment.company_id == cid).distinct().all()
    }

    profiles = {e.id: _person(e.id) for e in field}
    span_days = (end - start).days or 1

    n_days = n_routes = n_stops = n_rts = n_dmg = n_miss = 0
    day = start

    while day <= end:
        if day in existing_dates or (day.month, day.day) in _HOLIDAYS:
            day += timedelta(days=1)
            continue

        rng = random.Random(f"day-{day.isoformat()}")
        weekday_f = _WEEKDAY[day.weekday()]
        if weekday_f < 0.2 and rng.random() < 0.85:
            day += timedelta(days=1)          # Sundays mostly off
            continue

        season = _SEASON[day.month] * _year_month_jitter(day.year, day.month)
        arc = _YEAR_ARC.get(day.year, 1.0)

        # Day shocks — a storm, a depot problem, a surge. Without these every
        # week looks the same shape and the day chart is a flat comb.
        shock = 1.0
        roll = rng.random()
        if roll < 0.04:
            shock = 0.25                        # depot down / storm
        elif roll < 0.09:
            shock = 1.65                        # surge
        # One deliberately terrible week per year, so the UI is seen under a
        # genuinely bad stretch rather than only healthy data.
        bad_week = (day.isocalendar()[1] == (7 + day.year % 40))

        scale = arc * season * weekday_f * shock
        n_truck = max(1, min(len(trucks), int(round(len(trucks) * scale))))
        chosen_trucks = rng.sample(trucks, n_truck)

        # Who was employed yet — a walker who joined later has no history, so
        # their first day carries no prior period.
        available = [
            e for e in carriers
            if profiles[e.id]["start_frac"] * span_days <= (day - start).days
        ] or carriers[:4]

        for truck in chosen_trucks:
            ta = TruckAssignment(
                id=uuid.uuid4(), company_id=cid, truck_id=truck.id, date=day,
            )
            if not dry_run:
                db.add(ta)
                db.flush()

            drv = rng.choice(drivers)
            crew_n = min(len(available), rng.randint(3, 8))
            crew = rng.sample(available, crew_n)
            if not dry_run:
                db.add(AssignmentMember(
                    id=uuid.uuid4(), company_id=cid, assignment_id=ta.id,
                    employee_id=drv.id, role=drv.role,
                ))
                for m in crew:
                    db.add(AssignmentMember(
                        id=uuid.uuid4(), company_id=cid, assignment_id=ta.id,
                        employee_id=m.id, role=m.role,
                    ))
            n_days += 1

            # EDGE CASE: rostered but nothing delivered. Real, and the chart
            # must render it as an empty day rather than as a broken chart.
            if rng.random() < 0.06:
                continue

            for ri, member in enumerate(crew, start=1):
                prof = profiles[member.id]
                effort = rng.choice(_EFFORT_CHOICES)
                route = Route(
                    id=uuid.uuid4(), company_id=cid, route_date=day,
                    truck_assignment_id=ta.id, route_number=ri,
                    status="completed", package_count=0,
                    capacity_limit=_CAPACITY, effort_class=effort,
                    block_keys=[], tote_ids=[], tba_numbers=[],
                    normalised_addresses=[], stops=[],
                )
                if not dry_run:
                    db.add(route)
                    db.flush()
                n_routes += 1

                base = rng.randint(*_STOPS_PER_ROUTE)
                stop_n = max(1, int(round(base * prof["volume"] * shock)))
                rate = min(0.9, _RTS_RATE[effort] * prof["care"]
                           * (2.4 if bad_week else 1.0))

                for si in range(1, stop_n + 1):
                    total = rng.choice([1, 1, 1, 2, 2, 3])
                    rts = sum(1 for _ in range(total) if rng.random() < rate)
                    # Missing is rarer than RTS and easy to forget in a seed.
                    missing = 1 if (total - rts) > 0 and rng.random() < 0.004 else 0
                    delivered = max(0, total - rts - missing)
                    if not dry_run:
                        db.add(DeliveryStop(
                            id=uuid.uuid4(), company_id=cid, route_id=route.id,
                            truck_assignment_id=ta.id,
                            block_key=f"{rng.choice(_STREETS)}_{rng.randrange(100, 900, 100)}",
                            tba_numbers=[], status="completed",
                            stop_sequence=si, packages_total=total,
                            packages_delivered=delivered, rts_count=rts,
                            missing_count=missing, effort_class=effort,
                            walker_id=member.id,
                        ))
                    n_stops += 1

                    for _ in range(rts):
                        if rng.random() < 0.18 * prof["damage"]:
                            rts_type = "package_damaged"
                        else:
                            rts_type = rng.choice(
                                [t for t in RTS_TYPES if t != "package_damaged"])
                        if not dry_run:
                            db.add(RTSPackage(
                                id=uuid.uuid4(), company_id=cid,
                                route_id=route.id, truck_assignment_id=ta.id,
                                tba_number=f"TBA{uuid.uuid4().hex[:12].upper()}",
                                rts_type=rts_type,
                                rts_explanation=_EXPLANATIONS[rts_type],
                                is_reattemptable=is_reattemptable(rts_type),
                                walker_id=member.id,
                            ))
                        n_rts += 1

                    if missing and not dry_run:
                        db.add(MissingPackage(
                            id=uuid.uuid4(), company_id=cid, route_id=route.id,
                            truck_assignment_id=ta.id,
                            tba_number=f"TBA{uuid.uuid4().hex[:12].upper()}",
                            walker_id=member.id,
                            resolution_status="pending",
                            resolution_notes="Scanned out but not found on the truck.",
                        ))
                    n_miss += missing

            # Pre-route damage on the truck — the figure drivers and captains
            # see (ADR-271 F). Without rows their damage number is always zero.
            #
            # The RNG draws happen REGARDLESS of dry_run: gating them on it
            # desynchronises the random stream, so the dry run would predict a
            # different dataset from the one the real run writes. Only the
            # db.add is skipped.
            if rng.random() < 0.20:
                for _ in range(rng.choice([1, 1, 2])):
                    stage = rng.choice(_DAMAGE_STAGES)
                    if not dry_run:
                        db.add(DamagedPackage(
                            id=uuid.uuid4(), company_id=cid, route_date=day,
                            tba_number=f"TBA{uuid.uuid4().hex[:12].upper()}",
                            truck_assignment_id=ta.id, stage=stage,
                            damage_notes=_DAMAGE_NOTES[stage],
                            resolution_status="pending",
                        ))
                    n_dmg += 1

        if not dry_run and n_days % 40 == 0:
            db.commit()                        # keep the transaction bounded
        day += timedelta(days=1)

    if dry_run:
        db.rollback()
        print(f"DRY RUN — would create across {start} .. {end}:")
    else:
        db.commit()
        print(f"Created across {start} .. {end}:")
    print(f"  assignments {n_days}\n  routes      {n_routes}\n"
          f"  stops       {n_stops}\n  rts         {n_rts}\n"
          f"  missing     {n_miss}\n  truck-dmg   {n_dmg}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", type=int, default=36)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    main(a.months, a.dry_run)

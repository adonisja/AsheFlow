"""Give per-person outcomes real VARIANCE so the drill-down shows something.

WHY THIS EXISTS
`seed_route_outcomes.py` deliberately spreads work evenly:

    # Round-robin rather than random, so every walker on the truck ends
    # up with a comparable share

That was right for proving per-person scoping — every walker needed *some*
data. But it makes every walker look identical, and it makes every month look
like every other month. Viewed through the ADR-271 drill-down the result is a
flat line at every level, which is exactly what the drill-down exists to
disprove:

    "the mock shows the same data across each period which makes it
     difficult to see changes in data"

WHAT VARIANCE MEANS HERE
Three layers, because real delivery data has all three:

  1. PER-PERSON SKILL — a persistent multiplier per employee. A strong walker
     carries more and returns less, every month, not at random. Without this,
     comparing two accounts is meaningless and the At-Risk list has no signal.
  2. SEASONAL SHAPE — a per-month factor. December peaks, February slumps.
     Without it the year-over-year and month-to-month charts are flat.
  3. DAY NOISE — day-to-day swing on top, including occasional light days.

Skill is derived from a HASH of the employee id, not from `random`, so it is
stable across runs and across partial re-runs: the same person always gets the
same profile even if this script is run twice on different date ranges.

ROLE MATTERS
Damage is attributed by role (ADR-271 F), so the script seeds both kinds:
  * on-route damage  -> RTSPackage rts_type='package_damaged' (walker_id)
  * pre-route damage -> DamagedPackage on the truck assignment
A driver with no truck damage rows would make their damage figure permanently
zero and the role split unverifiable.

ONLY PAST DATES, and only stops already completed by seed_route_outcomes —
this RE-ROLLS outcome numbers, it does not create days.

Run from inside the container:
    docker compose exec backend python scripts/seed_stats_variance.py
    docker compose exec backend python scripts/seed_stats_variance.py --dry-run
"""
import hashlib
import os
import random
import sys
import uuid
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal                      # noqa: E402
from app.models.assignment_member import AssignmentMember   # noqa: E402
from app.models.company import Company                      # noqa: E402
from app.models.delivery_stop import DeliveryStop           # noqa: E402
from app.models.employee import Employee                    # noqa: E402
from app.models.rts import (                                # noqa: E402
    DamagedPackage, RTSPackage, RTS_TYPES, is_reattemptable,
)
from app.models.truck_assignment import TruckAssignment     # noqa: E402
from app.models.walker_route import Route                   # noqa: E402

random.seed(271)

# Base RTS rate by difficulty — kept identical to seed_route_outcomes so the
# difficulty-normalisation signal (ADR-268) survives.
_RTS_RATE = {"easy": 0.02, "standard": 0.05, "heavy": 0.11}

# Seasonal multiplier on volume. A real operation is not flat: peak season is
# roughly double a February trough, which is what makes a year chart worth
# looking at.
_MONTH_FACTOR = {
    1: 0.80, 2: 0.62, 3: 0.95, 4: 1.05, 5: 0.90, 6: 0.72,
    7: 1.00, 8: 1.15, 9: 0.92, 10: 1.08, 11: 0.85, 12: 1.45,
}

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


def _profile(employee_id) -> dict:
    """A STABLE per-person profile derived from the id.

    Hash, not random: this script may be run more than once, and a walker whose
    numbers changed every run would make any screenshot unreproducible. The
    same id always yields the same profile.

    volume  0.70–1.30  how much they carry relative to peers
    care    0.55–1.45  RTS multiplier; BELOW 1 is better than average
    """
    h = hashlib.sha256(str(employee_id).encode()).digest()
    return {
        "volume": 0.70 + (h[0] / 255) * 0.60,
        "care":   0.55 + (h[1] / 255) * 0.90,
        # A few people are genuinely damage-prone; most are not.
        "damage": 0.4 + (h[2] / 255) * 1.6,
    }


def main(dry_run: bool = False) -> None:
    db = SessionLocal()
    company = db.query(Company).first()
    if company is None:
        print("No company found — nothing to do.")
        return

    cid = company.id
    today = date.today()

    # Only completed PAST work. Re-rolling today would fight the live board.
    routes = (
        db.query(Route)
        .filter(Route.company_id == cid, Route.route_date < today)
        .order_by(Route.route_date)
        .all()
    )
    if not routes:
        print("No past routes — run seed_route_outcomes.py first.")
        return

    profiles: dict = {}
    stops_touched = 0
    rts_created = 0
    dmg_created = 0

    for route in routes:
        stops = (
            db.query(DeliveryStop)
            .filter(
                DeliveryStop.company_id == cid,
                DeliveryStop.route_id == route.id,
                DeliveryStop.walker_id.isnot(None),
            )
            .all()
        )
        if not stops:
            continue

        effort = route.effort_class or "standard"
        base_rts = _RTS_RATE.get(effort, 0.05)
        month_f = _MONTH_FACTOR.get(route.route_date.month, 1.0)

        # Day noise, stable per route so a re-run reproduces it.
        day_rng = random.Random(f"{route.id}")
        day_f = day_rng.uniform(0.65, 1.35)
        # Occasional very light day — a real week has them, and a chart with no
        # troughs looks synthetic.
        if day_rng.random() < 0.12:
            day_f *= 0.35

        for stop in stops:
            prof = profiles.setdefault(stop.walker_id, _profile(stop.walker_id))

            # Volume: person x season x day, around a 2-parcel base.
            mean = 2.0 * prof["volume"] * month_f * day_f
            total = max(1, int(round(day_rng.gauss(mean, 0.8))))

            rate = min(0.85, base_rts * prof["care"])
            rts = sum(1 for _ in range(total) if day_rng.random() < rate)

            if dry_run:
                stops_touched += 1
                continue

            # Clear previously generated RTS rows for this stop so a re-run
            # replaces rather than accumulates.
            old = (
                db.query(RTSPackage)
                .filter(
                    RTSPackage.company_id == cid,
                    RTSPackage.route_id == route.id,
                    RTSPackage.walker_id == stop.walker_id,
                )
                .all()
            )
            for o in old:
                db.delete(o)
                rts_created -= 1

            stop.status = "completed"
            stop.effort_class = effort
            stop.packages_total = total
            stop.packages_delivered = total - rts
            stop.rts_count = rts
            stops_touched += 1

            for _ in range(rts):
                # Damage-prone people produce more package_damaged specifically,
                # so the damaged figure is not just a slice of the RTS total.
                if day_rng.random() < 0.18 * prof["damage"]:
                    rts_type = "package_damaged"
                else:
                    rts_type = day_rng.choice(
                        [t for t in RTS_TYPES if t != "package_damaged"]
                    )
                db.add(RTSPackage(
                    id=uuid.uuid4(), company_id=cid, route_id=route.id,
                    truck_assignment_id=route.truck_assignment_id,
                    tba_number=f"TBA{uuid.uuid4().hex[:12].upper()}",
                    rts_type=rts_type,
                    rts_explanation=_EXPLANATIONS.get(rts_type, "Returned to station."),
                    is_reattemptable=is_reattemptable(rts_type),
                    walker_id=stop.walker_id,
                ))
                rts_created += 1

        # ── pre-route damage on the TRUCK ────────────────────────────────────
        # Drivers and captains see this figure (ADR-271 F); with no rows their
        # damage number is permanently zero and the role split is unverifiable.
        if not dry_run and route.truck_assignment_id and day_rng.random() < 0.22:
            existing = (
                db.query(DamagedPackage)
                .filter(
                    DamagedPackage.company_id == cid,
                    DamagedPackage.truck_assignment_id == route.truck_assignment_id,
                    DamagedPackage.route_date == route.route_date,
                )
                .count()
            )
            if existing == 0:
                for _ in range(day_rng.choice([1, 1, 2])):
                    stage = day_rng.choice(_DAMAGE_STAGES)
                    db.add(DamagedPackage(
                        id=uuid.uuid4(), company_id=cid,
                        route_date=route.route_date,
                        tba_number=f"TBA{uuid.uuid4().hex[:12].upper()}",
                        truck_assignment_id=route.truck_assignment_id,
                        stage=stage,
                        damage_notes=_DAMAGE_NOTES[stage],
                        resolution_status="pending",
                    ))
                    dmg_created += 1

    if dry_run:
        print(f"DRY RUN — would re-roll {stops_touched} stops "
              f"across {len(routes)} routes for {len(profiles)} people.")
        db.rollback()
        return

    db.commit()
    print(f"Re-rolled {stops_touched} stops across {len(routes)} routes.")
    print(f"RTS rows net {rts_created:+d}, damaged-package rows +{dmg_created}.")

    # Show the spread actually produced — a script that claims variance should
    # prove it rather than assert it.
    print("\nPer-person spread (top 8 by volume):")
    rows = (
        db.query(
            DeliveryStop.walker_id,
            Employee.name,
            Employee.role,
        )
        .join(Employee, Employee.id == DeliveryStop.walker_id)
        .filter(DeliveryStop.company_id == cid)
        .distinct()
        .all()
    )
    from sqlalchemy import func
    summary = []
    for wid, name, role in rows:
        d, r = (
            db.query(
                func.coalesce(func.sum(DeliveryStop.packages_delivered), 0),
                func.coalesce(func.sum(DeliveryStop.rts_count), 0),
            )
            .filter(
                DeliveryStop.company_id == cid,
                DeliveryStop.walker_id == wid,
            )
            .first()
        )
        summary.append((int(d), int(r), name, role))
    summary.sort(reverse=True)
    for d, r, name, role in summary[:8]:
        pct = (r / (d + r) * 100) if (d + r) else 0
        print(f"  {name[:22]:24} {role:10} delivered={d:6}  rts={r:4} ({pct:.1f}%)")


if __name__ == "__main__":
    main(dry_run="--dry-run" in sys.argv)

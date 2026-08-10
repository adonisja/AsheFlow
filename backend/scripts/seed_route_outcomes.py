"""Complete past routes so outcome-dependent features have data to show (ADR-268).

WHY THIS EXISTS
The seed builds the PLANNING half of a day — routes, crews, stops,
confirmations — but nothing is ever walked. Measured on staging before writing
this:

    stops                      15,579   ALL status='planned'
    packages_total set              0
    rts_count > 0                   0
    RTSPackage rows                 0
    routes by effort_class     664 x 'standard'   (zero variance)

So every outcome feature — RTS rate, delivered vs total, difficulty-normalised
At-Risk — renders empty, and none of them can be verified. `effort_class` on a
stop is snapshotted at COMPLETION, which is why it is None everywhere.

WHAT IT DOES
For route dates strictly in the past, marks stops completed and fills the
outcome columns:

  * packages_total / packages_delivered
  * rts_count + a matching RTSPackage row per RTS, with a real rts_type and
    explanation
  * effort_class on the route AND snapshotted on the stop

DELIBERATE SHAPE
  * RTS rate VARIES BY effort_class (easy < standard < heavy). A flat rate
    would make difficulty-normalisation look like it works when it is doing
    nothing — the normalisation has to have a signal to remove.
  * effort_class is assigned per route, not per stop, matching how route_sort
    produces it.
  * Only PAST dates. Completing today's or a future route would corrupt the
    live dispatch board.
  * Idempotent: a stop already completed is skipped, so re-running does not
    double-count.

Run from inside the container:
    docker compose exec backend python scripts/seed_route_outcomes.py
    docker compose exec backend python scripts/seed_route_outcomes.py --dry-run
"""
import os
import random
import sys
import uuid
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal                     # noqa: E402
from app.models.company import Company                    # noqa: E402
from app.models.delivery_stop import DeliveryStop         # noqa: E402
from app.models.rts import RTSPackage, RTS_TYPES, is_reattemptable  # noqa: E402
from app.models.walker_route import Route                 # noqa: E402

# Deterministic: the same run produces the same data, so a number seen on a
# screen can be traced back to a specific row rather than to chance.
random.seed(268)

# RTS rate by route difficulty. The whole point of normalising At-Risk by
# effort_class is that a harder route produces more returns for reasons the
# walker does not control — that has to be true in the data, or the
# normalisation is untestable.
_RTS_RATE = {"easy": 0.02, "standard": 0.05, "heavy": 0.11}

# Weighted so 'standard' dominates, as it does in a real operation.
_EFFORT_CHOICES = ["easy"] * 2 + ["standard"] * 5 + ["heavy"] * 3

_EXPLANATIONS = {
    "no_access":                          "Gate code did not work, no answer on buzzer.",
    "business_closed":                    "Business shut when attempted, no safe drop.",
    "package_damaged":                    "Box crushed in transit, contents exposed.",
    "inclement_weather":                  "Heavy rain, no covered drop point.",
    "customer_requested_future_delivery": "Customer asked for delivery tomorrow.",
    "customer_cancelled_order":           "Customer cancelled at the door.",
}


def main(dry_run: bool = False) -> None:
    db = SessionLocal()
    company = db.query(Company).first()
    if company is None:
        print("no company — nothing to do")
        return

    today = date.today()
    routes = (
        db.query(Route)
        .filter(Route.company_id == company.id, Route.route_date < today)
        .order_by(Route.route_date)
        .all()
    )
    if not routes:
        print("no past routes — nothing to do")
        return

    touched_routes = 0
    touched_stops = 0
    rts_created = 0

    for route in routes:
        stops = (
            db.query(DeliveryStop)
            .filter(
                DeliveryStop.company_id == company.id,
                DeliveryStop.route_id == route.id,
                DeliveryStop.status != "completed",     # idempotent
            )
            .all()
        )
        if not stops:
            continue

        effort = random.choice(_EFFORT_CHOICES)
        rts_rate = _RTS_RATE[effort]
        route.effort_class = effort
        touched_routes += 1

        for stop in stops:
            # Package count per stop: most stops are one or two parcels.
            total = random.choice([1, 1, 1, 2, 2, 3])
            rts = sum(1 for _ in range(total) if random.random() < rts_rate)
            delivered = total - rts

            stop.status = "completed"
            stop.effort_class = effort            # the completion snapshot
            stop.packages_total = total
            stop.packages_delivered = delivered
            stop.rts_count = rts
            touched_stops += 1

            for i in range(rts):
                rts_type = random.choice(RTS_TYPES)
                db.add(RTSPackage(
                    id=uuid.uuid4(),
                    company_id=company.id,
                    route_id=route.id,
                    truck_assignment_id=route.truck_assignment_id,
                    # Traceable to this script: a TBA nobody can confuse with a
                    # real Amazon barcode.
                    tba_number=f"SEED268{str(stop.id)[:8]}{i}".upper(),
                    normalised_address=stop.normalised_address,
                    rts_type=rts_type,
                    rts_explanation=_EXPLANATIONS[rts_type],
                    is_reattemptable=is_reattemptable(rts_type),
                    walker_id=stop.walker_id,
                    walker_name=stop.walker_name,
                ))
                rts_created += 1

    print(f"routes  touched: {touched_routes}")
    print(f"stops   completed: {touched_stops}")
    print(f"RTS     rows created: {rts_created}")

    if dry_run:
        db.rollback()
        print("DRY RUN — rolled back, nothing written")
        return

    db.commit()
    print("committed")


if __name__ == "__main__":
    main(dry_run="--dry-run" in sys.argv)

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
  * Stops are ATTRIBUTED to a walker (DeliveryStop.walker_id). Without it every
    stop belongs to nobody, and the per-person scoping in ADR-268 — a walker
    sees their own stops, a driver sees the truck's — has nothing to filter on,
    so every walker's history reads empty. Found only by checking the rendered
    numbers against a walker account.
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

from sqlalchemy import or_                                # noqa: E402

from app.database import SessionLocal                     # noqa: E402
from app.models.assignment_member import AssignmentMember  # noqa: E402
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
        # Idempotent on the OUTCOME columns, but a completed stop with no
        # walker_id still needs repairing: the first version of this script did
        # not attribute stops at all, which left every walker's per-person
        # history empty (ADR-268). Re-running must fix those rows without
        # re-rolling their package counts.
        stops = (
            db.query(DeliveryStop)
            .filter(
                DeliveryStop.company_id == company.id,
                DeliveryStop.route_id == route.id,
                or_(
                    DeliveryStop.status != "completed",
                    DeliveryStop.walker_id.is_(None),
                ),
            )
            .all()
        )
        if not stops:
            continue

        # Who can own a stop on this truck. Drivers and captains run the
        # vehicle; the people who actually walk packages to doors are the ones
        # a stop belongs to (ADR-244: walker_id is the stop's EXECUTOR).
        crew = (
            db.query(AssignmentMember)
            .filter(
                AssignmentMember.assignment_id == route.truck_assignment_id,
                AssignmentMember.company_id == company.id,
                AssignmentMember.role.in_(["walker", "trainee", "trainer"]),
            )
            .all()
        )
        owners = [m.employee_id for m in crew] or [None]

        effort = random.choice(_EFFORT_CHOICES)
        rts_rate = _RTS_RATE[effort]
        route.effort_class = effort
        touched_routes += 1

        for stop in stops:
            # Round-robin rather than random, so every walker on the truck ends
            # up with a comparable share — random assignment leaves some crew
            # members with almost nothing and makes the per-person view look
            # broken for them.
            owner = owners[touched_stops % len(owners)]

            # Package count per stop: most stops are one or two parcels.
            total = random.choice([1, 1, 1, 2, 2, 3])
            rts = sum(1 for _ in range(total) if random.random() < rts_rate)
            delivered = total - rts

            already_done = stop.status == "completed"
            if stop.walker_id is None:
                stop.walker_id = owner
            touched_stops += 1

            if already_done:
                # Attribution repair only. Re-rolling counts would change
                # numbers a user may already have seen, and would double-create
                # the RTS rows below.
                continue

            stop.status = "completed"
            stop.effort_class = effort            # the completion snapshot
            stop.packages_total = total
            stop.packages_delivered = delivered
            stop.rts_count = rts

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

    # RTS rows created before stops were attributed copied a NULL walker_id,
    # which made a walker's rts_count (from DeliveryStop) disagree with their
    # rts_details (from these rows) — the count said 2, the list said 4.
    #
    # The link is EXACT, not inferred: the TBA is built as
    # f"SEED268{stop.id[:8]}{i}", so the originating stop is encoded in it.
    # An earlier version distributed orphans across the route's walkers by
    # hashing the TBA, which repaired the NULLs but left the count and the list
    # disagreeing per person — a repair that produced a different wrong answer.
    #
    # Verified collision-free before relying on it: 15,579 stops, 15,579
    # distinct 8-char prefixes.
    # Every seeded row, not just the NULLs: an earlier hash-based repair wrote
    # a WRONG owner onto 1,595 of 1,647 rows, and leaving those in place would
    # keep the count/list mismatch it caused. Reassigning from the TBA is
    # idempotent — a row already pointing at the right stop is rewritten to the
    # same value.
    orphan_rts = (
        db.query(RTSPackage)
        .filter(RTSPackage.company_id == company.id,
                RTSPackage.tba_number.like("SEED268%"))
        .all()
    )
    rts_repaired = 0
    rts_unmatched = 0
    if orphan_rts:
        stop_by_prefix = {
            str(st.id)[:8].upper(): st
            for st in db.query(DeliveryStop).filter(
                DeliveryStop.company_id == company.id).all()
        }
        for r in orphan_rts:
            # "SEED268" is 7 chars; the next 8 are the stop id prefix.
            prefix = r.tba_number[7:15]
            st = stop_by_prefix.get(prefix)
            if st is None or st.walker_id is None:
                # Left NULL on purpose. Guessing an owner is what produced the
                # count/list mismatch in the first place.
                rts_unmatched += 1
                continue
            r.walker_id = st.walker_id
            r.walker_name = st.walker_name
            rts_repaired += 1

    print(f"routes  touched: {touched_routes}")
    print(f"RTS     re-attributed: {rts_repaired}")
    if rts_unmatched:
        print(f"RTS     unmatched (left NULL): {rts_unmatched}")
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

"""Seed trip_count and roll-call history (ADR-271 I).

WHY
Two figures the My Stats drill-down promises have no data behind them:

  * `AssignmentMember.trip_count` is 0 on EVERY row, so the lifetime header's
    "Trips" tile renders 0 for everyone. A permanently-zero headline stat is
    worse than an absent one.
  * `shift_roll_calls` holds 302 rows company-wide against ~4,000 assignment
    days, so almost nobody has an attendance history to show.

WHAT
For each existing AssignmentMember on a PAST date:
  * a trip count derived from how much they actually carried that day — a
    walker with 30 stops did not do the same number of trips as one with 5
  * a roll-call row, mostly `present`, with realistic late/ncns rates that VARY
    BY PERSON so the attendance figure distinguishes people rather than showing
    everyone the same 96%

Reliability is hashed from the employee id, like every other per-person trait
in these scripts, so a given person's record is stable across re-runs and
screenshots stay reproducible.

IDEMPOTENT: rows that already have a trip_count, or a roll call for that date,
are skipped.

Run from inside the container:
    docker compose exec backend python scripts/seed_trips_and_rollcall.py --dry-run
    docker compose exec backend python scripts/seed_trips_and_rollcall.py
"""
import argparse
import hashlib
import os
import random
import sys
import uuid
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import func                                 # noqa: E402

from app.database import SessionLocal                       # noqa: E402
from app.models.assignment_member import AssignmentMember   # noqa: E402
from app.models.company import Company                      # noqa: E402
from app.models.delivery_stop import DeliveryStop           # noqa: E402
from app.models.shift_roll_call import ShiftRollCall        # noqa: E402
from app.models.truck_assignment import TruckAssignment     # noqa: E402
from _seed_guard import seed_target


def _reliability(emp_id) -> dict:
    """Stable per-person attendance profile.

    Hashed rather than random so the same person keeps the same record across
    runs. Most people are reliable; a few genuinely are not, and the metric is
    worthless if everyone looks identical.
    """
    h = hashlib.sha256(f"rel-{emp_id}".encode()).digest()
    # 0.00 .. 0.14 chance of a late mark, 0.00 .. 0.06 of an NCNS.
    return {
        "late": (h[0] / 255) * 0.14,
        "ncns": (h[1] / 255) * 0.06,
    }


def main(dry_run: bool) -> None:
    db = SessionLocal()
    # ADR-280 D3: refuses a live tenant, and is deterministic — the bare
    # .first() this replaces had no filter and no ordering.
    company = seed_target(db)
    cid = company.id
    today = date.today()

    members = (
        db.query(AssignmentMember, TruckAssignment.date)
        .join(TruckAssignment, TruckAssignment.id == AssignmentMember.assignment_id)
        .filter(
            AssignmentMember.company_id == cid,
            TruckAssignment.company_id == cid,
            TruckAssignment.date < today,
        )
        .all()
    )
    if not members:
        print("No past assignment members — run the backfill first.")
        return

    # Stops per (employee, date) — the basis for a believable trip count.
    stop_counts = {
        (w, d): int(n)
        for w, d, n in (
            db.query(DeliveryStop.walker_id, TruckAssignment.date,
                     func.count(DeliveryStop.id))
            .join(TruckAssignment,
                  TruckAssignment.id == DeliveryStop.truck_assignment_id)
            .filter(
                DeliveryStop.company_id == cid,
                TruckAssignment.company_id == cid,
                DeliveryStop.walker_id.isnot(None),
            )
            .group_by(DeliveryStop.walker_id, TruckAssignment.date)
            .all()
        )
    }

    existing_rc = {
        (e, d) for e, d in
        db.query(ShiftRollCall.employee_id, ShiftRollCall.date)
        .filter(ShiftRollCall.company_id == cid).all()
    }

    n_trips = n_rc = 0
    profiles: dict = {}

    for m, when in members:
        rng = random.Random(f"{m.id}")

        # ── trip_count ──
        if not m.trip_count:
            stops = stop_counts.get((m.employee_id, when), 0)
            if stops:
                # A trip is a truck-load run, not a stop: roughly one per 12
                # stops, floor of 1 for anyone who worked at all.
                trips = max(1, round(stops / 12) + (1 if rng.random() < 0.25 else 0))
            else:
                # Rostered but carried nothing — a driver, or a day with no
                # route. They still ran the truck.
                trips = 1 if rng.random() < 0.6 else 0
            if not dry_run:
                m.trip_count = trips
            n_trips += 1

        # ── roll call ──
        if (m.employee_id, when) not in existing_rc:
            prof = profiles.setdefault(m.employee_id, _reliability(m.employee_id))
            roll = rng.random()
            if roll < prof["ncns"]:
                status = "ncns"
            elif roll < prof["ncns"] + prof["late"]:
                status = "late"
            else:
                status = "present"
            if not dry_run:
                db.add(ShiftRollCall(
                    id=uuid.uuid4(), company_id=cid,
                    employee_id=m.employee_id, date=when, status=status,
                    confirmed=True,
                    submitted_at=datetime.now(timezone.utc),
                ))
            existing_rc.add((m.employee_id, when))
            n_rc += 1

        if not dry_run and n_rc % 2000 == 0 and n_rc:
            db.commit()

    if dry_run:
        db.rollback()
        print(f"DRY RUN — would set {n_trips} trip counts, add {n_rc} roll calls.")
        return

    db.commit()
    print(f"Set {n_trips} trip counts, added {n_rc} roll calls.")

    tot = db.query(func.coalesce(func.sum(AssignmentMember.trip_count), 0)).filter(
        AssignmentMember.company_id == cid).scalar()
    print(f"total trips across the company: {int(tot)}")
    print("attendance spread:")
    for st, n in (
        db.query(ShiftRollCall.status, func.count(ShiftRollCall.id))
        .filter(ShiftRollCall.company_id == cid)
        .group_by(ShiftRollCall.status).all()
    ):
        print(f"  {st:10} {n}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    main(ap.parse_args().dry_run)

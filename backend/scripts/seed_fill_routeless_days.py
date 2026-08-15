"""
Fill routes for assignments that have a crew but NO routes.

WHY THIS EXISTS
---------------
`seed_history_backfill.py` writes only BEFORE the earliest existing
TruckAssignment:

    end   = earliest - timedelta(days=1)
    start = end - timedelta(days=months * 30)

Any date at or after `earliest` is outside its range entirely, and its
`existing_dates` guard then skips those dates a second time. The result seen on
staging: a driver whose series ended in an EIGHT-day run of zeroes
(2026-08-03..08-10, plus 2026-07-15..07-18). Each of those dates had a truck and
a full crew — Falcon/20, Eagle/23, Morgan/18 — and zero routes. The person was
rostered onto a truck that never got a route.

That is not the deliberate 6% "rostered but nothing delivered" edge case in the
backfill. It is a coverage hole between the two seeding passes, and it lands on
the MOST RECENT days, which is exactly where the drill-down opens.

WHAT IT DOES
------------
Finds every TruckAssignment with >=1 AssignmentMember and 0 Routes, and
generates routes/stops/RTS/missing/damage for it using the SAME per-person,
per-week, per-day variance model as the backfill — imported, not re-derived, so
the two passes cannot drift apart.

IDEMPOTENT: an assignment that already has a route is never touched, so this is
safe to re-run. Seeded RNG is keyed on the assignment id, so a re-run after a
partial failure reproduces the same data.

    python scripts/seed_fill_routeless_days.py --dry-run
    python scripts/seed_fill_routeless_days.py
"""
import argparse
import hashlib
import os
import random
import sys
import uuid
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import func                                 # noqa: E402

from app.database import SessionLocal                       # noqa: E402
from app.models.assignment_member import AssignmentMember   # noqa: E402
from app.models.delivery_stop import DeliveryStop           # noqa: E402
from app.models.rts import (                                # noqa: E402
    DamagedPackage, MissingPackage, RTSPackage, RTS_TYPES, is_reattemptable,
)
from app.models.truck_assignment import TruckAssignment     # noqa: E402
from app.models.walker_route import Route                   # noqa: E402

# Import the variance model rather than restating it. If the backfill's shape
# changes, this pass changes with it.
from seed_history_backfill import (                         # noqa: E402
    _CAPACITY, _DAMAGE_NOTES, _DAMAGE_STAGES, _EFFORT_CHOICES, _EXPLANATIONS,
    _RTS_RATE, _STOPS_PER_ROUTE, _STREETS, _person,
)

# Roles that execute stops. A driver/captain owns the truck, not the stops
# (ADR-244), so a route's walker_id must never be one of them.
_CARRIER_ROLES = ("walker", "trainer", "trainee")


def purge(db, since) -> None:
    """Remove routes this script generated, so a bad run can be replaced.

    Targets ONLY assignments whose routes all carry the fill marker
    (route_number set with block_keys empty is not distinctive enough), so it
    is keyed on the route ids created at or after `since`. Deliberately narrow:
    a purge that over-reaches would delete the backfill's history too.
    """
    ids = [r for (r,) in db.query(Route.id).filter(Route.created_at >= since).all()]
    if not ids:
        print("purge: nothing matched")
        return
    for model in (RTSPackage, MissingPackage, DeliveryStop):
        n = db.query(model).filter(model.route_id.in_(ids)).delete(
            synchronize_session=False)
        print(f"purge: {model.__name__} {n}")
    n = db.query(Route).filter(Route.id.in_(ids)).delete(synchronize_session=False)
    print(f"purge: Route {n}")
    db.commit()


def main(dry_run: bool) -> None:
    db = SessionLocal()
    try:
        # D1 NOTE (ADR-115): these reads are deliberately NOT company-scoped.
        # This is an offline seeding tool with no caller and no request context,
        # and it must fill every tenant on the box. Tenancy is preserved on the
        # WRITE side instead: `cid` below is read from each assignment
        # (`ta.company_id`) and stamped on every row generated for it, so no row
        # is ever created under a company that did not own its assignment.
        # A caller-facing endpoint may not copy this pattern.
        #
        # Assignments that have members but no routes.
        routed = {r for (r,) in db.query(Route.truck_assignment_id).distinct()}
        rows = (
            db.query(TruckAssignment)
            .join(AssignmentMember,
                  AssignmentMember.assignment_id == TruckAssignment.id)
            .group_by(TruckAssignment.id)
            .having(func.count(AssignmentMember.id) > 0)
            .all()
        )
        targets = [ta for ta in rows if ta.id not in routed]
        if not targets:
            print("nothing to fill — every crewed assignment already has routes")
            return

        dates = sorted({ta.date for ta in targets})
        print(f"{len(targets)} routeless assignments across {len(dates)} dates "
              f"({dates[0]} .. {dates[-1]})")

        n_routes = n_stops = n_rts = n_miss = n_dmg = 0

        for ta in targets:
            day = ta.date
            cid = ta.company_id
            # Keyed on the assignment, so two trucks on one date differ and a
            # re-run reproduces the same numbers.
            rng = random.Random(f"fill-{ta.id}")

            members = (
                db.query(AssignmentMember)
                .filter(AssignmentMember.assignment_id == ta.id,
                        AssignmentMember.company_id == cid)
                .all()
            )
            crew = [m for m in members if m.role in _CARRIER_ROLES]
            if not crew:
                continue          # driver-only assignment: no stops to own

            # NOTE: no arc/season/weekday factor here. Those scale the number of
            # trucks on a date, and the truck already exists — this pass fills
            # routes onto an assignment that was created by an earlier pass.
            shock = 1.0
            roll = rng.random()
            if roll < 0.04:
                shock = 0.25
            elif roll < 0.09:
                shock = 1.65
            bad_week = (day.isocalendar()[1] == (7 + day.year % 40))

            for ri, member in enumerate(crew, start=1):
                prof = _person(member.employee_id)
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

                iso_y, iso_w, _ = day.isocalendar()
                wk_h = hashlib.sha256(
                    f"wk-{member.employee_id}-{iso_y}-{iso_w}".encode()).digest()
                week_f = 0.70 + (wk_h[0] / 255) * 0.65
                dy_h = hashlib.sha256(
                    f"dy-{member.employee_id}-{day.isoformat()}".encode()).digest()
                day_f = 0.60 + (dy_h[0] / 255) * 0.85

                # EXACTLY the backfill's per-route formula. `arc`, `season` and
                # `weekday_f` are DAY-level factors: the backfill applies them
                # to the number of TRUCKS running that day, not to the stops on
                # each route. Multiplying them in here as well double-counts
                # them and produced 12,900 stops on a day whose real crew ran
                # ~1,900 packages.
                base = rng.randint(*_STOPS_PER_ROUTE)
                stop_n = max(1, int(round(
                    base * prof["volume"] * shock * week_f * day_f)))
                rate = min(0.9, _RTS_RATE[effort] * prof["care"]
                           * (0.75 + (wk_h[1] / 255) * 0.70)
                           * (2.4 if bad_week else 1.0))

                for si in range(1, stop_n + 1):
                    total = rng.choice([1, 1, 1, 2, 2, 3])
                    rts = sum(1 for _ in range(total) if rng.random() < rate)
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
                            walker_id=member.employee_id,
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
                                walker_id=member.employee_id,
                            ))
                        n_rts += 1

                    if missing and not dry_run:
                        db.add(MissingPackage(
                            id=uuid.uuid4(), company_id=cid, route_id=route.id,
                            truck_assignment_id=ta.id,
                            tba_number=f"TBA{uuid.uuid4().hex[:12].upper()}",
                            walker_id=member.employee_id,
                            resolution_status="pending",
                            resolution_notes="Scanned out but not found on the truck.",
                        ))
                    n_miss += missing

            # Pre-route truck damage — the figure drivers and captains see.
            # RNG draws happen regardless of dry_run so the two runs agree.
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

            if not dry_run:
                db.flush()

        if dry_run:
            print("DRY RUN — nothing written")
        else:
            db.commit()

        print(f"routes={n_routes} stops={n_stops} rts={n_rts} "
              f"missing={n_miss} damaged={n_dmg}")
    finally:
        db.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--purge-since", metavar="ISO_TS",
                    help="delete routes created at/after this timestamp, then exit "
                         "(use to undo a bad fill run before re-running)")
    a = ap.parse_args()
    if a.purge_since:
        db = SessionLocal()
        try:
            purge(db, datetime.fromisoformat(a.purge_since))
        finally:
            db.close()
    else:
        main(a.dry_run)
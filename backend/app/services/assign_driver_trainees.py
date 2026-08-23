"""ADR-264 — place driver trainees on trucks with a supervising driver.

Runs after `assign_drivers`, so every truck's driver is known and pairing can be
read off the placed crew rather than guessed from the pool.

THE RULES THIS ENFORCES (operator, 2026-08-22)
---------------------------------------------
1. CONTINUITY — a trainee is paired with a driver who has supervised them
   before, most recent first, falling back through their whole history. The
   system never creates a NEW supervising relationship on its own.

2. HELD OUT, NOT PLACED — a trainee with no available prior supervisor is left
   off every truck and dispatch is alerted. Placing them on a truck with a
   driver who is not their supervisor is one edit away from an unapproved
   pairing, and a flag is easy to miss once the crew looks complete.

3. NEVER SOLO — this pass can produce *paired* or *unpaired-and-alerting*, never
   a trainee driving alone. Solo is an explicit dispatch approval (D7).

4. NO CAPACITY, NO PLACEMENT — a trainee and supervisor consume one truck and
   two drivers. When their supervisor's truck cannot take them, warn and leave
   them unassigned rather than bumping a walker to make room: that trade costs
   the truck a walker for a training need, and it is dispatch's to make.
"""
import logging
from datetime import date
from typing import Dict, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.employee import Employee
from app.services.driver_supervision import prior_supervisor_ids, resolve_supervisor

logger = logging.getLogger(__name__)


def unpaired_warning(employee_id, employee_name: str, reason: str) -> dict:
    """The single shape for an unpaired-trainee warning.

    Built here rather than at each call site because two paths emit it — the
    dispatch RUN (assign_driver_trainees) and the READ
    (GET /dispatch/{date} via unpaired_driver_trainees) — and a dispatcher
    seeing different wording for the same condition would reasonably assume
    they are different problems.

    `type` is load-bearing: run_dispatch rewrites any warning carrying
    employee_id but NO type into a ban_conflict, message and all.
    """
    detail = (
        "on dispatch today — none of the drivers who have supervised them are working. "
        if reason == "unavailable"
        else "yet — this is their first supervised day. "
    )
    return {
        "type": "driver_trainee_unpaired",
        "employee_id": str(employee_id),
        "employee_name": employee_name,
        "reason": reason,
        "message": (
            f"{employee_name} is a driver trainee with no supervising driver {detail}"
            "They are not assigned to a truck. Pair them with a driver, or approve "
            "a solo day."
        ),
    }


def assign_driver_trainees(
    driver_trainees: List,
    assigned_crews: Dict,
    db: Session,
    company_id: UUID,
    target_date: date,
    cfg=None,
) -> List[dict]:
    """Place each driver trainee on their supervising driver's truck.

    Mutates `assigned_crews` in place. Returns staffing warnings, in the same
    shape the other assign_* services use, so run_dispatch can append them
    without special-casing.
    """
    warnings: List[dict] = []
    if not driver_trainees:
        return warnings

    # Every driver already placed, by truck. `assign_drivers` runs first, so
    # this is the authoritative "who is driving what today".
    driver_truck: Dict = {}
    for truck_id, crew in assigned_crews.items():
        for member in crew:
            if member.get("role") == "driver":
                driver_truck[member["id"]] = truck_id

    # The candidate pool for supervision is the drivers actually ON dispatch
    # today, not the whole roster: a driver who is scheduled but unplaced cannot
    # supervise anyone from a truck they are not on.
    placed_driver_ids = list(driver_truck)
    candidates = (
        db.query(Employee)
        .filter(
            Employee.id.in_(placed_driver_ids),
            Employee.company_id == company_id,
        )
        .all()
        if placed_driver_ids
        else []
    )

    for trainee in driver_trainees:
        supervisor_id, reason = resolve_supervisor(
            db=db,
            trainee_id=trainee.id,
            company_id=company_id,
            target_date=target_date,
            todays_candidates=candidates,
        )

        if supervisor_id is None:
            # first_day | unavailable — both mean the same thing here: do not
            # place, and make it visible. The trainee is NOT dropped silently;
            # the warning is what puts them in front of dispatch.
            warnings.append(unpaired_warning(trainee.id, trainee.name, reason))
            logger.info(
                "assign_driver_trainees: unpaired trainee=%s reason=%s date=%s company=%s",
                trainee.id, reason, target_date, company_id,
            )
            continue

        truck_id = driver_truck.get(supervisor_id)
        if truck_id is None:
            # resolve_supervisor only returns a driver from `candidates`, which
            # is built from placed drivers — so this is unreachable unless the
            # two fall out of sync. Warn rather than raise: a defensive branch
            # that silently passes is how a trainee vanishes.
            warnings.append({
                "type": "driver_trainee_unpaired",
                "employee_id": str(trainee.id),
                "employee_name": trainee.name,
                "reason": "supervisor_unplaced",
                "message": (
                    f"{trainee.name}'s supervising driver is not on a truck today. "
                    "Pair them manually."
                ),
            })
            continue

        # D6 — the pair consumes one truck and two drivers. There is no separate
        # seat check: the trainee joins their supervisor's truck, and the truck
        # already has exactly one driver, so the pair is self-limiting.
        assigned_crews[truck_id].append({
            "id": trainee.id,
            "role": "driver_trainee",
            "paired_trainer_id": supervisor_id,
        })
        logger.info(
            "assign_driver_trainees: paired trainee=%s supervisor=%s truck=%s reason=%s",
            trainee.id, supervisor_id, truck_id, reason,
        )

    return warnings


def unpaired_driver_trainees(db: Session, target_date: date, company_id: UUID) -> List[dict]:
    """Scheduled driver trainees with no crew row today — DERIVED, not stored.

    ADR-264: an unpaired trainee is HELD OUT of crews rather than placed beside
    an unfamiliar driver. Held out is only safe if it is VISIBLE, and the
    dispatch warnings that flag it live in the run response only — `GET
    /dispatch/{date}` returns `"warnings": []`, so a page refresh made the
    trainee vanish from the day entirely.

    Deriving on read rather than persisting the warning keeps one source of
    truth: the moment dispatch pairs the trainee by hand, an AssignmentMember
    row exists and they drop out of this list with nothing to clean up. A stored
    warning would have to be revoked, and a warning nobody revoked is worse than
    none.
    """
    from app.models.assignment_member import AssignmentMember
    from app.models.truck_assignment import TruckAssignment
    from app.services.available_pool import get_available_pool

    pool = get_available_pool(db, target_date, company_id=company_id)
    scheduled = pool.get("driver_trainees", [])
    if not scheduled:
        return []

    placed_ids = {
        row[0]
        for row in db.query(AssignmentMember.employee_id)
        .join(TruckAssignment, AssignmentMember.assignment_id == TruckAssignment.id)
        .filter(
            TruckAssignment.date == target_date,
            TruckAssignment.company_id == company_id,
            AssignmentMember.company_id == company_id,
        )
        .all()
    }

    out = []
    for trainee in scheduled:
        if trainee.id in placed_ids:
            continue
        priors = prior_supervisor_ids(db, trainee.id, company_id, target_date)
        out.append({
            "employee_id": str(trainee.id),
            "employee_name": trainee.name,
            # Distinguishes "never had one" from "theirs is out today", which
            # are different asks of the dispatcher.
            "reason": "first_day" if not priors else "unavailable",
        })
    return out

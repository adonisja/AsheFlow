"""ADR-264 D9 — who may supervise a driver trainee, in one place.

THE POINT OF THIS MODULE
------------------------
`field_supervisor` and `captain` are real roles that arrive in their own work.
When they do, "who can supervise a driver trainee" must change in exactly one
place. Every call site — dispatch pairing, the replacement suggester when a
supervisor declines, and manual assignment — goes through the predicate below.

**Never inline `role == "driver"` at a supervision check.** An inlined
comparison is precisely what makes threading a new role expensive later, and
this codebase has precedent for role lists drifting between call sites (the
`_allow_*` bundles in walker_routes.py, and ADR-211's consecutive-penalty bug,
which was a filter that had quietly stopped matching what its callers assumed).

WHY A DRIVER AND NOT A TRAINER
------------------------------
A walker `trainer` trains walkers. Drivers are trained by drivers: the trainee
drives and is the main worker for the day, and the supervisor assists from the
same truck (operator, 2026-08-07). A trainer has no vehicle or load-custody
authority to pass on, so the walker training role is not reusable here despite
the similar shape.
"""
from typing import Iterable, Optional
from uuid import UUID

# The roles that may supervise a driver trainee for a day.
#
# `field_supervisor` and `captain` are deliberately ABSENT until those roles
# carry the operational authority this implies — ADR-264 D9 builds the seam, not
# the roles. Adding one here is the whole change; no call site needs editing.
SUPERVISING_ROLES: frozenset[str] = frozenset({"driver"})


def can_supervise_driver_trainee(employee) -> bool:
    """True when `employee` may supervise a driver trainee today.

    Deliberately takes the employee OBJECT rather than a role string: an
    inactive driver is not a candidate, and a caller passing `employee.role`
    alone would silently skip that check. Making the wider fact the argument
    makes the narrower mistake unavailable.
    """
    if employee is None:
        return False
    return bool(getattr(employee, "is_active", False)) and getattr(employee, "role", None) in SUPERVISING_ROLES


def eligible_supervisors(employees: Iterable) -> list:
    """The subset of `employees` that may supervise, order preserved.

    Used by the replacement suggester (D7) when a supervising driver declines.
    A list rather than a generator so callers can take len() without consuming
    it — the "no free supervisor" branch needs the count.
    """
    return [e for e in employees if can_supervise_driver_trainee(e)]


# ---------------------------------------------------------------------------
# Continuity: who supervised this trainee last (ADR-264 D5 addendum, 2026-08-22)
# ---------------------------------------------------------------------------
#
# The rule is CONTINUITY, not eligibility. The first day is paired by hand; every
# day after reuses the previous supervisor when they are available. A driver
# trainee taught by a different driver each day gets five disconnected
# impressions instead of one accumulating relationship, and the supervisor who
# signs the observation phase should be someone who watched the earlier ones.
#
# NOTHING IS RECORDED ABOUT THE SUPERVISING DRIVER (operator, 2026-08-22).
# `driver_trainer_id` is written on the TRAINEE's record and read only to answer
# "who supervised last time". The supervising driver is a driver doing their
# normal job who happens to have a trainee with them — they are not in a
# training program, so no TrainerMark, no phase, no debt, no attribution
# accrues to them.
#
# This is why record_trainer_mark's `if not record.trainer_id: return None`
# gate is CORRECT rather than a gap: a driver trainee's record leaves
# trainer_id NULL, so no mark is issued. Do not "fix" that by falling back to
# driver_trainer_id — the walker TrainerMark machinery measures a walker
# trainer's performance and has no counterpart here.
#
# The system NEVER picks a substitute on its own. When the previous supervisor
# is unavailable the trainee stays unpaired and dispatch is asked — the same
# principle as D7's "solo is an explicit dispatch approval, never a fallback".


def previous_supervisor_id(db, trainee_id, company_id, before_date) -> Optional[UUID]:
    """The driver who supervised this trainee most recently, or None.

    Reads `TrainingRecord.driver_trainer_id` — already one row per trainee per
    day, so there is no new state to keep in sync. Deliberately NOT `trainer_id`,
    which is the walker trainer (D5, revised 2026-08-22).

    Solo days (`supervised=False`) carry a NULL supervisor and are skipped by the
    NOT NULL filter rather than ending the lookup: a trainee whose supervisor was
    absent yesterday is still re-paired with the driver from the day before.
    """
    from app.models.training import TrainingRecord

    row = (
        db.query(TrainingRecord.driver_trainer_id)
        .filter(
            TrainingRecord.trainee_id == trainee_id,
            TrainingRecord.company_id == company_id,
            TrainingRecord.record_date < before_date,
            TrainingRecord.driver_trainer_id.isnot(None),
        )
        .order_by(TrainingRecord.record_date.desc())
        .first()
    )
    return row[0] if row else None


def resolve_supervisor(db, trainee_id, company_id, target_date, todays_candidates) -> tuple[Optional[UUID], str]:
    """Pick today's supervisor for a driver trainee.

    Returns `(supervisor_id, reason)` where reason is one of:

        "continuity"    — the previous supervisor is here and eligible
        "first_day"     — no prior record; dispatch assigns by hand
        "unavailable"   — previous supervisor is not on today's dispatch

    Both `None` outcomes are the SAME instruction to the caller: leave the
    trainee unpaired and notify dispatch. They are distinguished only so the
    notification can say which it is — "assign a supervisor for their first day"
    reads differently from "yesterday's supervisor is out".

    `todays_candidates` is the pool of employees on today's dispatch; the caller
    supplies it because who counts as "on dispatch" differs between run_dispatch
    (building crews in memory) and the manual assign path (reading rows).
    """
    prev_id = previous_supervisor_id(db, trainee_id, company_id, target_date)
    if prev_id is None:
        return None, "first_day"

    for c in todays_candidates:
        if getattr(c, "id", None) == prev_id and can_supervise_driver_trainee(c):
            return prev_id, "continuity"
    return None, "unavailable"

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


def prior_supervisor_ids(db, trainee_id, company_id, before_date) -> list:
    """Every driver who has supervised this trainee, most recent first.

    A LIST, not a single id (operator, 2026-08-22). Continuity spans the whole
    supervisor history: if yesterday's driver is out, the trainee is re-paired
    with an EARLIER supervising driver who is here today, before dispatch is
    asked. Each of them has already watched this trainee work, which is the
    thing continuity is protecting.

    Reads `TrainingRecord.driver_trainer_id` — one row per trainee per day, so
    no new state. Deliberately NOT `trainer_id`, which is the walker trainer
    (D5, revised 2026-08-22).

    Solo days carry a NULL supervisor and drop out via the NOT NULL filter
    rather than ending the walk.
    """
    from app.models.training import TrainingRecord

    rows = (
        db.query(TrainingRecord.driver_trainer_id, TrainingRecord.record_date)
        .filter(
            TrainingRecord.trainee_id == trainee_id,
            TrainingRecord.company_id == company_id,
            TrainingRecord.record_date < before_date,
            TrainingRecord.driver_trainer_id.isnot(None),
        )
        .order_by(TrainingRecord.record_date.desc())
        .all()
    )
    # Deduplicate while preserving recency order: a driver who supervised on
    # three separate days is one candidate, ranked by their most recent day.
    seen, out = set(), []
    for supervisor_id, _ in rows:
        if supervisor_id not in seen:
            seen.add(supervisor_id)
            out.append(supervisor_id)
    return out


def resolve_supervisor(db, trainee_id, company_id, target_date, todays_candidates) -> tuple:
    """Pick today's supervisor for a driver trainee.

    Returns `(supervisor_id, reason)`:

        "continuity"   — their most recent supervisor is here and eligible
        "prior"        — an EARLIER supervising driver is here instead
        "first_day"    — no supervisor has ever been recorded
        "unavailable"  — every prior supervisor is off today

    The two `None` outcomes mean the same thing to the caller: do NOT place this
    trainee on a truck, and alert dispatch (operator, 2026-08-22). They are
    distinguished only so the alert can say which — "assign a supervisor for
    their first day" reads differently from "none of their supervisors are in".

    The system never pairs a trainee with a driver who has not supervised them
    before. A new supervising relationship is always a human decision, the same
    principle as D7's "solo is an explicit dispatch approval, never a fallback".
    """
    priors = prior_supervisor_ids(db, trainee_id, company_id, target_date)
    if not priors:
        return None, "first_day"

    by_id = {
        getattr(c, "id", None): c
        for c in todays_candidates
        if can_supervise_driver_trainee(c)
    }
    for rank, supervisor_id in enumerate(priors):
        if supervisor_id in by_id:
            # rank 0 is the most recent supervisor; anything later is a
            # fallback to an earlier one, which is still continuity but worth
            # distinguishing in the audit trail and the crew view.
            return supervisor_id, "continuity" if rank == 0 else "prior"
    return None, "unavailable"

"""ADR-264 D10 (revised 2026-08-22) — who is ready to become a driver.

THE DECISION IS A PERSON, NOT A SCORE
-------------------------------------
There is no driver graduation quiz. A driver trainee completes their phases and
**dispatch/management approves the promotion explicitly**; the supervising
driver's observation is input to that decision, not the decision itself. A
driving assessment is a judgement about road conduct that no question bank
stands in for.

This diverges from the walker track on purpose. There, `graduate_trainees`
promotes automatically on a passed quiz because the quiz IS the sign-off.

A MISSING VERDICT DOES NOT BLOCK THE PROMOTION
----------------------------------------------
If the observation phase closed with nothing recorded, the trainee is treated as
**successful** and dispatch is alerted to promote them (operator, 2026-08-22).
The likeliest explanation is that observation went fine and the supervising
driver forgot to write it down, and withholding someone's promotion over another
person's missing paperwork is the wrong default.

The honesty comes from two follow-ups rather than from blocking:

- the supervising driver is prompted to complete the documentation, and
- an observation that actually went badly is recorded as a note, after which
  dispatch assigns a driver to observe them again **while they keep the driver
  role**.

So an unrecorded bad day is recoverable through supervision, not demotion.
"""
import logging
from datetime import date
from typing import List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.employee import Employee
from app.models.training import TrainingRecord
from app.services.company_config import get_company_config
from app.services.training_phases import TRACK_DRIVER, phase_plan

logger = logging.getLogger(__name__)


def driver_trainees_awaiting_promotion(
    db: Session, target_date: date, company_id: UUID, cfg=None
) -> List[dict]:
    """Driver trainees who have finished their phases and need a decision.

    Returns one dict per trainee, each carrying what the approver needs to
    decide: who supervised the observation, whether a verdict was recorded, and
    what that verdict was.

    `verdict`:
        "passed"      — the supervising driver recorded a pass
        "failed"      — recorded a fail; promote anyway is still the operator's
                        call, but the note travels with it
        "unrecorded"  — nothing recorded. Treated as SUCCESSFUL for the purposes
                        of prompting a promotion, with a documentation nudge.
    """
    cfg = cfg or get_company_config(db, company_id)
    plan = phase_plan(cfg, TRACK_DRIVER)

    trainees = (
        db.query(Employee)
        .filter(
            Employee.role == "driver_trainee",
            Employee.is_active == True,
            Employee.company_id == company_id,
        )
        .all()
    )
    if not trainees:
        return []

    out: List[dict] = []
    for trainee in trainees:
        # The observation phase record — the LAST phase, derived from the plan
        # (D3), never a hardcoded number.
        obs = (
            db.query(TrainingRecord)
            .filter(
                TrainingRecord.trainee_id == trainee.id,
                TrainingRecord.company_id == company_id,
                TrainingRecord.current_day_number == plan.observation,
                TrainingRecord.record_date <= target_date,
            )
            .order_by(TrainingRecord.record_date.desc())
            .first()
        )
        if obs is None or not obs.phase_closed:
            # Still in the program. Not an error, and not reported: the crew
            # view already shows them as a driver trainee.
            continue

        # A solo day cannot close a phase (D8), so a closed observation phase
        # was supervised by definition — but read the supervisor rather than
        # assuming, because the record is the evidence a human will act on.
        if obs.passed is True:
            verdict = "passed"
        elif obs.passed is False:
            verdict = "failed"
        else:
            verdict = "unrecorded"

        out.append({
            "employee_id": str(trainee.id),
            "employee_name": trainee.name,
            "observation_date": obs.record_date.isoformat() if obs.record_date else None,
            "supervisor_id": str(obs.driver_trainer_id) if obs.driver_trainer_id else None,
            "verdict": verdict,
            "score": obs.score,
            "notes": obs.observation_notes,
        })

    return out


def promotion_warning(entry: dict) -> dict:
    """The dispatch-run warning for one trainee awaiting promotion.

    Built here rather than at each call site because the dispatch run and any
    read surface must word the same condition identically — different wording
    for one situation reads as two situations.
    """
    name = entry["employee_name"]
    verdict = entry["verdict"]

    if verdict == "passed":
        detail = "Their supervising driver recorded a pass."
    elif verdict == "failed":
        detail = (
            "Their supervising driver recorded a FAIL — promote and assign a driver "
            "to observe them again, or hold the promotion. The note is on the record."
        )
    else:
        detail = (
            "No verdict was recorded. Treat as successful and promote; the supervising "
            "driver still needs to complete the documentation."
        )

    return {
        "type": "driver_trainee_awaiting_promotion",
        "employee_id": entry["employee_id"],
        "employee_name": name,
        "verdict": verdict,
        "message": (
            f"🎓 **{name} has completed the driver training program.** {detail} "
            "Promote them to driver from the employee page."
        ),
    }

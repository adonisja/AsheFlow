import logging
from datetime import date, datetime, timezone
from typing import Dict, List, Optional
from uuid import UUID
from sqlalchemy.orm import Session
from app.models.training import TrainingRecord, TrainingTask, TrainingCurriculum
from app.models.employee import Employee
from app.models.trainer_continuation_request import TrainerContinuationRequest
from app.services.company_config import ResolvedConfig

logger = logging.getLogger(__name__)

# Phases 1–3 are curriculum phases. Phase 4 is observation (auto-generated).
# Phase 5 is the quiz day (walk-along + quiz issued by management).
# Phase 6+ is remediation after a failed quiz. Never injected by score_phase4 path here.
MAX_CURRICULUM_PHASE = 4

# Which curriculum track dispatch-time injection assigns (ADR-263). Trainees are
# walkers — walker_routes.py::_WALKER_ROLES is {"walker", "trainee"} — and this
# service only ever processes crew members with role == "trainee".
#
# A constant rather than a lookup because there is currently no driver-trainee:
# drivers are trained by other drivers via a temporary driver-trainer role that
# is not yet modelled (ADR-263 "Deferred"). This becomes a per-trainee lookup
# when that lands.
TRAINEE_CURRICULUM_ROLE = "walker"


def inject_curriculum(db: Session, target_date: date, assigned_crews: Dict[str, List[Dict]], cfg: ResolvedConfig = None, company_id: Optional[UUID] = None) -> None:
    """
    Hook called at dispatch publish time to auto-generate daily training records
    for all trainees assigned today.

    Phase advancement logic (ADR-046):
    - A phase advances ONLY if the previous record's phase_closed = True.
    - If phase_closed = False, the trainee stays in the same phase.
    - Missed days do not incur debt or penalties — phases only move on days
      the DA is physically dispatched and present.
    - Phase 4 tasks are auto-generated from all mandatory Phase 1–3 curriculum
      items as demonstration tasks, not from a static Phase 4 curriculum.
    - Phase 5 is the quiz day: a single walk-along task is injected so the trainer
      has a record; the quiz itself lives in GraduationQuiz (issued by management).
    - Phase 6+ remediation records are created by generate_quiz_remediation or
      score_phase4 (Phase 4 fail path). They are never injected here on first visit.
    """
    # 1. Identify all trainees and their paired trainer from today's crews.
    # paired_trainer_id is persisted on AssignmentMember (set during dispatch) and
    # passed through in the crew dict — use it directly rather than inferring from
    # truck position, which breaks when a truck has multiple trainers.
    trainees_in_crews = []
    skipped_driver_trainees = 0
    for truck_id, crew in assigned_crews.items():
        for member in crew:
            if member["role"] == "trainee":
                trainees_in_crews.append((member["id"], member.get("paired_trainer_id")))
            elif member["role"] == "driver_trainee":
                # ADR-256 added 'driver_trainee' to ck_assignment_members_role so the
                # slot is now INSERTABLE, but no track trains it: ADR-264 (proposed)
                # owns that and is unimplemented. Injecting TRAINEE_CURRICULUM_ROLE
                # here would hand a driver trainee walker material — the exact failure
                # the role scoping above exists to prevent.
                # Counted and logged, never silent: an invisible skip is how a trainee
                # goes a whole program with no records and nobody finds out.
                skipped_driver_trainees += 1

    if skipped_driver_trainees:
        logger.warning(
            "inject_curriculum: date=%s skipped %d driver_trainee crew member(s) — "
            "the driver training track (ADR-264) is not implemented; no training "
            "records were created for them",
            target_date, skipped_driver_trainees,
        )

    logger.info("inject_curriculum: date=%s trainees=%d", target_date, len(trainees_in_crews))
    if not trainees_in_crews:
        logger.debug("inject_curriculum: no trainees in crews for date=%s — skipping", target_date)
        return

    # 2. Lock past records that are still open (past date, not yet locked)
    unlocked_past = db.query(TrainingRecord).filter(
        TrainingRecord.company_id == company_id,
        TrainingRecord.record_date < target_date,
        TrainingRecord.is_locked == False,
    ).all()
    for rec in unlocked_past:
        rec.is_locked = True
    if unlocked_past:
        db.flush()

    # 3. Fetch full curriculum, grouped by phase.
    #
    # Scoped by company_id AND by role (ADR-263). Both filters matter:
    #   - company_id: without it this reads every tenant's curriculum and injects
    #     Company B's topics into Company A's trainee records (Dimension 1).
    #   - roles: without it a walker trainee receives driver vehicle-safety items,
    #     and the Phase 4 mirroring below promotes them to MANDATORY demonstration
    #     tasks that block graduation — a walker trainer asked to observe a
    #     walker, who has no vehicle, performing a pre-trip vehicle inspection.
    #
    # Trainees are walkers (walker_routes.py::_WALKER_ROLES), so this service —
    # which only ever handles role == "trainee" crew members — always wants the
    # walker track. Driver curriculum reaches drivers through the curriculum read
    # endpoints, not through dispatch-time injection: `trainer` is a WALKER
    # trainer and never supervises a driver, and the temporary driver-trainer
    # role that would pair a driver trainee is not yet modelled (ADR-263
    # "Deferred"). When it is, TRAINEE_CURRICULUM_ROLE below becomes a lookup on
    # the trainee's own role rather than a constant.
    curriculum = [
        item
        for item in db.query(TrainingCurriculum)
        .filter(TrainingCurriculum.company_id == company_id)
        .order_by(TrainingCurriculum.day_number)
        .all()
        # Role filter applied in Python, not SQL: `roles` is a Postgres text[] in
        # production but JSON under the SQLite test engine, and `.any()` compiles
        # on neither uniformly. The curriculum is a small per-tenant table (tens
        # of rows), so the filter is free here and stays dialect-agnostic.
        if TRAINEE_CURRICULUM_ROLE in (item.roles or [])
    ]
    curriculum_by_phase: Dict[int, List[TrainingCurriculum]] = {}
    for item in curriculum:
        curriculum_by_phase.setdefault(item.day_number, []).append(item)

    # Mandatory Phase 1–3 items for Phase 4 observation generation
    mandatory_phases_1_3 = [
        item for item in curriculum
        if item.day_number in (1, 2, 3) and item.is_mandatory
    ]

    # An empty curriculum must not silently produce empty phases that auto-close
    # as complete (Dimension 5 — no silent drops). Log loudly; the caller cannot
    # meaningfully train anyone in this state.
    if not curriculum:
        logger.error(
            "inject_curriculum: NO curriculum rows for company_id=%s role=%s — "
            "trainees will receive empty phases. Seed the curriculum.",
            company_id, TRAINEE_CURRICULUM_ROLE,
        )

    for trainee_id, trainer_id in trainees_in_crews:
        # --- Continuation request resolution ---
        active_request = db.query(TrainerContinuationRequest).filter(
            TrainerContinuationRequest.trainee_id == trainee_id,
            TrainerContinuationRequest.status == "accepted",
        ).first()

        if active_request:
            requested_trainer_id = active_request.trainer_id
            trainer_available = any(
                any(m["id"] == requested_trainer_id and m["role"] == "trainer" for m in crew)
                for crew in assigned_crews.values()
            )
            if trainer_available:
                trainer_id = requested_trainer_id
            active_request.status = "nullified"
            active_request.resolved_at = datetime.now(timezone.utc)

        # Auto-expire still-pending requests
        pending_request = db.query(TrainerContinuationRequest).filter(
            TrainerContinuationRequest.trainee_id == trainee_id,
            TrainerContinuationRequest.status == "pending",
        ).first()
        if pending_request:
            pending_request.status = "nullified"
            pending_request.resolved_at = datetime.now(timezone.utc)

        db.flush()

        # --- If record already exists for today, delete and recreate it.
        # Updating trainer_id in place would leave tasks generated for the old
        # pairing/phase intact. Full deletion lets the creation path below run
        # fresh so phase logic, debt rollover, and task generation are correct.
        existing_record = db.query(TrainingRecord).filter(
            TrainingRecord.trainee_id == trainee_id,
            TrainingRecord.record_date == target_date,
        ).first()

        if existing_record:
            db.query(TrainingTask).filter(
                TrainingTask.training_record_id == existing_record.id
            ).delete()
            db.delete(existing_record)
            db.flush()

        # --- Determine current phase ---
        prev_records = db.query(TrainingRecord).filter(
            TrainingRecord.trainee_id == trainee_id,
            TrainingRecord.record_date < target_date,
        ).order_by(TrainingRecord.record_date.desc()).all()

        if not prev_records:
            # First ever dispatch day for this trainee
            current_phase = 1
        else:
            last_record = prev_records[0]

            if last_record.current_day_number == MAX_CURRICULUM_PHASE and last_record.phase_closed:
                # Phase 4 closed — next dispatch day is the quiz day (Phase 5).
                # The quiz itself is issued separately by management; injection only
                # creates the walk-along task so the trainer has a record.
                current_phase = 5
            elif last_record.current_day_number == 5 and last_record.phase_closed:
                # Quiz day closed — quiz passed (graduation handled separately) or
                # quiz failed (generate_quiz_remediation created a Phase 6 record).
                # Either way, this trainee's training is complete at dispatch level.
                continue
            elif last_record.current_day_number >= 6 and last_record.phase_closed:
                # Remediation phase closed — another quiz day is needed.
                current_phase = 5
            elif last_record.phase_closed:
                # Normal phase advancement (Phases 1–3)
                current_phase = last_record.current_day_number + 1
            else:
                # Phase not yet closed — DA stays in same phase
                current_phase = last_record.current_day_number

        logger.info("inject_curriculum: creating phase=%d record for trainee=%s trainer=%s date=%s", current_phase, trainee_id, trainer_id, target_date)
        # --- Create the new record ---
        new_record = TrainingRecord(
            trainee_id=trainee_id,
            trainer_id=trainer_id,
            record_date=target_date,
            current_day_number=current_phase,
            phase_closed=False,
            extended=False,
            company_id=company_id,
        )
        db.add(new_record)
        db.flush()

        # --- Roll over debt from previous uncompleted mandatory coverage tasks ---
        debt_tasks = []
        if prev_records:
            prev_record_ids = [r.id for r in prev_records]
            uncompleted_mandatory = db.query(TrainingTask).filter(
                TrainingTask.training_record_id.in_(prev_record_ids),
                TrainingTask.is_mandatory == True,
                TrainingTask.is_completed == False,
                TrainingTask.record_type == "coverage",
            ).all()

            # Deduplicate by topic title
            seen_titles = set()
            for task in uncompleted_mandatory:
                if task.topic_title not in seen_titles:
                    seen_titles.add(task.topic_title)
                    debt_tasks.append(task)

        for dt in debt_tasks:
            new_debt_age = (dt.debt_age or 0) + 1
            debt_task = TrainingTask(
                training_record_id=new_record.id,
                topic_title=dt.topic_title,
                description=dt.description,
                is_mandatory=True,
                is_training_debt=True,
                record_type="coverage",
                debt_age=new_debt_age,
                is_escalated=new_debt_age >= (cfg.debt_escalation_threshold if cfg else 3),
                company_id=company_id,
            )
            db.add(debt_task)

        # --- Add tasks for current phase ---
        if current_phase == 4:
            # Phase 4: observation tasks auto-generated from mandatory Phase 1–3 items
            for item in mandatory_phases_1_3:
                new_task = TrainingTask(
                    training_record_id=new_record.id,
                    topic_title=item.topic_title,
                    description=item.description,
                    record_type="demonstration",
                    is_mandatory=True,
                    is_training_debt=False,
                    company_id=company_id,
                )
                db.add(new_task)
        elif current_phase == 5:
            # Phase 5 (quiz day): single walk-along task for the trainer's record.
            # The quiz itself is in GraduationQuiz — issued separately by management.
            # No curriculum tasks, no debt rollover. Trainer confirms walk-along complete.
            new_task = TrainingTask(
                training_record_id=new_record.id,
                topic_title="Quiz Day Walk-Along",
                description=(
                    "Trainee is completing their graduation quiz today. "
                    "Proceed as a normal walk-along shift after the morning quiz session. "
                    "Mark this task complete once the walk-along portion of the shift is done."
                ),
                record_type="coverage",
                is_mandatory=True,
                is_training_debt=False,
                company_id=company_id,
            )
            db.add(new_task)
        elif current_phase >= 6:
            # Phase 6+ (remediation): tasks are generated by generate_quiz_remediation
            # when the manager sends the trainee for further training. On the first
            # dispatch day into remediation, the record was already created by that
            # service with targeted tasks — we should not overwrite it here.
            # If we reach this branch it means a new remediation day on the same
            # open record: no new tasks needed, debt rollover above handles carry-over.
            pass
        else:
            # Phases 1–3: add coverage tasks from curriculum
            phase_items = curriculum_by_phase.get(current_phase, [])
            debt_titles = {dt.topic_title for dt in debt_tasks}
            for ct in phase_items:
                if ct.topic_title in debt_titles:
                    continue  # already added as debt task, don't duplicate
                new_task = TrainingTask(
                    training_record_id=new_record.id,
                    topic_title=ct.topic_title,
                    description=ct.description,
                    record_type="coverage",
                    is_mandatory=ct.is_mandatory,
                    is_training_debt=False,
                    company_id=company_id,
                )
                db.add(new_task)

    db.commit()

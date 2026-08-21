import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, Integer, Float, Date, Text, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.dialects.sqlite import JSON as SQLiteJSON
from sqlalchemy.sql import func
from app.models.base import Base

# Valid values for TrainingCurriculum.roles (ADR-263). A subset of
# employee.VALID_ROLES — only roles that actually have a training track.
#
# "walker" covers trainees and the trainers who supervise them
# (walker_routes.py::_WALKER_ROLES). Note that `trainer` means WALKER trainer
# specifically — it is not a general supervision role, and a trainer never
# trains a driver. Drivers train drivers: ADR-264 pairs a driver_trainee with a
# supervising DRIVER on the same truck via AssignmentMember.paired_trainer_id —
# no new role, since the supervisor stays a driver. ADR-264 is proposed and
# unimplemented; the `driver_trainee` enum value exists (ADR-256) but nothing
# trains or promotes it yet.
#
# "driver" is the vehicle / load-custody / crew-custody track.
CURRICULUM_ROLES: frozenset[str] = frozenset({"walker", "driver"})


class TrainingCurriculum(Base):
    """
    Template for the 4-phase training cycle topics.

    day_number here means "phase number" (1–4). Phases are curriculum units,
    not calendar dates — a phase advances when all mandatory tasks are complete,
    regardless of how many calendar days it took. See ADR-046.

    record_type:
      "coverage"     — trainer confirms they taught this topic (Phases 1–3)
      "demonstration"— trainer observes DA performing this skill (Phase 4)

    Phase 4 rows are NOT seeded statically. training_injection auto-generates
    Phase 4 tasks by mirroring all mandatory Phase 1–3 items as demonstration tasks.
    """
    __tablename__ = "training_curriculums"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    day_number  = Column(Integer, nullable=False, index=True)   # phase number: 1–4
    topic_title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    is_mandatory = Column(Boolean, nullable=False, default=True)
    category    = Column(String(50), nullable=True)             # app_setup|policy|delivery_standards|delivery_types|scorecard|vehicle_safety|crew_ops|observation
    record_type = Column(String(20), nullable=False, default="coverage")  # coverage|demonstration

    # Which training track(s) this item belongs to (ADR-263). Multi-valued so a
    # shared item — ADP, Discord, attendance, the whole scorecard-literacy block —
    # is ONE row carrying {"walker", "driver"} rather than two rows that drift
    # apart the first time someone edits one and not the other.
    #
    # Assignment: a trainee receives rows where their role is in `roles`.
    # Trainer/trainee -> "walker" (walker_routes.py::_WALKER_ROLES); drivers ->
    # "driver". Query with .roles.any("walker") — NOT `== ["walker"]`, which
    # would miss every shared item.
    # Dialect variant: Postgres gets a real text[] (so `.any()` compiles to a
    # native array containment check); SQLite — which the test suite runs on —
    # has no array type and gets JSON. Without the variant, model creation fails
    # under SQLite with "can't render element of type ARRAY" and every test that
    # touches this table errors at table-create time.
    roles = Column(
        ARRAY(String(20)).with_variant(SQLiteJSON(), "sqlite"),
        nullable=False,
        server_default="{walker}",
        default=lambda: ["walker"],
    )


class TrainingRecord(Base):
    """
    Stateful log representing a trainee's training session for a given phase.

    current_day_number = phase number (1–4). Advances only when phase_closed = True
    on the previous record. A missed dispatch day leaves the trainee in the same
    phase with no penalty — phases only advance on days the DA is physically present.

    Phase 4 records use passed/score/observation_notes instead of trainer_comments
    for their primary output. trainer_comments is still available for any phase.

    submitted_at: set when the trainer explicitly submits the record (by midnight).
    phase_closed: set True when all mandatory coverage tasks are complete.
    extended: set True if Phase 4 failed and a Phase 6 remediation record was generated.
    """
    __tablename__ = "training_records"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    trainee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    trainer_id = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True, index=True)

    record_date        = Column(Date, nullable=False, index=True)
    # phase: 0 = ORE day, 1–4 normal, 5 = quiz day, 6+ = remediation
    #
    # ADR-281: phase 0 is the ORE day. ORE itself is self-serve e-learning on
    # Amazon's platform, but the DAY is supervised — a trainer walks the new
    # hire through app install, website access and the procedures on the page.
    # So phase 0 uses the same coverage-task model as 1–3 and closes the same
    # way; nothing here is special-cased for it.
    current_day_number = Column(Integer, nullable=False)

    trainer_comments  = Column(Text, nullable=True)
    manager_comments  = Column(Text, nullable=True)

    # Trainee's review of the trainer (submitted via /record/{id}/review).
    # RESTORED 2026-07-10: dropped as "orphaned" by migration j1k2l3m4n5o6
    # after being removed from the ORM — but the review endpoint, schemas, and
    # both rating UIs still used them, so assigning the unmapped attribute
    # silently persisted NOTHING (200 OK, no write). A column referenced by an
    # endpoint is not an orphan.
    trainee_comments  = Column(Text, nullable=True)
    trainer_rating    = Column(Integer, nullable=True)   # 1–5 stars

    # Phase gate tracking
    submitted_at    = Column(DateTime(timezone=True), nullable=True)
    phase_closed    = Column(Boolean, nullable=False, default=False)
    phase_closed_at = Column(DateTime(timezone=True), nullable=True)

    # ── ADR-281: Phase 0 (ORE day) ──────────────────────────────────────────
    # The ATTESTATION is permanent; the FILE is not. Retention for the
    # certificate is 48h (it carries the trainee's name and an Amazon training
    # id), so if the file were the completion signal, the signal would evaporate
    # on day three. These two columns are the durable record that ORE was done.
    ore_completed_at             = Column(DateTime(timezone=True), nullable=True)
    ore_certificate_uploaded_by  = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    # S3 object key, nulled by the nightly sweep once the object is deleted.
    # A NULL key with a non-null ore_completed_at means "certificate expired",
    # which is a different answer to a manager than "never uploaded".
    ore_certificate_key          = Column(String(300), nullable=True)
    ore_certificate_expires_at   = Column(DateTime(timezone=True), nullable=True)

    # Early departure after ORE — a PERMITTED choice (ADR-281 D5), recorded
    # because it affects pay for that date. Deliberately NOT fed to the
    # scorecard, and deliberately NOT counted across the programme: a tally is
    # a judgement waiting for a threshold.
    left_early     = Column(Boolean, nullable=False, server_default="false")
    left_early_at  = Column(DateTime(timezone=True), nullable=True)

    # Phase 4 outcome
    passed            = Column(Boolean, nullable=True)   # null until Phase 4 submitted
    score             = Column(Float, nullable=True)     # 0.0–100.0, Phase 4 only
    observation_notes = Column(Text, nullable=True)      # Phase 4 free-form commentary
    extended          = Column(Boolean, nullable=False, default=False)

    is_locked  = Column(Boolean, nullable=False, default=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class TrainingTask(Base):
    """
    Actual tasks assigned to a specific TrainingRecord.
    Tracks check-offs, training debt, and trainer coverage.

    record_type:
      "coverage"     — trainer confirms they taught this topic (Phases 1–3)
      "demonstration"— trainer observes DA performing this in the field (Phase 4)

    completed_late: True when a coverage task was completed after the next phase
    was already opened (only possible via management force-unlock override).
    """
    __tablename__ = "training_tasks"

    id                 = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id         = Column(UUID(as_uuid=True), nullable=False, index=True)
    training_record_id = Column(UUID(as_uuid=True), ForeignKey("training_records.id", ondelete="CASCADE"), nullable=False, index=True)

    # Snapshot of the curriculum task, ensuring historical consistency
    topic_title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    record_type      = Column(String(20), nullable=False, default="coverage")  # coverage|demonstration
    is_completed     = Column(Boolean, nullable=False, default=False)
    is_mandatory     = Column(Boolean, nullable=False, default=True)
    is_training_debt = Column(Boolean, nullable=False, default=False)

    # Debt tracking
    debt_age     = Column(Integer, nullable=False, default=0)
    is_escalated = Column(Boolean, nullable=False, default=False)

    # Completion tracking
    completed_at      = Column(DateTime(timezone=True), nullable=True)
    completed_late    = Column(Boolean, nullable=False, default=False)
    completed_late_at = Column(DateTime(timezone=True), nullable=True)

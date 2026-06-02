import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, Integer, Float, Date, Text, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.models.base import Base

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
    category    = Column(String(50), nullable=True)             # app_setup|policy|delivery_standards|delivery_types|scorecard|observation
    record_type = Column(String(20), nullable=False, default="coverage")  # coverage|demonstration


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
    current_day_number = Column(Integer, nullable=False)  # phase: 1–4 normal, 5 = quiz day, 6+ = remediation

    trainer_comments  = Column(Text, nullable=True)
    manager_comments  = Column(Text, nullable=True)

    # Phase gate tracking
    submitted_at    = Column(DateTime(timezone=True), nullable=True)
    phase_closed    = Column(Boolean, nullable=False, default=False)
    phase_closed_at = Column(DateTime(timezone=True), nullable=True)

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

import uuid
from sqlalchemy import Column, String, Boolean, ForeignKey, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.models.base import Base


class TrainerMark(Base):
    """
    Performance accountability record issued when a trainer fails to close
    a training phase by midnight with no inherited debt.

    Attribution rules (ADR-046 §3):
      - Only one mark is issued per incident, to the trainer active at end of day.
      - If the trainer had inherited debt tasks on their record, NO mark is issued —
        the failure is attributed to the original debt originator.
      - debt_originated = True means this mark started a new debt chain.
      - debt_chain_context documents the downstream impact for management context
        but does NOT create additional marks on subsequent trainers.

    reason values:
      "phase_not_closed" — mandatory tasks incomplete at midnight
      "submitted_late"   — record not submitted by midnight (management reopened)

    Underperforming trainer threshold: marks across 3+ distinct trainees triggers
    a management notification (checked in record_trainer_mark service).
    """
    __tablename__ = "trainer_marks"

    id                 = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trainer_id         = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    training_record_id = Column(UUID(as_uuid=True), ForeignKey("training_records.id", ondelete="CASCADE"), nullable=False)
    trainee_id         = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    reason             = Column(String(50), nullable=False)  # phase_not_closed | submitted_late
    debt_originated    = Column(Boolean, nullable=False, default=False)
    debt_chain_context = Column(Text, nullable=True)
    created_at         = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

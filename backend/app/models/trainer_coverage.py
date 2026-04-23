import uuid
from sqlalchemy import Column, String, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.models.base import Base


class TrainerCoverage(Base):
    """
    Topic-level audit log recording which trainer covered which curriculum topic.

    A row is written every time a trainer marks a TrainingTask as complete.
    This enables:
      - Mid-shift handoff tracing: if Trainer A leaves and Trainer B picks up,
        the log shows exactly who covered each topic and at what time.
      - Trainer accountability: end-of-day attribution for mark purposes goes
        to whoever covered the most recent topics, visible from this table.
      - Exemplary trainer identification: trainers who clear inherited debt and
        close their own phase are flagged via analysis of this log.

    curriculum_item_id is nullable (SET NULL on delete) to preserve coverage
    history even if the curriculum item is later removed or edited.
    """
    __tablename__ = "trainer_coverage"

    id                 = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    training_record_id = Column(UUID(as_uuid=True), ForeignKey("training_records.id", ondelete="CASCADE"), nullable=False, index=True)
    trainer_id         = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    curriculum_item_id = Column(UUID(as_uuid=True), ForeignKey("training_curriculums.id", ondelete="SET NULL"), nullable=True)
    topic_title        = Column(String(255), nullable=False)  # snapshot for historical integrity
    covered_at         = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

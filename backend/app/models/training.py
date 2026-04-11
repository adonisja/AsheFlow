import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, Integer, Date, Text, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.models.base import Base

class TrainingCurriculum(Base):
    """
    Template for the 5-day training cycle topics.
    """
    __tablename__ = "training_curriculums"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    day_number = Column(Integer, nullable=False, index=True) # Day 1, Day 2, etc.
    topic_title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    is_mandatory = Column(Boolean, nullable=False, default=True)


class TrainingRecord(Base):
    """
    Stateful log representing a trainee's specific day of training.
    """
    __tablename__ = "training_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trainee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    trainer_id = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True, index=True)
    
    record_date = Column(Date, nullable=False, index=True)
    current_day_number = Column(Integer, nullable=False) # E.g., Trainee is on Day 3
    
    trainer_comments = Column(Text, nullable=True)
    manager_comments = Column(Text, nullable=True) # Explicit manager commands/notes
    
    is_locked = Column(Boolean, nullable=False, default=False) # If true, immutable
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class TrainingTask(Base):
    """
    Actual tasks assigned to a specific TrainingRecord.
    Tracks check-offs and training debt.
    """
    __tablename__ = "training_tasks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    training_record_id = Column(UUID(as_uuid=True), ForeignKey("training_records.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Snapshot of the curriculum task, ensuring historical consistency
    topic_title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    
    is_completed = Column(Boolean, nullable=False, default=False)
    is_mandatory = Column(Boolean, nullable=False, default=True)
    is_training_debt = Column(Boolean, nullable=False, default=False) # True if rolled over from a previous day

    # Debt tracking: how many dispatch days this task has been carried over uncompleted.
    # Increments by 1 each time the task rolls into a new record as debt.
    # 0 means the task was introduced today (not debt), or debt_age on first rollover = 1.
    debt_age = Column(Integer, nullable=False, default=0)

    # Escalation flag: set automatically when debt_age reaches the DEBT_ESCALATION_THRESHOLD.
    # Surfaces this trainee in the manager escalation view for human intervention.
    is_escalated = Column(Boolean, nullable=False, default=False)

    # We can also track when it was completed
    completed_at = Column(DateTime(timezone=True), nullable=True)

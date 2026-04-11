import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.models.base import Base


class TrainerContinuationRequest(Base):
    """A trainee's request to continue training with the same trainer next dispatch.

    Lifecycle:
    - Created by the trainee (status = "pending").
    - Trainer sees it on their dashboard and can accept or reject.
    - Both accept and reject are silent to the trainee — no feedback is shown.
    - If accepted: on the trainee's next assigned dispatch day, training_injection
      checks for an active accepted request and, if the trainer is available,
      pairs them. If the trainer is unavailable the request is nullified and the
      trainee is paired normally.
    - If rejected: the request is nullified and training proceeds normally on
      the next dispatch day.
    - If neither accepted nor rejected by the time the trainee's next dispatch
      day arrives: training_injection automatically nullifies the request
      (expires it) before pairing.

    Constraints:
    - A trainee can only have one pending/accepted request at a time
      (UniqueConstraint on trainee_id + status in ('pending', 'accepted') is
      enforced at the application layer, not the DB, to keep the schema simple).

    Attributes:
        id: Primary key UUID.
        trainee_id: FK to the requesting trainee.
        trainer_id: FK to the requested trainer.
        status: One of 'pending', 'accepted', 'nullified'.
        created_at: When the request was submitted.
        resolved_at: When the request was accepted, rejected, or nullified.
    """
    __tablename__ = "trainer_continuation_requests"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trainee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    trainer_id = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    status     = Column(String(20), nullable=False, default="pending")  # pending | accepted | nullified

    # Trainer-set priority for conflict resolution when multiple accepted requests
    # from different trainees land on the same dispatch day.
    # Lower integer = higher priority. NULL = unranked (treated as lowest priority).
    # Visible only to the trainer who owns the requests. Cleared on nullification.
    priority   = Column(Integer, nullable=True)

    created_at  = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    resolved_at = Column(DateTime(timezone=True), nullable=True)

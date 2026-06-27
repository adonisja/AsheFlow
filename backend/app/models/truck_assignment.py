from sqlalchemy import Column, String, Boolean, Date, DateTime, ForeignKey, CheckConstraint, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from app.models.base import Base
import uuid


class TruckAssignment(Base):
    """ORM model for a daily truck assignment record.

    One record is created per truck per dispatch run.  All crew members
    for that truck on that day are stored as related ``AssignmentMember`` rows.

    Constraints & Safety:
    - ``truck_id`` and ``date`` combination MUST be unique (preventing double dispatch).
    - Cascading deletes are enforced; deleting the truck deletes its history.

    Attributes:
        id: Primary key UUID.
        truck_id: Foreign key to the assigned truck.
        date: The date this assignment is for.
        status: Lifecycle status — one of ``planned``, ``active``, or ``completed``.
    """
    __tablename__ = "truck_assignments"
    __table_args__ = (
        UniqueConstraint("truck_id", "date", name="uq_truck_assignment_date"),
        CheckConstraint("status IN ('planned', 'active', 'completed')", name="ck_truck_assignments_status"),
    )

    id                  = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id          = Column(UUID(as_uuid=True), nullable=False, index=True)
    truck_id            = Column(UUID(as_uuid=True), ForeignKey("trucks.id", ondelete="CASCADE"), nullable=False, index=True)
    date                = Column(Date,               nullable=False, index=True)
    status              = Column(String(50),         nullable=False, default="planned")
    sort_initiated_by       = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True, index=True)
    sort_committed_at       = Column(DateTime(timezone=True), nullable=True)
    paired_arrival_confirmed = Column(Boolean, nullable=False, default=False)

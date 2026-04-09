from sqlalchemy import Column, String, Date, ForeignKey, CheckConstraint, UniqueConstraint
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

    id       = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    truck_id = Column(UUID(as_uuid=True), ForeignKey("trucks.id", ondelete="CASCADE"), nullable=False, index=True)
    date     = Column(Date,               nullable=False, index=True)
    status   = Column(String(50),         nullable=False, default="planned")

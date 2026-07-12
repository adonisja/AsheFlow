from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, CheckConstraint, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from app.models.base import Base
import uuid


class AssignmentMember(Base):
    """ORM model for a single crew member on a truck assignment.

    Each row links one employee to one ``TruckAssignment`` with their role
    for that day.

    Constraints & Safety:
    - ``assignment_id`` and ``employee_id`` combination must be unique (an employee
      cannot be assigned to the same truck twice on the same day).
    - Cascading deletes are enforced; deleting an employee or an assignment deletes this row.

    Attributes:
        id: Primary key UUID.
        assignment_id: Foreign key to the parent ``TruckAssignment``.
        employee_id: Foreign key to the assigned employee.
        role: The employee's role for this assignment — one of ``driver``,
            ``trainer``, or ``walker``.
    """
    __tablename__ = "assignment_members"
    __table_args__ = (
        UniqueConstraint("assignment_id", "employee_id", name="uq_assignment_member"),
        CheckConstraint("role IN ('driver', 'trainer', 'trainee', 'walker')", name="ck_assignment_members_role"),
        CheckConstraint("status IN ('active', 'departed', 'transferred')", name="ck_assignment_members_status"),
    )

    id                = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id        = Column(UUID(as_uuid=True), nullable=False, index=True)
    assignment_id     = Column(UUID(as_uuid=True), ForeignKey("truck_assignments.id", ondelete="CASCADE"), nullable=False, index=True)
    employee_id       = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"),          nullable=False, index=True)
    role              = Column(String(50),         nullable=False)
    # Set only for role='trainee' rows — the specific trainer paired during dispatch.
    # Null for all other roles. Used by inject_curriculum, Discord DMs, and dashboards.
    paired_trainer_id = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True, index=True)
    # True when a dispatch coordinator placed this member manually after the algorithm ran.
    # False (default) = algorithm-placed. Used for fill-rate analytics.
    is_manual         = Column(Boolean,            nullable=False, default=False)
    # Stamped when the member confirms physical arrival at the anchor point
    # from their app (ADR-145 flow: trainee confirms → trainer is notified →
    # trainer runs the paired rebalance). Nullable = not yet confirmed.
    ap_arrived_at     = Column(DateTime(timezone=True), nullable=True)
    # Live crew membership lifecycle (ADR-197). 'active' = on this truck and
    # available; 'departed' = left for the day; 'transferred' = moved to another
    # truck (distinct for analytics; F5 treats both non-active as off-crew).
    # F5's live-crew count = members with status='active'. departed_at stamps the
    # transition. Route-execution state stays on Route/DeliveryStop — this is
    # membership only; availability is derived from both (ADR-197 Phase 0b).
    status            = Column(String(20), nullable=False, server_default="active")
    departed_at       = Column(DateTime(timezone=True), nullable=True)

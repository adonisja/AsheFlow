from sqlalchemy import (
    Column, String, Boolean, DateTime, Integer, ForeignKey, CheckConstraint,
    UniqueConstraint, Index, text,
)
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
        role: The employee's SLOT for this assignment — ``driver``, ``trainer``,
            ``trainee``, ``walker``, ``captain`` (ADR-256) or ``driver_trainee``
            (ADR-264). Distinct from ``Employee.role``, which is the job title:
            a captain-titled employee may be slotted as a walker for the day.
            At most one ``captain`` row per assignment (ADR-256 D2).
    """
    __tablename__ = "assignment_members"
    __table_args__ = (
        UniqueConstraint("assignment_id", "employee_id", name="uq_assignment_member"),
        # ADR-256 adds 'captain'; ADR-264 adds 'driver_trainee'. This is the SLOT
        # namespace (who fills what seat on this truck today), distinct from
        # Employee.role (job title) — a captain-titled employee may be slotted as
        # a walker for the day.
        CheckConstraint(
            "role IN ('driver', 'trainer', 'trainee', 'walker', 'captain', 'driver_trainee')",
            name="ck_assignment_members_role",
        ),
        CheckConstraint("status IN ('active', 'departed', 'transferred')", name="ck_assignment_members_status"),
        # ADR-256 D2: exactly one captain slot per truck. The partial unique index is
        # the guarantee — a service-level check alone loses to a concurrent double-assign
        # (both read "no captain", both insert, both succeed). Write sites catch
        # IntegrityError and raise 409.
        # Both dialects must be named explicitly. A `postgresql_where` alone is
        # SILENTLY DROPPED by SQLite (the test engine), degrading this into a plain
        # unique index on assignment_id — one crew member per truck, any role. That
        # is not a test artifact: it fails ordinary driver/trainer inserts, which is
        # how it was caught.
        Index(
            "uq_assignment_members_one_captain",
            "assignment_id",
            unique=True,
            postgresql_where=text("role = 'captain'"),
            sqlite_where=text("role = 'captain'"),
        ),
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
    # Per-employee-per-day trip count (ADR-199 D3). A "trip" = one route run
    # completed AND returned to the truck (incremented on back-at-truck). This is
    # the PERSON's run count for the day; distinct from Route.wave_number, which
    # is the TRUCK's redistribution cycle. Purely additive — starts at 0.
    trip_count        = Column(Integer, nullable=False, server_default="0", default=0)

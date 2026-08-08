from datetime import datetime, timezone

from sqlalchemy import (
    Column, Integer, Boolean, Date, DateTime, ForeignKey, CheckConstraint,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID

from app.models.base import Base
import uuid


class CaptainTruckFamiliarity(Base):
    """How many dispatched days a captain has held a given truck (ADR-256 D16).

    A new captain learns one truck at a time: they hold it for
    ``CompanyConfig.captain_truck_rotation_days`` days, then rotate to a truck they
    have not completed. Familiarisation ends when every ACTIVE truck has a completed
    row, after which the normal consecutive-day penalty resumes.

    **Visited set, not round-robin.** Round-robin ("next truck in order, done when
    back at the first") needs no storage but breaks the moment a truck is out of
    service or the captain is absent: a missed slot either stalls the cycle or skips
    a truck, and "back at the first" then no longer means "held them all". The
    failure is silent — a captain marked familiar who never ran truck 3. This table
    answers the question directly and survives absences, fleet changes and reorders.

    Counting rule: a day is credited at FINALIZE, not at assignment. A captain who
    is assigned and then calls out has not learned the truck.

    Attributes:
        days_held: Dispatched-and-finalised days on this truck.
        first_held_at: Company-local date of the first credited day.
        last_held_at: Company-local date of the most recent credited day. Also the
            idempotency key — a second finalize on the same date must not double-count.
        completed_at: Set when days_held first reaches the configured threshold.
            Null while in progress. Never cleared by a config change: lowering the
            threshold must not retroactively un-complete a truck.
        pinned: Manual override, per captain per truck. While true this truck is
            held regardless of the rotation threshold, until dispatch clears it.
    """
    __tablename__ = "captain_truck_familiarity"
    __table_args__ = (
        UniqueConstraint("employee_id", "truck_id", name="uq_captain_truck_familiarity"),
        CheckConstraint("days_held >= 0", name="ck_captain_familiarity_days_nonneg"),
    )

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id    = Column(UUID(as_uuid=True), nullable=False, index=True)
    employee_id   = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    truck_id      = Column(UUID(as_uuid=True), ForeignKey("trucks.id", ondelete="CASCADE"), nullable=False, index=True)

    days_held     = Column(Integer, nullable=False, default=0, server_default="0")
    first_held_at = Column(Date, nullable=True)
    last_held_at  = Column(Date, nullable=True)
    completed_at  = Column(Date, nullable=True)
    pinned        = Column(Boolean, nullable=False, default=False, server_default="false")

    created_at    = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

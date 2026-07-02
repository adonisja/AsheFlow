"""Station loading operations: tote transfers and load check-offs (ADR-174).

Both tables are scoped to a single load day. A transfer is a PHYSICAL move
instruction executed at the station before trucks depart: from_truck is where
the tote sits, to_truck is where current zone data wants it. AP Sort consumes
the finalized result and never mutates tote membership.
"""
import uuid

from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.models.base import Base


class ToteTransfer(Base):
    __tablename__ = "tote_transfers"

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id      = Column(UUID(as_uuid=True), nullable=False, index=True)
    transfer_date   = Column(Date, nullable=False, index=True)
    bag_id          = Column(String(100), nullable=False)
    from_truck_id   = Column(UUID(as_uuid=True), ForeignKey("trucks.id", ondelete="CASCADE"), nullable=False)
    to_truck_id     = Column(UUID(as_uuid=True), ForeignKey("trucks.id", ondelete="CASCADE"), nullable=False)
    package_count   = Column(Integer, nullable=True)
    # suggested → confirmed → completed; or kept (tote stays on from_truck and
    # zone data is realigned to the physical placement)
    status          = Column(String(20), nullable=False, default="suggested")
    reason          = Column(String(30), nullable=False)   # "rerun_diff" | "dispatch"
    created_at      = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    resolved_by     = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    resolved_by_name = Column(String(100), nullable=True)
    resolved_at     = Column(DateTime(timezone=True), nullable=True)
    completed_at    = Column(DateTime(timezone=True), nullable=True)


class ToteLoadCheck(Base):
    __tablename__ = "tote_load_checks"
    __table_args__ = (
        UniqueConstraint("company_id", "load_date", "bag_id", name="uq_tote_check_per_day"),
    )

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id      = Column(UUID(as_uuid=True), nullable=False, index=True)
    load_date       = Column(Date, nullable=False, index=True)
    truck_id        = Column(UUID(as_uuid=True), ForeignKey("trucks.id", ondelete="CASCADE"), nullable=False)
    bag_id          = Column(String(100), nullable=False)
    checked_by      = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    checked_by_name = Column(String(100), nullable=False)
    checked_at      = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

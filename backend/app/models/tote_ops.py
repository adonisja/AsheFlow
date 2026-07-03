"""Station loading operations: tote transfers and load check-offs (ADR-174).

Both tables are scoped to a single load day. A transfer is a PHYSICAL move
instruction executed at the station before trucks depart: from_truck is where
the tote sits, to_truck is where current zone data wants it. AP Sort consumes
the finalized result and never mutates tote membership.
"""
import uuid

from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
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


class PackageRemoval(Base):
    """Out-of-zone freight pulled from a truck at the station (ADR-176).

    One row per removal unit: a whole tote (tba is NULL, tba_numbers holds the
    list) or a single package inside an otherwise-good tote. flagged rows are
    created automatically at sort-persist time and superseded per re-run;
    removed rows are the permanent record of what was handed back to Amazon.
    """
    __tablename__ = "package_removals"

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id      = Column(UUID(as_uuid=True), nullable=False, index=True)
    removal_date    = Column(Date, nullable=False, index=True)
    bag_id          = Column(String(100), nullable=False)
    tba             = Column(String(50), nullable=True)     # NULL = whole tote
    tba_numbers     = Column(JSONB, nullable=True)          # tote rows: list[str]
    package_count   = Column(Integer, nullable=False, default=1)
    whole_tote      = Column(Boolean, nullable=False, default=False)
    reason          = Column(String(30), nullable=False, default="out_of_zone")
    locator         = Column(String(50), nullable=True)     # dock tag / OV zone
    status          = Column(String(20), nullable=False, default="flagged")  # flagged | removed
    flagged_at      = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    removed_by      = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    removed_by_name = Column(String(100), nullable=True)
    removed_at      = Column(DateTime(timezone=True), nullable=True)

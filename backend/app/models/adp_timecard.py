from sqlalchemy import Column, String, Date, DateTime, Boolean, Integer, UniqueConstraint, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.models.base import Base
import uuid


class ADPTimeCard(Base):
    __tablename__ = "adp_timecards"
    __table_args__ = (
        UniqueConstraint("employee_id", "work_date", name="uq_adp_timecards_employee_date"),      
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    adp_associate_oid = Column(String(100), nullable=False)
    work_date = Column(Date, nullable=False, index=True)
    is_working_day = Column(Boolean, nullable=False, default=True)
    raw_payload = Column(JSONB, nullable=True)
    fetched_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    


class ADPTimeCardSegment(Base):
    __tablename__ = "adp_timecard_segments"
    __table_args__ = (
        UniqueConstraint("timecard_id", "segment_index", name="uq_adp_timecard_segments_order"),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    timecard_id = Column(UUID(as_uuid=True), ForeignKey("adp_timecards.id", ondelete="CASCADE"), nullable=False, index=True)
    segment_index = Column(Integer, nullable=False)
    clock_in_at = Column(DateTime(timezone=True), nullable=False)
    clock_out_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

from sqlalchemy import Column, String, Date, DateTime, CheckConstraint, UniqueConstraint, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from app.models.base import Base
import uuid


class FlexTimesheet(Base):
    __tablename__ = "flex_timesheets"
    __table_args__ = (
        UniqueConstraint("employee_id", "work_date", name="uq_flex_timesheets_employee_date"),
        CheckConstraint("source IN ('manual_upload','api', 'bot')", name="ck_flex_timesheets_source")
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    work_date = Column(Date, nullable=False)
    clock_in_at = Column(DateTime(timezone=True))
    clock_out_at = Column(DateTime(timezone=True))
    break_start_at = Column(DateTime(timezone=True), nullable=False)
    break_end_at = Column(DateTime(timezone=True), nullable=False)
    source = Column(String(30), nullable=False, default="manual_upload")
    uploaded_by = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"))
    uploaded_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
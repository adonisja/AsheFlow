from sqlalchemy import Column, String, Date, DateTime, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from app.models.base import Base
import uuid


class ADPPayPeriod(Base):
    __tablename__ = "adp_pay_periods"
    __table_args__ = (
        UniqueConstraint("company_id", "period_start", name="uq_pay_period_company"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    adp_pay_period_id = Column(String(100), nullable=False)
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    close_deadline = Column(DateTime(timezone=True), nullable=False)
    pay_date = Column(Date, nullable=False)
    fetched_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
import uuid
from sqlalchemy import Column, String, Boolean, Date, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from app.models.base import Base


class TruckZone(Base):
    __tablename__ = "truck_zones"

    id             = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id     = Column(UUID(as_uuid=True), nullable=False, index=True)
    truck_id       = Column(UUID(as_uuid=True), ForeignKey("trucks.id", ondelete="CASCADE"), nullable=False, index=True)
    truck_polygon  = Column(JSONB, nullable=False)
    zone_label     = Column(String(50), nullable=False)
    zone_date      = Column(Date, nullable=False, index=True)
    is_active      = Column(Boolean, nullable=False, default=True)
    created_by     = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True, index=True)
    created_by_name = Column(String(100), nullable=False)
    created_at     = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

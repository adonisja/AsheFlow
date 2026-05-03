import uuid
from sqlalchemy import Column, String, Date, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.models.base import Base


ARRIVAL_TYPES = ["loading", "return"]


class StationArrival(Base):
    """Records when a driver arrives at the station.

    Two visits per shift:
      - "loading": driver arrives to load packages before departing for their route
      - "return": driver arrives back at the station with RTS packages after the route

    The departure record (field_ops.Departure) captures when the driver *leaves*
    the station; this model captures when they *arrive*.
    """
    __tablename__ = "station_arrivals"
    __table_args__ = (
        UniqueConstraint("driver_id", "date", "arrival_type", name="uq_station_arrivals_driver_date_type"),
    )

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    driver_id    = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    date         = Column(Date, nullable=False, index=True)
    arrival_type = Column(String(20), nullable=False)  # "loading" | "return"
    arrived_at   = Column(DateTime(timezone=True), server_default=func.now())

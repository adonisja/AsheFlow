import uuid
from sqlalchemy import Column, String, Date, DateTime, Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.sql import func
from app.models.base import Base


ARRIVAL_TYPES = ["loading", "return"]

# Items that should be staged and ready when the driver arrives at the station.
STAGING_ITEMS = ["totes", "ov_packages", "phones_rabbits", "chargers"]


class StationArrival(Base):
    """Records when a driver arrives at the station.

    Two visits per shift:
      - "loading": driver arrives to load packages before departing for their route
      - "return": driver arrives back at the station with RTS packages after the route

    The departure record (field_ops.Departure) captures when the driver *leaves*
    the station; this model captures when they *arrive*.

    For "loading" arrivals, was_staged and missing_items track whether dispatch
    had the area properly staged — used for efficiency/process metrics.
    """
    __tablename__ = "station_arrivals"
    __table_args__ = (
        UniqueConstraint("driver_id", "date", "arrival_type", name="uq_station_arrivals_driver_date_type"),
    )

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    driver_id     = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    date          = Column(Date, nullable=False, index=True)
    arrival_type  = Column(String(20), nullable=False)  # "loading" | "return"
    arrived_at    = Column(DateTime(timezone=True), server_default=func.now())
    # Staging check — populated only for "loading" arrivals
    was_staged    = Column(Boolean, nullable=True)
    missing_items = Column(ARRAY(String), nullable=True)  # subset of STAGING_ITEMS

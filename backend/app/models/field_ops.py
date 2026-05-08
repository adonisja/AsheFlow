import uuid
from sqlalchemy import Column, String, Float, Integer, Boolean, Date, DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from app.models.base import Base


class CheckIn(Base):
    __tablename__ = "check_ins"
    __table_args__ = (
        UniqueConstraint("employee_id", "date", name="uq_check_ins_employee_date"),
    )

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    date        = Column(Date, nullable=False, index=True)
    photo_url   = Column(Text, nullable=True)   # stored as base64 data-URI or future S3 URL
    checked_in_at = Column(DateTime(timezone=True), server_default=func.now())


class Departure(Base):
    __tablename__ = "departures"
    __table_args__ = (
        UniqueConstraint("employee_id", "date", name="uq_departures_employee_date"),
    )

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id    = Column(UUID(as_uuid=True), nullable=False, index=True)
    employee_id   = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    date          = Column(Date, nullable=False, index=True)
    itinerary_photo_url = Column(Text, nullable=True)
    departed_at   = Column(DateTime(timezone=True), server_default=func.now())
    returned_at   = Column(DateTime(timezone=True), nullable=True)   # stamped on return; enables shift duration tracking


class WalkerRating(Base):
    __tablename__ = "walker_ratings"
    __table_args__ = (
        UniqueConstraint("driver_id", "walker_id", "date", name="uq_walker_ratings_driver_walker_date"),
    )

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id  = Column(UUID(as_uuid=True), nullable=False, index=True)
    driver_id   = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    walker_id   = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    date        = Column(Date, nullable=False, index=True)
    present     = Column(Boolean, nullable=False, default=True)  # False = no-show; stars will be null
    stars       = Column(Integer, nullable=True)   # nullable to support no-show records
    comment     = Column(Text, nullable=True)
    rated_at    = Column(DateTime(timezone=True), server_default=func.now())


# Standard checklist item names
INSPECTION_ITEMS = [
    "tires",
    "lights",
    "mirrors",
    "brakes",
    "fluids",
    "horn",
    "wipers",
    "seatbelts",
    "cargo_security",
    "fuel_level",
]


class FuelMileageLog(Base):
    """Driver fuel and mileage log — one record per driver per day.

    odometer_start submitted at departure; odometer_end and fuel_added patched at return.
    """
    __tablename__ = "fuel_mileage_logs"
    __table_args__ = (
        UniqueConstraint("driver_id", "date", name="uq_fuel_mileage_logs_driver_date"),
    )

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    driver_id       = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    truck_id        = Column(UUID(as_uuid=True), ForeignKey("trucks.id", ondelete="SET NULL"), nullable=True, index=True)
    date            = Column(Date, nullable=False, index=True)
    odometer_start  = Column(Float, nullable=False)             # miles at start of shift
    odometer_end    = Column(Float, nullable=True)              # patched at return
    fuel_added      = Column(Float, nullable=True)              # gallons, patched at return
    notes           = Column(Text, nullable=True)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())


INSPECTION_TYPES = ["pre_trip", "eod"]


class VehicleInspection(Base):
    """Vehicle inspection checklist — one pre_trip and one eod record allowed per driver per date."""
    __tablename__ = "vehicle_inspections"
    __table_args__ = (
        UniqueConstraint("driver_id", "date", "inspection_type", name="uq_vehicle_inspections_driver_date_type"),
    )

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    driver_id       = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    truck_id        = Column(UUID(as_uuid=True), ForeignKey("trucks.id", ondelete="SET NULL"), nullable=True, index=True)
    date            = Column(Date, nullable=False, index=True)
    inspection_type = Column(String(20), nullable=False, default="pre_trip")  # "pre_trip" | "eod"
    # items: {item_name: True (pass) | False (fail)}
    items           = Column(JSONB, nullable=False, default=dict)
    has_failures    = Column(Boolean, nullable=False, default=False)
    notes           = Column(Text, nullable=True)
    submitted_at    = Column(DateTime(timezone=True), server_default=func.now())

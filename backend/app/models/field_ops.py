import uuid
from sqlalchemy import Column, String, Integer, Boolean, Date, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from app.models.base import Base


class CheckIn(Base):
    __tablename__ = "check_ins"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_id = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    date        = Column(Date, nullable=False, index=True)
    photo_url   = Column(Text, nullable=True)   # stored as base64 data-URI or future S3 URL
    checked_in_at = Column(DateTime(timezone=True), server_default=func.now())


class Departure(Base):
    __tablename__ = "departures"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_id   = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    date          = Column(Date, nullable=False, index=True)
    itinerary_photo_url = Column(Text, nullable=True)
    departed_at   = Column(DateTime(timezone=True), server_default=func.now())
    returned_at   = Column(DateTime(timezone=True), nullable=True)   # stamped on return; enables shift duration tracking


class WalkerRating(Base):
    __tablename__ = "walker_ratings"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    driver_id   = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    walker_id   = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    date        = Column(Date, nullable=False, index=True)
    present     = Column(Boolean, nullable=False, default=True)  # False = no-show; stars will be null
    stars       = Column(Integer, nullable=True)   # nullable to support no-show records
    comment     = Column(Text, nullable=True)
    rated_at    = Column(DateTime(timezone=True), server_default=func.now())


# Standard checklist item names
INSPECTION_ITEMS = [
    "tyres",
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

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    driver_id       = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    truck_id        = Column(UUID(as_uuid=True), ForeignKey("trucks.id", ondelete="SET NULL"), nullable=True, index=True)
    date            = Column(Date, nullable=False, index=True)
    odometer_start  = Column(Integer, nullable=False)           # km / miles at start of shift
    odometer_end    = Column(Integer, nullable=True)            # patched at return
    fuel_added      = Column(Integer, nullable=True)            # litres or gallons, patched at return
    notes           = Column(Text, nullable=True)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())


class VehicleInspection(Base):
    """Pre-trip vehicle inspection checklist completed by the driver each morning."""
    __tablename__ = "vehicle_inspections"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    driver_id    = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    truck_id     = Column(UUID(as_uuid=True), ForeignKey("trucks.id", ondelete="SET NULL"), nullable=True, index=True)
    date         = Column(Date, nullable=False, index=True)
    # items: {item_name: True (pass) | False (fail)}
    items        = Column(JSONB, nullable=False, default=dict)
    has_failures = Column(Boolean, nullable=False, default=False)
    notes        = Column(Text, nullable=True)
    submitted_at = Column(DateTime(timezone=True), server_default=func.now())

"""Anchor point model.

A driver sets an AP (parking/staging location) before leaving the station.
Multiple APs can exist per truck per day — a preliminary before departure,
an arrival confirmation on reaching the spot, and relocations if the driver
moves to a different area mid-day.

Status lifecycle:
    preliminary  — submitted before or just after departure, ETA included
    arrived      — driver tapped "Arrived" at the location
    relocated    — superseded by a later AP for the same day

is_initial=True marks the first AP of the day (preliminary). Only this record
feeds next-day driver suggestions via GET /anchor-points/truck/{id}.
"""

import uuid
from sqlalchemy import Column, String, Date, DateTime, ForeignKey, Text, Boolean, Integer, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.models.base import Base

AP_STATUSES = ["preliminary", "arrived", "relocated"]


class AnchorPoint(Base):
    __tablename__ = "anchor_points"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    truck_id     = Column(UUID(as_uuid=True), ForeignKey("trucks.id",     ondelete="CASCADE"),    nullable=False, index=True)
    driver_id    = Column(UUID(as_uuid=True), ForeignKey("employees.id",  ondelete="CASCADE"),    nullable=False, index=True)
    date         = Column(Date,               nullable=False, index=True)
    sequence     = Column(Integer,            nullable=False, default=1)   # 1 = first AP of the day
    is_initial   = Column(Boolean,            nullable=False, default=False)  # True only for sequence=1
    status       = Column(String(20),         nullable=False, default="preliminary")
    location     = Column(String(255),        nullable=False)
    eta          = Column(String(20),         nullable=True)
    notes        = Column(Text,               nullable=True)
    submitted_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    arrived_at   = Column(DateTime(timezone=True), nullable=True)
    confirmed_by = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    confirmed_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(f"status IN ('preliminary','arrived','relocated')", name="ck_anchor_points_status"),
    )

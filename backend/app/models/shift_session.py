import uuid
from sqlalchemy import Column, Integer, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.models.base import Base


class ShiftSession(Base):
    """Tracks a driver's current position in the 5-gate shift lifecycle.

    One active session per driver at a time (enforced by partial unique index
    on driver_id WHERE completed_at IS NULL). Completed sessions are retained
    as a lightweight audit trail — no data beyond timestamps is stored here;
    the actual records (inspections, departures, etc.) live in their own tables.

    Gates:
      1 — Pre-shift  (check-in, pre-trip, start odometer, dock assignment)
      2 — Station loading  (staging check, manifest ack, departure)
      3 — Route  (anchor point, check-ins, walker ratings, RTS request)
      4 — Return  (station arrival return, station handoff)
      5 — EOD  (end odometer, EOD inspection, sign-out)
    """
    __tablename__ = "shift_sessions"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id   = Column(UUID(as_uuid=True), nullable=False, index=True)
    driver_id    = Column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    current_gate = Column(Integer, nullable=False, default=1)
    started_at   = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    gate_1_completed_at = Column(DateTime(timezone=True), nullable=True)
    gate_2_completed_at = Column(DateTime(timezone=True), nullable=True)
    gate_3_completed_at = Column(DateTime(timezone=True), nullable=True)
    gate_4_completed_at = Column(DateTime(timezone=True), nullable=True)

    completed_at = Column(DateTime(timezone=True), nullable=True)

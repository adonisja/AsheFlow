"""A standing crew that rides together (ADR-357).

Preferences top out at 88% for a SINGLE candidate (ADR-356); five people each
winning their own weighted draw is roughly 0.5%. "Always" is a different kind of
statement from "usually", so a pin is a CONSTRAINT applied before the draw rather
than another weight inside it.

The driver is the anchor: dispatch places drivers first, so by the time any other
role is assigned the driver's truck is known and the members can simply be seated
on it.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models.base import Base


class CrewPin(Base):
    """A named crew held together across dispatch runs.

    Standing, not per-day: "these people work well together" is a durable fact,
    and re-entering it every morning is the kind of chore that stops being done.

    Attributes:
        driver_id: The anchor. Members are seated on whichever truck this driver
            is assigned. When the driver is not dispatched the pin is inactive
            for the day (ADR-357 D2) — members dispatch normally and a warning is
            raised, rather than the system picking a substitute anchor.
        is_active: Cleared when a member is removed, or automatically when one
            pinned member bans another (D4). Set false rather than deleting the
            row: the roster is worth keeping if the conflict is resolved.
        inactive_reason: Why it was nullified, so a dispatcher does not have to
            guess.
    """

    __tablename__ = "crew_pins"
    __table_args__ = (
        # One pin per driver. Two active pins on one driver cannot both be
        # honoured and choosing between them would be arbitrary (D6).
        UniqueConstraint("company_id", "driver_id", name="uq_crew_pin_driver"),
        Index("ix_crew_pins_company_active", "company_id", "is_active"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    name = Column(String(80), nullable=False)
    driver_id = Column(
        UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )

    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    inactive_reason = Column(Text, nullable=True)

    created_by = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    members = relationship(
        "CrewPinMember",
        back_populates="pin",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class CrewPinMember(Base):
    """One employee held to a pin's driver.

    The driver is NOT stored here — they are the anchor, on the pin itself. A
    driver row would invite seating the anchor onto their own truck twice.
    """

    __tablename__ = "crew_pin_members"
    __table_args__ = (
        UniqueConstraint("pin_id", "employee_id", name="uq_crew_pin_member"),
        # An employee in two active pins is the same unresolvable conflict as two
        # pins on one driver, one layer down. Enforced in the service rather than
        # here: the constraint spans a join to crew_pins.is_active.
        Index("ix_crew_pin_members_employee", "employee_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    pin_id = Column(
        UUID(as_uuid=True), ForeignKey("crew_pins.id", ondelete="CASCADE"), nullable=False
    )
    employee_id = Column(
        UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )

    pin = relationship("CrewPin", back_populates="members")

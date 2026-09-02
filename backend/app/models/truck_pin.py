"""A person held to a specific truck on named weekdays (ADR-358).

The other pin axis. A CrewPin (ADR-357) binds people to a DRIVER and follows
wherever that driver is drawn; a TruckPin binds a person to a TRUCK, on the days
they actually work it — "Marcus is on Truck 4 on Tuesdays and Thursdays".

A person may hold one axis or the other, never both (ADR-358 D2): "follow this
driver" and "be on this truck" cannot both hold once the driver is drawn
elsewhere, and resolving that at dispatch time would silently produce different
crews on different days for reasons nobody could see.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID

from app.models.base import Base

WEEKDAYS = (
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
)


class TruckPin(Base):
    """One employee, one truck, one weekday.

    Tuesday-on-4 and Thursday-on-7 are two rows, and neither implies the other —
    a person's week is rarely uniform, and a single row with a day list would
    make "which truck on Thursday" a parse rather than a lookup.
    """

    __tablename__ = "truck_pins"
    __table_args__ = (
        # One truck per person per day. A second row for the same weekday is a
        # contradiction, not an additional preference.
        UniqueConstraint("employee_id", "day_of_week", name="uq_truck_pin_employee_day"),
        CheckConstraint(
            "day_of_week IN ('Monday', 'Tuesday', 'Wednesday', 'Thursday', "
            "'Friday', 'Saturday', 'Sunday')",
            name="ck_truck_pins_day_of_week",
        ),
        Index("ix_truck_pins_company_day", "company_id", "day_of_week"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    employee_id = Column(
        UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    truck_id = Column(
        UUID(as_uuid=True), ForeignKey("trucks.id", ondelete="CASCADE"), nullable=False
    )

    # Capitalised English name, matching EmployeeOffDay and what
    # target_date.strftime("%A") produces. Normalised on write so readers can
    # compare with == : available_pool mixes .ilike() and == against its own
    # day_of_week column and its comment flags the hazard. This table does not
    # inherit that ambiguity.
    day_of_week = Column(String(10), nullable=False, index=True)

    created_by = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )

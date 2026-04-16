from sqlalchemy import Column, String, Boolean, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID
from app.models.base import Base
import uuid

VALID_ROLES = ("driver", "walker", "trainer", "trainee", "dispatch", "management", "admin")


class Employee(Base):
    """ORM model for an employee.

    Attributes:
        id: Primary key UUID.
        name: Full display name.
        discord_id: Unique Discord user ID used for notifications.
        role: Job role — one of ``driver``, ``trainer``, or ``walker``.
        is_active: Whether the employee is currently active and eligible for dispatch.
    """
    __tablename__ = "employees"
    __table_args__ = (
        CheckConstraint(
            f"role IN {VALID_ROLES}",
            name="ck_employees_role_valid",
        ),
    )

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name         = Column(String(255),        nullable=False)
    email        = Column(String(255),        nullable=True,  unique=True, index=True)
    discord_id   = Column(String(100),        nullable=False, unique=True, index=True)
    cognito_sub  = Column(String(255),        nullable=True,  unique=True, index=True)
    role         = Column(String(50),         nullable=False, index=True)
    is_active    = Column(Boolean,            nullable=False, default=True, index=True)
    phone_number = Column(String(20),         nullable=True)

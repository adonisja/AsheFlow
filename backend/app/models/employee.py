from sqlalchemy import Column, String, Boolean, CheckConstraint, DateTime, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from app.models.base import Base
import uuid
from datetime import datetime, timezone

VALID_ROLES = ("driver", "walker", "trainer", "trainee", "dispatch", "management", "admin")
VALID_ACCOUNT_STATUSES = ("pending_verification", "active", "deactivated")


class Employee(Base):
    """ORM model for an employee.

    Attributes:
        id: Primary key UUID.
        name: Full display name.
        discord_id: Unique Discord user ID used for notifications.
        role: Job role — one of ``driver``, ``trainer``, or ``walker``.
        is_active: Whether the employee is currently active and eligible for dispatch.
        account_status: Lifecycle state — pending_verification (invited, not yet logged in),
            active (logged in at least once), or deactivated (manually disabled).
        invited_at: Timestamp when the invite was issued. Used by the Celery cleanup job
            to expire unverified accounts after INVITE_EXPIRY_DAYS days.

    Uniqueness:
        discord_id and email are unique per company, not globally. This allows
        the same person to exist across two companies' Discord servers or use the
        same email at two different DSPs.
    """
    __tablename__ = "employees"
    __table_args__ = (
        CheckConstraint(
            f"role IN {VALID_ROLES}",
            name="ck_employees_role_valid",
        ),
        CheckConstraint(
            "account_status IN ('pending_verification', 'active', 'deactivated')",
            name="ck_employees_account_status_valid",
        ),
        # Partial unique index — only enforced when discord_id is not null,
        # allowing multiple pending employees without a Discord ID yet.
        UniqueConstraint("company_id", "email", name="uq_employees_company_email"),
    )

    id                   = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id           = Column(UUID(as_uuid=True), nullable=False, index=True)
    name                 = Column(String(255),        nullable=False)
    username             = Column(String(100),        nullable=True,  unique=True, index=True)
    email                = Column(String(255),        nullable=True,  index=True)
    discord_id           = Column(String(100),        nullable=True,  index=True)
    cognito_sub          = Column(String(255),        nullable=True,  unique=True, index=True)
    role                 = Column(String(50),         nullable=False, index=True)
    is_active            = Column(Boolean,            nullable=False, default=False, index=True)
    phone_number         = Column(String(20),         nullable=True)
    account_status       = Column(String(30),         nullable=False, default="pending_verification", index=True)
    invited_at           = Column(DateTime(timezone=True), nullable=True)
    reset_on_graduation  = Column(Boolean,            nullable=False, default=False)

from sqlalchemy import Column, String, Boolean, CheckConstraint, DateTime, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from app.models.base import Base
import uuid
from datetime import datetime, timezone

# ADR-256: captain (route lead, one per truck) and field_supervisor (road-facing
# oversight, parallel to dispatch). ADR-264: driver_trainee — the enum value only;
# its training behaviour is ADR-264's to build.
# Mirrored in app/schemas/employee.py — the two copies must stay in sync.
VALID_ROLES = (
    "driver", "walker", "trainer", "trainee", "dispatch", "management", "admin",
    "captain", "field_supervisor", "driver_trainee",
)
VALID_ACCOUNT_STATUSES = ("pending_verification", "active", "deactivated")


class Employee(Base):
    """ORM model for an employee.

    Attributes:
        id: Primary key UUID.
        name: Full display name.
        discord_id: Unique Discord user ID used for notifications.
        role: Job role — one of ``VALID_ROLES``.
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
    # ADR-221: stamped on deactivation. The tombstone survives so the 6-month
    # name-redaction clock has a departure time to measure against.
    deactivated_at       = Column(DateTime(timezone=True), nullable=True)
    reset_on_graduation  = Column(Boolean,            nullable=False, default=False)

    # ── External HR system IDs ────────────────────────────────────────────────
    # Each HR platform gets its own column: hr_system_id_<source>.
    # This allows one employee to exist in multiple systems simultaneously.
    # hr_system_id_adp: ADP associateOID. Backfilled with a generated UUID for
    # pre-ADP employees; replaced with the real ADP ID on CSV import.
    # hr_system_id_adp_verified: flips to true on first successful GET /hr/v2/workers
    # round-trip confirming the stored ID resolves to a live ADP worker record.
    # Timecard sync only runs for employees where this flag is true.
    hr_system_id_adp          = Column(UUID(as_uuid=True), nullable=False, default=uuid.uuid4)
    hr_system_id_adp_verified = Column(Boolean, nullable=False, default=False)
    # hr_system_work_assignment_id_adp: ADP's Position Fulfillment Identifier (PFID),
    # from workAssignments[].itemID on GET /hr/v2/workers. Required in the
    # eventContext of every timeEntries.modify write — a correction cannot be
    # submitted without it. Nullable: populated by adp_sync, absent until the
    # employee's first roster sync (ADR-233).
    hr_system_work_assignment_id_adp = Column(String(64), nullable=True)

    # ── Modified duty / injury status ─────────────────────────────────────────
    # null = no restriction; "injured" = temporary light duty; "disabled" = permanent light duty.
    # Both non-null values hard-block assignment to heavy routes (ADR-139).
    injury_status       = Column(String(20), nullable=True)
    injury_status_since = Column(DateTime(timezone=True), nullable=True)

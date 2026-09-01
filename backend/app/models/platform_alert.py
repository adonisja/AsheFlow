import uuid
from sqlalchemy import (
    Column, String, Text, Boolean, DateTime, Integer, Index, func,
)
from sqlalchemy.dialects.postgresql import UUID
from app.models.base import Base


class PlatformAlert(Base):
    """An infrastructure condition only a super admin can fix (ADR-335).

    ADR-323 alerted company admins when Discord went down. ADR-324 D2 found that
    audience incomplete: a company admin cannot rotate a Discord bot token — it
    is platform infrastructure, one bot serving every tenant, credentials in SSM.
    Only a super admin can act.

    A Notification cannot reach them. `Notification.employee_id` is
    nullable=False with an FK to employees, and a super admin has no Employee row
    by design (`get_super_admin`, deps.py:247). Hence a separate table rather
    than a nullable column on Notification, which would have made every existing
    notification read learn to exclude platform rows.
    """
    __tablename__ = "platform_alerts"
    __table_args__ = (
        # The dedup key (ADR-335 D2): one OPEN alert per type per tenant.
        # Partial, so resolved rows do not block a genuine recurrence. Not a
        # unique constraint because Postgres treats NULL company_id values as
        # distinct, which would let platform-wide alerts pile up.
        Index(
            "ix_platform_alerts_open",
            "alert_type", "company_id",
            unique=False,
            postgresql_where=(Column("is_resolved") == False),  # noqa: E712
        ),
    )

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    alert_type = Column(String(64), nullable=False, index=True)

    # NULLABLE BY DESIGN — mirrors audit_log.company_id (ADR-274 D14). A Discord
    # outage is one incident across every tenant; a per-tenant fault names its
    # tenant. This is the one place a null company_id is correct rather than a
    # Dimension 1 defect.
    company_id = Column(UUID(as_uuid=True), nullable=True, index=True)

    message  = Column(Text, nullable=False)
    severity = Column(String(20), nullable=False, default="warning")

    # A platform alert is a CONDITION, not an inbox item (ADR-335 D2). It closes
    # when the integration answers again, not when someone reads it.
    is_resolved = Column(Boolean, nullable=False, default=False, index=True)

    # "first seen 09:12, 47 occurrences, still failing" is a different
    # operational picture from "an alert exists", and they look identical
    # without these.
    occurrence_count = Column(Integer, nullable=False, default=1)
    first_seen_at    = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_seen_at     = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    resolved_at = Column(DateTime(timezone=True), nullable=True)

    # NOT a ForeignKey. ADR-274 D13: writing a super admin's Cognito sub into an
    # employees FK raises ForeignKeyViolation and 500s the endpoint — the first
    # implementation of the company audits did exactly that, and staging caught
    # it. Text, the same shape super_admin_identity() produces for audit
    # payloads. Null when the alert resolved ITSELF (D3).
    resolved_by_sub   = Column(String(128), nullable=True)
    resolved_by_email = Column(String(320), nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

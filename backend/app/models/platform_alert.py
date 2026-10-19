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
        # The dedup key (ADR-335 D2): one OPEN alert per type per tenant --
        # and, since ADR-543 D2, per SUBJECT account, so two unprotected admins
        # in one company are two alerts, not one alert with a merged count.
        # Partial, so resolved rows do not block a genuine recurrence. Not a
        # unique constraint because Postgres treats NULL company_id values as
        # distinct, which would let platform-wide alerts pile up.
        Index(
            "ix_platform_alerts_open",
            "alert_type", "company_id", "subject_ref",
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

    # ADR-543 D2 — WHO an account alert is about. NULL for infrastructure
    # alerts (Discord, SES, backups), which are about no account.
    #   subject_kind  'employee' | 'platform' (platform staff have no Employee row)
    #   subject_ref   the Cognito username: the account's handle, not a name.
    #                 Returned to super admins only (ADR-343 D4: platform
    #                 support must not see personal identifiers).
    #   subject_role  the role or platform group, which support MAY see.
    subject_kind = Column(String(16), nullable=True)
    subject_ref  = Column(String(128), nullable=True)
    subject_role = Column(String(32), nullable=True)

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

import uuid

from sqlalchemy import CheckConstraint, Column, DateTime, Index, String, func, text
from sqlalchemy.dialects.postgresql import UUID

from app.models.base import Base

ACCOUNT_KINDS = ("employee", "surveyor", "staff")
REQUESTER_KINDS = ("tenant_admin", "super_admin")
STATUSES = ("pending", "applied", "cancelled", "expired")


class EmailChangeRequest(Base):
    """An admin-started email change waiting for the NEW inbox to confirm it (ADR-563 D3).

    For someone who lost access to their old address. Nothing about the
    account changes until the link sent to the new address is used, so a typo
    costs nothing. Platform accounts have no Employee row, which is why this
    is its own table rather than Employee.pending_email (ADR-451).

    The token is stored only as a SHA-256 hash; the link carries the raw value.
    """
    __tablename__ = "email_change_requests"
    __table_args__ = (
        CheckConstraint(f"account_kind IN {ACCOUNT_KINDS}", name="ck_email_change_kind"),
        CheckConstraint(f"requested_by_kind IN {REQUESTER_KINDS}", name="ck_email_change_requester"),
        CheckConstraint(f"status IN {STATUSES}", name="ck_email_change_status"),
        # One pending change per account; starting another replaces it.
        Index("uq_email_change_pending", "cognito_sub", unique=True,
              postgresql_where=text("status = 'pending'"),
              sqlite_where=text("status = 'pending'")),
    )

    id                = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cognito_sub       = Column(String(64), nullable=False, index=True)
    cognito_username  = Column(String(128), nullable=False)
    account_kind      = Column(String(16), nullable=False)
    company_id        = Column(UUID(as_uuid=True), nullable=True, index=True)   # employee only
    new_email         = Column(String(320), nullable=False)
    token_hash        = Column(String(64), nullable=False, unique=True)
    status            = Column(String(16), nullable=False, default="pending", server_default="pending")
    requested_by_kind = Column(String(16), nullable=False)
    requested_by_ref  = Column(String(64), nullable=False)
    created_at        = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    expires_at        = Column(DateTime(timezone=True), nullable=False)
    closed_at         = Column(DateTime(timezone=True), nullable=True)

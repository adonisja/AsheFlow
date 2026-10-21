import uuid

from sqlalchemy import CheckConstraint, Column, DateTime, Index, String, func, text
from sqlalchemy.dialects.postgresql import UUID

from app.models.base import Base

ACCOUNT_KINDS = ("employee", "surveyor", "staff")
STATUSES = ("pending", "resolved")


class MfaResetRequest(Base):
    """A locked-out person asking for their two-factor to be reset (ADR-551).

    Created only after the requester proved control of the account's verified
    inbox (an emailed code). It never changes the account itself: it puts a
    flag beside the reset button of whoever can act -- the company's admins,
    platform support, or a super admin -- and the reset closes it (D4).
    """
    __tablename__ = "mfa_reset_requests"
    __table_args__ = (
        CheckConstraint(f"account_kind IN {ACCOUNT_KINDS}", name="ck_mfa_reset_request_kind"),
        CheckConstraint(f"status IN {STATUSES}", name="ck_mfa_reset_request_status"),
        # D2: one pending request per account; asking again is not a second row.
        Index("uq_mfa_reset_request_pending", "cognito_sub", unique=True,
              postgresql_where=text("status = 'pending'"),
              sqlite_where=text("status = 'pending'")),
    )

    id               = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cognito_sub      = Column(String(64), nullable=False, index=True)
    account_kind     = Column(String(16), nullable=False)
    company_id       = Column(UUID(as_uuid=True), nullable=True, index=True)   # employee only
    contributor_id   = Column(UUID(as_uuid=True), nullable=True)               # surveyor only
    request_ip       = Column(String(64), nullable=True)                       # ADR-435 D11 attribution
    status           = Column(String(16), nullable=False, default="pending", server_default="pending")
    requested_at     = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    resolved_at      = Column(DateTime(timezone=True), nullable=True)
    resolved_by_kind = Column(String(32), nullable=True)
    resolved_by_ref  = Column(String(64), nullable=True)

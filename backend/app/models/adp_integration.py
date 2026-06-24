from sqlalchemy import Column, String, Boolean, DateTime, CheckConstraint, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from app.models.base import Base
import uuid


class ADPIntegration(Base):
    """ADP RUN connection configuration for a company.

    One row per company. Stores the OAuth client ID and Secrets Manager ARNs
    for the client secret and mTLS certificate — no sensitive material is held
    in this table directly.

    last_employee_sync_at and last_timecard_sync_at are cursors for the Celery
    tasks, not audit records. NULL means the sync has never run. The tasks use
    these to determine their lookback window and handle the first-run case
    explicitly.

    Constraints:
    - One row per company (uq_adp_integrations_company).
    - adp_environment must be 'sandbox' or 'production'.
    """
    __tablename__ = "adp_integrations"
    __table_args__ = (
        UniqueConstraint("company_id", name="uq_adp_integrations_company"),
        CheckConstraint(
            "adp_environment IN ('sandbox', 'production')",
            name="ck_adp_integrations_environment",
        ),
    )

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    # OAuth client ID — not sensitive, stored as plain text.
    adp_client_id = Column(String(200), nullable=False)

    # ARNs pointing to AWS Secrets Manager — the actual secrets never touch this table.
    adp_client_secret_arn = Column(String(2048), nullable=False)
    adp_certificate_arn   = Column(String(2048), nullable=False)

    # 'sandbox' during development/staging; 'production' for live payroll data.
    adp_environment = Column(String(20), nullable=False, default="sandbox")

    # Cursors for Celery tasks. NULL = never synced (first-run case).
    last_employee_sync_at  = Column(DateTime(timezone=True), nullable=True)
    last_timecard_sync_at  = Column(DateTime(timezone=True), nullable=True)
    last_pay_period_sync_at = Column(DateTime(timezone=True), nullable=True)

    # Set to False to pause all ADP sync without deleting the config.
    is_enabled = Column(Boolean, nullable=False, default=False)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

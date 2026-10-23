"""ADR-578: feedback from a platform account (no tenant) can be stored.

feedbacks.company_id was made NOT NULL by h2b3c4d5e6f7, but create_feedback
writes NULL for a caller with no Employee row (super_admin, platform_support)
and routes the signal to a platform alert (ADR-487 D2). Every such submission
failed at the INSERT. NULL here means "platform", as on platform_alerts.

Revision ID: c5bb070808f5
Revises: 76782aa3349a
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c5bb070808f5"
down_revision = "76782aa3349a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("feedbacks", "company_id", existing_type=postgresql.UUID(as_uuid=True), nullable=True)


def downgrade() -> None:
    # Platform submissions have no tenant to restore; they leave with the column constraint.
    op.execute("DELETE FROM feedbacks WHERE company_id IS NULL")
    op.alter_column("feedbacks", "company_id", existing_type=postgresql.UUID(as_uuid=True), nullable=False)

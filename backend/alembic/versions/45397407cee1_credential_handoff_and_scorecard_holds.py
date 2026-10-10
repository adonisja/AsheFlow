"""ADR-491 credential handoff + ADR-492 scorecard retention holds

Revision ID: 45397407cee1
Revises: f3c49b344868
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "45397407cee1"
down_revision = "f3c49b344868"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ADR-491 — values are destroyed when the handoff ends; the row stays as status.
    op.alter_column("trainee_credentials", "flex_email", existing_type=sa.String(), nullable=True)
    op.alter_column("trainee_credentials", "clock_in_code", existing_type=sa.String(), nullable=True)
    op.add_column("trainee_credentials", sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("trainee_credentials", sa.Column("expired_at", sa.DateTime(timezone=True), nullable=True))

    # ADR-492 — a declared hold stops the 13-month clock.
    op.add_column("scorecards", sa.Column("retention_hold_until", sa.Date(), nullable=True))
    op.add_column("scorecards", sa.Column(
        "retention_hold_indefinite", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("scorecards", sa.Column(
        "retention_hold_set_by", postgresql.UUID(as_uuid=True),
        sa.ForeignKey("employees.id", ondelete="SET NULL"), nullable=True))
    op.add_column("scorecards", sa.Column("retention_hold_set_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("scorecards", "retention_hold_set_at")
    op.drop_column("scorecards", "retention_hold_set_by")
    op.drop_column("scorecards", "retention_hold_indefinite")
    op.drop_column("scorecards", "retention_hold_until")
    op.drop_column("trainee_credentials", "expired_at")
    op.drop_column("trainee_credentials", "confirmed_at")
    # A destroyed value cannot be restored; rows without one are status-only and
    # are dropped rather than given a fake secret.
    op.execute("DELETE FROM trainee_credentials WHERE flex_email IS NULL OR clock_in_code IS NULL")
    op.alter_column("trainee_credentials", "clock_in_code", existing_type=sa.String(), nullable=False)
    op.alter_column("trainee_credentials", "flex_email", existing_type=sa.String(), nullable=False)

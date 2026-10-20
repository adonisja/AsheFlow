"""ADR-541 D2: tokens issued before a password or email change are refused.

Revision ID: a64cf3783c8d
Revises: 4a63452a4f96
"""
from alembic import op
import sqlalchemy as sa

revision = "a64cf3783c8d"
down_revision = "4a63452a4f96"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable: NULL means "no change has happened", so every existing token
    # stays valid. Stamped by account_security.end_all_sessions.
    op.add_column("employees", sa.Column("tokens_valid_after", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("employees", "tokens_valid_after")

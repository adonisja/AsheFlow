"""add trainee credentials table

Revision ID: a1b2c3d4e5f6
Revises: z3a4b5c6d7e8
Create Date: 2026-06-05

Stores encrypted flex-account email and clock-in code issued by management
to a phase-1 trainee. One row per trainee (upsert on re-issue).
flex_email and clock_in_code are Fernet-encrypted at the application layer.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "a1b2c3d4e5f6"
down_revision = "z3a4b5c6d7e8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trainee_credentials",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "employee_id",
            UUID(as_uuid=True),
            sa.ForeignKey("employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("flex_email", sa.String(), nullable=False),
        sa.Column("clock_in_code", sa.String(), nullable=False),
        sa.Column(
            "sent_by",
            UUID(as_uuid=True),
            sa.ForeignKey("employees.id"),
            nullable=False,
        ),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_trainee_credentials_company_id", "trainee_credentials", ["company_id"])
    op.create_unique_constraint("uq_trainee_credentials_employee", "trainee_credentials", ["employee_id"])


def downgrade() -> None:
    op.drop_constraint("uq_trainee_credentials_employee", "trainee_credentials", type_="unique")
    op.drop_index("ix_trainee_credentials_company_id", table_name="trainee_credentials")
    op.drop_table("trainee_credentials")

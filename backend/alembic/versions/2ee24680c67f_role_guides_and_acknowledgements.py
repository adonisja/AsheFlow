"""role guides and notification acknowledgements (ADR-494)

Two tables:

  role_guides                     what a company tells one role it may do,
                                  per operating mode; seeded by the platform
                                  and editable by the tenant
  notification_acknowledgements   that a person CHOSE something about one
                                  notification, as distinct from having been
                                  shown it

Revision ID: 2ee24680c67f
Revises: 8d555bb8672b
Create Date: 2026-10-11
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "2ee24680c67f"
down_revision = "8d555bb8672b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "role_guides",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", UUID(as_uuid=True),
                  sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        # NOT nullable: ADR-305 changes half the surface, so one body cannot be
        # true for both modes (ADR-494 D4).
        sa.Column("operating_mode", sa.String(16), nullable=False),
        sa.Column("title", sa.String(80), nullable=False),
        # Text, not a capped String: this is a page the reader navigated to, so
        # the ticker's 280-char reasoning (ADR-488 D10) does not apply.
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("seed_key", sa.String(64), nullable=True),
        sa.Column("seed_version", sa.String(16), nullable=True),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("edited_by", UUID(as_uuid=True),
                  sa.ForeignKey("employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint("operating_mode IN ('full', 'workforce')",
                           name="ck_role_guide_mode"),
        # An edit records WHO. edited_at without edited_by is a change nobody
        # owns — the ADR-490 failure in a different column.
        sa.CheckConstraint("(edited_at IS NULL) = (edited_by IS NULL)",
                           name="ck_role_guide_edit_attributed"),
    )
    op.create_index("ix_role_guides_company_id", "role_guides", ["company_id"])
    # One guide per role per mode per tenant: what makes the seeder idempotent
    # and "edit the walker's full-mode guide" unambiguous.
    op.create_index("uq_role_guide", "role_guides",
                    ["company_id", "role", "operating_mode"], unique=True)

    op.create_table(
        "notification_acknowledgements",
        # The notification is the PK: one acknowledgement per notification, and a
        # notification addresses exactly one employee. A composite key with
        # employee_id would permit two rows for one notification.
        sa.Column("notification_id", UUID(as_uuid=True),
                  sa.ForeignKey("notifications.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("employee_id", UUID(as_uuid=True),
                  sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("company_id", UUID(as_uuid=True),
                  sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("action", sa.String(12), nullable=False),
        sa.Column("shown_as", sa.String(8), nullable=False),
        # 'unavailable' is the third value, and it is not a nicety: ADR-494 D6
        # degrades a gate whose action cannot be offered, and a row reading
        # 'skipped' when nobody was offered the choice asserts a declined
        # decision that was never presented.
        sa.CheckConstraint("action IN ('confirmed', 'skipped', 'unavailable')",
                           name="ck_ack_action"),
        sa.CheckConstraint("shown_as IN ('gate', 'prompt')", name="ck_ack_shown_as"),
    )
    op.create_index("ix_notification_acks_employee_id",
                    "notification_acknowledgements", ["employee_id"])
    op.create_index("ix_notification_acks_company_id",
                    "notification_acknowledgements", ["company_id"])


def downgrade() -> None:
    op.drop_index("ix_notification_acks_company_id",
                  table_name="notification_acknowledgements")
    op.drop_index("ix_notification_acks_employee_id",
                  table_name="notification_acknowledgements")
    op.drop_table("notification_acknowledgements")
    op.drop_index("uq_role_guide", table_name="role_guides")
    op.drop_index("ix_role_guides_company_id", table_name="role_guides")
    op.drop_table("role_guides")

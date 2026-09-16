"""ADR-426: device_id on collected_address_profiles

Lets a collector correct their own entry after a door reaches the verification
limit. Nullable — every existing row predates the field, and a NULL device can
never match a submitting one, so those rows stay uneditable rather than becoming
editable by whoever asks first.

Revision ID: 60a2ecf2f1e0
Revises: 08ea47de7f20
"""
from alembic import op
import sqlalchemy as sa

revision = "60a2ecf2f1e0"
down_revision = "08ea47de7f20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "collected_address_profiles",
        sa.Column("device_id", sa.String(length=64), nullable=True),
    )
    # The lookup is always (token, door, device) — "did this device already
    # submit this door under this campaign".
    op.create_index(
        "ix_collected_profiles_token_door_device",
        "collected_address_profiles",
        ["token_id", "door_key", "device_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_collected_profiles_token_door_device",
                  table_name="collected_address_profiles")
    op.drop_column("collected_address_profiles", "device_id")

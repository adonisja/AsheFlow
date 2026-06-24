"""update_adp_escalation_thresholds_add_mandatory_day

Revision ID: 9081104444eb
Revises: de016e575c09
Create Date: 2026-06-19 19:57:36.398336

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9081104444eb'
down_revision: Union[str, Sequence[str], None] = 'de016e575c09'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "company_configs", "adp_urgent_correction_day",
        existing_type=sa.Integer(),
        server_default="5",
    )
    op.add_column(
        "company_configs",
        sa.Column("adp_mandatory_correction_day", sa.Integer(), nullable=False, server_default="6"),
    )
    op.alter_column(
        "company_configs", "adp_mandatory_correction_hour",
        existing_type=sa.Integer(),
        server_default="0",
    )


def downgrade() -> None:
    op.drop_column("company_configs", "adp_mandatory_correction_day")
    op.alter_column(
        "company_configs", "adp_urgent_correction_day",
        existing_type=sa.Integer(),
        server_default="6",
    )
    op.alter_column(
        "company_configs", "adp_mandatory_correction_hour",
        existing_type=sa.Integer(),
        server_default="12",
    )

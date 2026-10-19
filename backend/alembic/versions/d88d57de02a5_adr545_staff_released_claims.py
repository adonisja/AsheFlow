"""ADR-545 D4: platform staff may release a stuck claim ("staff_released").

Revision ID: d88d57de02a5
Revises: f36f3f29ac77
"""
from alembic import op

revision = "d88d57de02a5"
down_revision = "f36f3f29ac77"
branch_labels = None
depends_on = None

_OLD = "('released', 'walk_closed', 'area_closed')"
_NEW = "('released', 'walk_closed', 'area_closed', 'staff_released')"


def upgrade() -> None:
    op.drop_constraint("ck_survey_claim_release_reason", "survey_block_claims", type_="check")
    op.create_check_constraint(
        "ck_survey_claim_release_reason", "survey_block_claims",
        f"release_reason IS NULL OR release_reason IN {_NEW}",
    )


def downgrade() -> None:
    # A staff-released row would violate the old constraint; fold it into
    # "released" (the closest meaning) rather than fail the downgrade.
    op.execute("UPDATE survey_block_claims SET release_reason = 'released' WHERE release_reason = 'staff_released'")
    op.drop_constraint("ck_survey_claim_release_reason", "survey_block_claims", type_="check")
    op.create_check_constraint(
        "ck_survey_claim_release_reason", "survey_block_claims",
        f"release_reason IS NULL OR release_reason IN {_OLD}",
    )

"""add check constraints for dispatch weight columns

Revision ID: c6d7e8f9a0b1
Revises: b5c6d7e8f9a0
Create Date: 2026-06-01

All seven dispatch weight / bonus / penalty / cap columns must be in [0, 1]
when set. NULL is allowed (means "use the hardcoded default from constants.py").
"""
from alembic import op

revision = 'c6d7e8f9a0b1'
down_revision = 'b5c6d7e8f9a0'
branch_labels = None
depends_on = None


def upgrade():
    op.create_check_constraint(
        "ck_company_configs_weight_driver",
        "company_configs",
        "dispatch_weight_driver IS NULL OR (dispatch_weight_driver BETWEEN 0 AND 1)",
    )
    op.create_check_constraint(
        "ck_company_configs_weight_trainer",
        "company_configs",
        "dispatch_weight_trainer IS NULL OR (dispatch_weight_trainer BETWEEN 0 AND 1)",
    )
    op.create_check_constraint(
        "ck_company_configs_weight_walker",
        "company_configs",
        "dispatch_weight_walker IS NULL OR (dispatch_weight_walker BETWEEN 0 AND 1)",
    )
    op.create_check_constraint(
        "ck_company_configs_mutual_bonus",
        "company_configs",
        "dispatch_mutual_bonus IS NULL OR (dispatch_mutual_bonus BETWEEN 0 AND 1)",
    )
    op.create_check_constraint(
        "ck_company_configs_tridirectional_bonus",
        "company_configs",
        "dispatch_tridirectional_bonus IS NULL OR (dispatch_tridirectional_bonus BETWEEN 0 AND 1)",
    )
    op.create_check_constraint(
        "ck_company_configs_consecutive_penalty",
        "company_configs",
        "dispatch_consecutive_penalty IS NULL OR (dispatch_consecutive_penalty BETWEEN 0 AND 1)",
    )
    op.create_check_constraint(
        "ck_company_configs_weight_cap",
        "company_configs",
        "dispatch_weight_cap IS NULL OR (dispatch_weight_cap BETWEEN 0 AND 1)",
    )


def downgrade():
    op.drop_constraint("ck_company_configs_weight_cap",           "company_configs", type_="check")
    op.drop_constraint("ck_company_configs_consecutive_penalty",  "company_configs", type_="check")
    op.drop_constraint("ck_company_configs_tridirectional_bonus", "company_configs", type_="check")
    op.drop_constraint("ck_company_configs_mutual_bonus",         "company_configs", type_="check")
    op.drop_constraint("ck_company_configs_weight_walker",        "company_configs", type_="check")
    op.drop_constraint("ck_company_configs_weight_trainer",       "company_configs", type_="check")
    op.drop_constraint("ck_company_configs_weight_driver",        "company_configs", type_="check")

"""ADR-356 follow-up: a distinct one-way tier for trainers

Revision ID: 8a3202667eff
Revises: 6ce289914e1c
Create Date: 2026-09-02

A trainer and a walker shared `oneway_weak`, so a trainer's own preference
carried no more weight than a walker's — inconsistent with the stated seniority
driver > captain > trainer > walker.

A SEPARATE migration rather than an edit to 6ce289914e1c: that revision has
already been applied to staging, so amending it in place would leave the column
missing there while alembic still reported the revision as done.
"""
from alembic import op
import sqlalchemy as sa

revision = "8a3202667eff"
down_revision = "6ce289914e1c"
branch_labels = None
depends_on = None

_COL = "dispatch_target_oneway_trainer"


def upgrade() -> None:
    op.add_column("company_configs", sa.Column(_COL, sa.Float(), nullable=True))
    op.create_check_constraint(
        "ck_company_configs_target_oneway_trainer",
        "company_configs",
        f"{_COL} IS NULL OR ({_COL} >= 0 AND {_COL} < 1)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_company_configs_target_oneway_trainer", "company_configs", type_="check"
    )
    op.drop_column("company_configs", _COL)

"""ADR-356 follow-up: rank mutual pairs by which two roles bonded

Revision ID: 80814ae0a3dd
Revises: 8a3202667eff
Create Date: 2026-09-02

driver<->captain, driver<->trainer and driver<->walker all resolved to one
`mutual_strong` tier at 55%, because the check only asked whether a crew lead
was involved. The driver and captain jointly control and organise the truck, so
their bond has the largest effect on the day; a driver-trainer bond means less
friction for the trainer, who can then focus on their paired trainee.

RENAMES mutual_strong -> mutual_lead_crew (same meaning, clearer name now that
it is one of three) and adds the two stronger tiers. A rename rather than
drop-and-add so any value a tenant has already set is preserved.
"""
from alembic import op
import sqlalchemy as sa

revision = "80814ae0a3dd"
down_revision = "8a3202667eff"
branch_labels = None
depends_on = None

_NEW = ("mutual_driver_trainer", "mutual_driver_captain")


def upgrade() -> None:
    op.execute(
        "ALTER TABLE company_configs "
        "RENAME COLUMN dispatch_target_mutual_strong TO dispatch_target_mutual_lead_crew"
    )
    op.execute(
        "ALTER TABLE company_configs "
        "RENAME CONSTRAINT ck_company_configs_target_mutual_strong "
        "TO ck_company_configs_target_mutual_lead_crew"
    )
    for name in _NEW:
        col = f"dispatch_target_{name}"
        op.add_column("company_configs", sa.Column(col, sa.Float(), nullable=True))
        op.create_check_constraint(
            f"ck_company_configs_target_{name}",
            "company_configs",
            f"{col} IS NULL OR ({col} >= 0 AND {col} < 1)",
        )


def downgrade() -> None:
    for name in _NEW:
        op.drop_constraint(
            f"ck_company_configs_target_{name}", "company_configs", type_="check"
        )
        op.drop_column("company_configs", f"dispatch_target_{name}")
    op.execute(
        "ALTER TABLE company_configs "
        "RENAME CONSTRAINT ck_company_configs_target_mutual_lead_crew "
        "TO ck_company_configs_target_mutual_strong"
    )
    op.execute(
        "ALTER TABLE company_configs "
        "RENAME COLUMN dispatch_target_mutual_lead_crew TO dispatch_target_mutual_strong"
    )

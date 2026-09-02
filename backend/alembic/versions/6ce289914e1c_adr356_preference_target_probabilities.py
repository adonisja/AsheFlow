"""ADR-356: preference strength as target probabilities

Revision ID: 6ce289914e1c
Revises: ff1deea176cf
Create Date: 2026-09-02

Adds seven nullable dispatch_target_* columns to company_configs.

The existing dispatch_weight_* / dispatch_*_bonus columns are DELIBERATELY LEFT
IN PLACE. A tenant's stored 0.70 is a weight MULTIPLIER; reading it as a
probability would silently change dispatch for every company that ever tuned
one. New columns default NULL and fall back to the platform defaults in
services/preference_tiers.py, so migrating a tenant is a deliberate act.

CHECK is >= 0 AND < 1, not BETWEEN 0 AND 1: a target of 1.0 means "always this
truck", which is a pin rather than a preference, and weight_for_target divides
by (1 - target).
"""
from alembic import op
import sqlalchemy as sa

revision = "6ce289914e1c"
down_revision = "ff1deea176cf"
branch_labels = None
depends_on = None

_TARGETS = (
    "oneway_weak",
    "oneway_captain",
    "oneway_driver",
    "mutual_weak",
    "mutual_strong",
    "tridirectional",
    "trio_plus",
)


def upgrade() -> None:
    for name in _TARGETS:
        col = f"dispatch_target_{name}"
        op.add_column("company_configs", sa.Column(col, sa.Float(), nullable=True))
        op.create_check_constraint(
            f"ck_company_configs_target_{name}",
            "company_configs",
            f"{col} IS NULL OR ({col} >= 0 AND {col} < 1)",
        )


def downgrade() -> None:
    for name in _TARGETS:
        op.drop_constraint(
            f"ck_company_configs_target_{name}", "company_configs", type_="check"
        )
        op.drop_column("company_configs", f"dispatch_target_{name}")

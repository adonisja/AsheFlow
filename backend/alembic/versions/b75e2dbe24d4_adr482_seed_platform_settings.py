"""ADR-482: backfill the platform settings every company was created without.

`create_company` did `db.add(CompanyConfig(company_id=...))` with no values, and
these eight columns document a default in a COMMENT while declaring none in code
(no `default=`, no `server_default`). So every company ever created has all
fifteen required fields NULL, and the Owner can only fill the seven the setup
form collects.

The live prod tenant sat at is_configured=False with a 200 OK on every save:

    missing= ['invite_expiry_days', 'dispatch_weight_driver',
     'dispatch_weight_trainer', 'dispatch_weight_walker', 'dispatch_mutual_bonus',
     'dispatch_tridirectional_bonus', 'dispatch_consecutive_penalty',
     'dispatch_weight_cap']

D1 fixes companies created from now on. This fixes the ones that already exist.

ONLY WHERE NULL. A tenant whose weights were tuned by hand must keep them --
this fills a gap, it does not reset a configuration. Each column is updated
independently for the same reason.

Values match PLATFORM_SEEDED_DEFAULTS; the weights satisfy ADR-186 D3
(W_TIME and W_DIFF >= W_DENSE).

Self-contained: no import from app.* (tests/test_migrations_are_self_contained).

Revision ID: b75e2dbe24d4
Revises: 3457b5455fff
Create Date: 2026-09-29
"""
from alembic import op
import sqlalchemy as sa

revision = "b75e2dbe24d4"
down_revision = "3457b5455fff"
branch_labels = None
depends_on = None

# Mirrors company_config.PLATFORM_SEEDED_DEFAULTS. Duplicated deliberately: a
# migration that imports live code breaks when that code is renamed (ADR-427).
_DEFAULTS = {
    "invite_expiry_days":            7,
    "dispatch_weight_driver":        0.70,
    "dispatch_weight_trainer":       0.25,
    "dispatch_weight_walker":        0.15,
    "dispatch_mutual_bonus":         0.10,
    "dispatch_tridirectional_bonus": 0.20,
    "dispatch_consecutive_penalty":  0.05,
    "dispatch_weight_cap":           0.85,
}


def upgrade() -> None:
    conn = op.get_bind()
    for column, value in _DEFAULTS.items():
        conn.execute(
            sa.text(
                f"UPDATE company_configs SET {column} = :v WHERE {column} IS NULL"
            ),
            {"v": value},
        )


def downgrade() -> None:
    """Deliberately does nothing.

    The upgrade cannot distinguish a value it wrote from one a platform admin
    set afterwards, so nulling these columns would destroy real configuration to
    undo a gap-fill. There is nothing to reverse: before this ran the columns
    were NULL, which is the broken state it exists to repair."""
    pass

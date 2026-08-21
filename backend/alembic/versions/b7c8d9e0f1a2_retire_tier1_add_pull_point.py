"""retire tier-1 thresholds; add pull_point to package_removals

Revision ID: b7c8d9e0f1a2
Revises: a6b7c8d9e0f1
Create Date: 2026-07-03

ADR-177: the tier-1 review wall is retired (classifications were vestiges of
the dead K-Means pipeline), so its five CompanyConfig threshold columns go.
package_removals gains pull_point: whole totes pull at the STATION, single
out-of-zone packages pull at the ANCHOR POINT (walker/driver).
"""

from alembic import op
import sqlalchemy as sa

revision = 'b7c8d9e0f1a2'
down_revision = 'a6b7c8d9e0f1'
branch_labels = None
depends_on = None

_TIER1_COLS = [
    ('tier1_small_tote_cutoff', sa.Integer()),
    ('tier1_small_stray_max', sa.Integer()),
    ('tier1_small_uncertain_max', sa.Integer()),
    ('tier1_stray_pct', sa.Float()),
    ('tier1_uncertain_pct', sa.Float()),
]


def upgrade() -> None:
    for name, _ in _TIER1_COLS:
        op.drop_column('company_configs', name)
    op.add_column(
        'package_removals',
        sa.Column('pull_point', sa.String(20), nullable=False, server_default='station'),
    )


def downgrade() -> None:
    op.drop_column('package_removals', 'pull_point')
    for name, col_type in _TIER1_COLS:
        op.add_column('company_configs', sa.Column(name, col_type, nullable=True))

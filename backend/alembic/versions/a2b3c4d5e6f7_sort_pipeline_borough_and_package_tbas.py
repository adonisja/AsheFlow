"""sort pipeline: add geoclient_borough to company_configs, package_tbas to truck_zones

Revision ID: a2b3c4d5e6f7
Revises: w0x1y2z3a4b5
Create Date: 2026-05-29

geoclient_borough: the NYC borough (or equivalent geographic unit) used when
calling the GeoClient address normalisation API. Stored per-company so DSPs
operating in different boroughs (Brooklyn, Queens, etc.) don't get wrong
normalisation. NULL = use platform default inference from package coordinates.

package_tbas: JSONB list of TBA strings belonging to each TruckZone cluster.
Stored at sort time so the walker sort can retrieve the packages for a specific
truck from the enriched Redis manifest without the client re-supplying them.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = 'a2b3c4d5e6f7'
down_revision = 'w0x1y2z3a4b5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('company_configs',
        sa.Column('geoclient_borough', sa.String(30), nullable=True)
    )
    op.add_column('truck_zones',
        sa.Column('package_tbas', JSONB, nullable=True)
    )


def downgrade() -> None:
    op.drop_column('company_configs', 'geoclient_borough')
    op.drop_column('truck_zones', 'package_tbas')

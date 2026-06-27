"""add normalised_addresses to routes

Revision ID: a0b1c2d3e4f5
Revises: z3a4b5c6d7e8
Create Date: 2026-06-26

Add normalised_addresses TEXT[] column to routes table.
Populated at route commit time by route_sort — allows next-stop suggestions and
stop grouping to work after the Redis manifest TTL expires.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY

revision = 'a0b1c2d3e4f5'
down_revision = 'z3a4b5c6d7e8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'routes',
        sa.Column(
            'normalised_addresses',
            ARRAY(sa.Text()),
            nullable=False,
            server_default='{}',
        ),
    )


def downgrade() -> None:
    op.drop_column('routes', 'normalised_addresses')

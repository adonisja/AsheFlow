"""ADR-584 D6: troublesome doors, keyed by door identity, off BuildingProfile.

Copies every non-zero BuildingProfile troublesome score across. The borough is
NULL for copied rows: a migration can't reach PlaceType to resolve it.

Revision ID: a5f522b5b53d
Revises: e61872c1fa3f
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "a5f522b5b53d"
down_revision = "e61872c1fa3f"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "troublesome_doors",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("borough", sa.String(1), nullable=True),
        sa.Column("address", sa.String(200), nullable=False),
        sa.Column("score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("last_incident_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("company_id", "borough", "address", name="uq_troublesome_doors_door"),
    )
    op.create_index("ix_troublesome_doors_company_id", "troublesome_doors", ["company_id"])
    op.execute("""
        INSERT INTO troublesome_doors (id, company_id, borough, address, score, last_incident_at, resolved_at)
        SELECT gen_random_uuid(), company_id, NULL, normalised_address, troublesome_score,
               troublesome_last_incident_at, troublesome_resolved_at
        FROM building_profiles
        WHERE troublesome_score > 0 AND normalised_address IS NOT NULL
        ON CONFLICT DO NOTHING
    """)


def downgrade():
    op.drop_index("ix_troublesome_doors_company_id", table_name="troublesome_doors")
    op.drop_table("troublesome_doors")

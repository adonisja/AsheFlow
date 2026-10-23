"""ADR-581: the Library holds no tenant-derived intelligence.

Deletes every building_profile_library row that is not geometry_only (all of
them were promoted from tenant BuildingProfiles; ADR-580), and drops the
columns that recorded tenant provenance and the nomination pipeline:
building_profile_library.promoted_from_company_ids / promoted_at / promoted_by /
promoted_by_name and building_profiles.nomination_status.

The geometry_only rows stay until the owner's citywide seed replaces them
(ADR-580 D9): routing reads them today.

Revision ID: 1a2a54f009ff
Revises: c5bb070808f5
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "1a2a54f009ff"
down_revision = "c5bb070808f5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DELETE FROM building_profile_library WHERE library_status <> 'geometry_only'")
    for col in ("promoted_from_company_ids", "promoted_at", "promoted_by", "promoted_by_name"):
        op.execute(f"ALTER TABLE building_profile_library DROP COLUMN IF EXISTS {col}")
    op.execute("ALTER TABLE building_profiles DROP COLUMN IF EXISTS nomination_status")


def downgrade() -> None:
    # The deleted rows were tenant-derived and are not restored (ADR-580).
    op.add_column("building_profiles", sa.Column("nomination_status", sa.String(20), nullable=True))
    op.add_column("building_profile_library", sa.Column("promoted_from_company_ids",
                  postgresql.ARRAY(postgresql.UUID(as_uuid=True)), nullable=True))
    op.add_column("building_profile_library", sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("building_profile_library", sa.Column("promoted_by", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("building_profile_library", sa.Column("promoted_by_name", sa.String(100), nullable=True))

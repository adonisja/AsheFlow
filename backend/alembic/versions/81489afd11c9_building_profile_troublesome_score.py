"""building_profile: troublesome decaying score (ADR-218)

Revision ID: 81489afd11c9
Revises: 137bdd270963
Create Date: 2026-07-21

ADR-218: distill the RTS "troublesome address" signal into a decaying score on
the building profile so the company-wide troublesome list reads off the building
(not retained delivery rows). Bumped per RTS (weighted by type), decayed nightly.
"""
from alembic import op
import sqlalchemy as sa

revision = "81489afd11c9"
down_revision = "137bdd270963"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("building_profiles", sa.Column("troublesome_score", sa.Float(), server_default="0", nullable=False))
    op.add_column("building_profiles", sa.Column("troublesome_last_incident_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("building_profiles", sa.Column("troublesome_resolved_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("building_profiles", "troublesome_resolved_at")
    op.drop_column("building_profiles", "troublesome_last_incident_at")
    op.drop_column("building_profiles", "troublesome_score")

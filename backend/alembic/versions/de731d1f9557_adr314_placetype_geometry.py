"""ADR-314 — PlaceType gains a geometry tier

Revision ID: de731d1f9557
Revises: e506600c0541
Create Date: 2026-08-26

`building_profile_library` held 33 columns of building INTELLIGENCE — type,
workload, notes, hours, verification — and no geometry or identity at all. It
could say a building was a walk-up with a tricky mailroom and could not say
where it was.

Ground truth is identical for every tenant standing on it (ADR-237's test:
"independent of who is delivering"), so it belongs to PlaceType rather than to
`building_profiles`, which is company-scoped. Storing it per tenant would mean N
enrichments returning N identical answers, and would break the case where a
second tenant in the same city pays nothing for ground already mapped.

`street_segments` gains the blockface house-number range — ADR-303 D4's missing
"segment span". Verified per-segment rather than per-address: three addresses on
segment 0297696 all return the same 000002000AA..000098000AA, so storing it per
address would duplicate one fact ~18 times (the measured mean addresses/block).

`building_profiles` gains `bin` ONLY, as the join key to the rows above.

All columns nullable: every existing row predates them.
"""
from alembic import op
import sqlalchemy as sa

revision = "de731d1f9557"
down_revision = "e506600c0541"
branch_labels = None
depends_on = None


def upgrade():
    # ── PlaceType: building identity + geometry ──────────────────────────────
    op.add_column("building_profile_library", sa.Column("bin", sa.String(20), nullable=True))
    op.add_column("building_profile_library", sa.Column("bbl", sa.String(20), nullable=True))
    op.add_column("building_profile_library", sa.Column("zip_code", sa.String(10), nullable=True))
    op.add_column("building_profile_library", sa.Column("lat", sa.Float(), nullable=True))
    op.add_column("building_profile_library", sa.Column("lng", sa.Float(), nullable=True))
    op.add_column("building_profile_library", sa.Column("segment_id", sa.String(20), nullable=True))
    op.add_column("building_profile_library", sa.Column("corner_code", sa.String(10), nullable=True))
    op.add_column("building_profile_library", sa.Column("structures_on_lot", sa.Integer(), nullable=True))
    op.add_column("building_profile_library", sa.Column("street_frontages", sa.Integer(), nullable=True))
    op.add_column("building_profile_library", sa.Column("geo_grc", sa.String(10), nullable=True))
    op.add_column("building_profile_library", sa.Column("geo_enriched_at", sa.DateTime(timezone=True), nullable=True))
    # BIN is the building identity (D1) and the dedupe key a future re-keying
    # would use; indexed but NOT unique — one BIN legitimately covers several
    # addresses (350 5 AVE and 2 W 34 ST are both BIN 1015862).
    op.create_index("ix_building_profile_library_bin", "building_profile_library", ["bin"])
    # Resumability for the enrichment pass (D4) keys on this being NULL.
    op.create_index("ix_bpl_geo_enriched_at", "building_profile_library", ["geo_enriched_at"])

    # ── PlaceType: topology (ADR-303 D4's span) ──────────────────────────────
    op.add_column("street_segments", sa.Column("low_house_number", sa.String(20), nullable=True))
    op.add_column("street_segments", sa.Column("high_house_number", sa.String(20), nullable=True))
    op.add_column("street_segments", sa.Column("first_cross_street", sa.String(100), nullable=True))
    op.add_column("street_segments", sa.Column("second_cross_street", sa.String(100), nullable=True))

    # ── Tenant: the join key only ────────────────────────────────────────────
    op.add_column("building_profiles", sa.Column("bin", sa.String(20), nullable=True))
    op.create_index("ix_building_profiles_bin", "building_profiles", ["bin"])


def downgrade():
    op.drop_index("ix_building_profiles_bin", table_name="building_profiles")
    op.drop_column("building_profiles", "bin")
    for col in ("second_cross_street", "first_cross_street",
                "high_house_number", "low_house_number"):
        op.drop_column("street_segments", col)
    op.drop_index("ix_bpl_geo_enriched_at", table_name="building_profile_library")
    op.drop_index("ix_building_profile_library_bin", table_name="building_profile_library")
    for col in ("geo_enriched_at", "geo_grc", "street_frontages", "structures_on_lot",
                "corner_code", "segment_id", "lng", "lat", "zip_code", "bbl", "bin"):
        op.drop_column("building_profile_library", col)

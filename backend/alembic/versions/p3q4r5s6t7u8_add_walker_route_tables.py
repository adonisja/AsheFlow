"""add walker_routes, walker_trips, location_difficulty_flags, misrouted_package_flags

Revision ID: p3q4r5s6t7u8
Revises: o2p3q4r5s6t7
Create Date: 2026-05-17

"""
import uuid
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, ARRAY

revision = 'p3q4r5s6t7u8'
down_revision = 'o2p3q4r5s6t7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "walker_routes",
        sa.Column("id",                  UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("company_id",          UUID(as_uuid=True), nullable=False),
        sa.Column("truck_assignment_id", UUID(as_uuid=True), sa.ForeignKey("truck_assignments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("route_date",          sa.Date(),          nullable=False),
        sa.Column("walker_id",           UUID(as_uuid=True), sa.ForeignKey("employees.id",         ondelete="CASCADE"), nullable=False),
        sa.Column("total_packages",      sa.Integer(),       nullable=False, server_default="0"),
        sa.Column("total_bags",          sa.Integer(),       nullable=False, server_default="0"),
        sa.Column("total_ovs",           sa.Integer(),       nullable=False, server_default="0"),
        sa.Column("planned_trips",       sa.Integer(),       nullable=False, server_default="1"),
        sa.Column("actual_trips",        sa.Integer(),       nullable=True),
        sa.Column("completed_at",        sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at",          sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_walker_routes_company_id",          "walker_routes", ["company_id"])
    op.create_index("ix_walker_routes_truck_assignment_id", "walker_routes", ["truck_assignment_id"])
    op.create_index("ix_walker_routes_walker_id",           "walker_routes", ["walker_id"])
    op.create_index("ix_walker_routes_route_date",          "walker_routes", ["route_date"])

    op.create_table(
        "walker_trips",
        sa.Column("id",              UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("company_id",      UUID(as_uuid=True), nullable=False),
        sa.Column("walker_route_id", UUID(as_uuid=True), sa.ForeignKey("walker_routes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("trip_number",     sa.Integer(),       nullable=False),
        sa.Column("bag_ids",         ARRAY(sa.Text()),   nullable=False, server_default="{}"),
        sa.Column("tba_numbers",     ARRAY(sa.Text()),   nullable=False, server_default="{}"),
        sa.Column("tag_numbers",     ARRAY(sa.Text()),   nullable=False, server_default="{}"),
        sa.Column("status",          sa.String(20),      nullable=False, server_default="pending"),
        sa.Column("departed_at",     sa.DateTime(timezone=True), nullable=True),
        sa.Column("returned_at",     sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_walker_trips_company_id",      "walker_trips", ["company_id"])
    op.create_index("ix_walker_trips_walker_route_id", "walker_trips", ["walker_route_id"])

    op.create_table(
        "location_difficulty_flags",
        sa.Column("id",              UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("company_id",      UUID(as_uuid=True), nullable=False),
        sa.Column("block_key",       sa.String(100),     nullable=False),
        sa.Column("difficulty_tier", sa.String(20),      nullable=False, server_default="standard"),
        sa.Column("flagged_by",      UUID(as_uuid=True), sa.ForeignKey("employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("flagged_at",      sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("notes",           sa.Text(),          nullable=True),
    )
    op.create_index("ix_location_difficulty_flags_company_id", "location_difficulty_flags", ["company_id"])
    op.create_index("ix_location_difficulty_flags_block_key",  "location_difficulty_flags", ["block_key"])

    op.create_table(
        "misrouted_package_flags",
        sa.Column("id",                        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("company_id",                UUID(as_uuid=True), nullable=False),
        sa.Column("walker_route_id",           UUID(as_uuid=True), sa.ForeignKey("walker_routes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tba_number",                sa.String(50),      nullable=False),
        sa.Column("tag_number",                sa.String(50),      nullable=True),
        sa.Column("current_bag_id",            sa.String(50),      nullable=False),
        sa.Column("suggested_walker_route_id", UUID(as_uuid=True), nullable=True),
        sa.Column("resolved",                  sa.Boolean(),       nullable=False, server_default="false"),
        sa.Column("resolved_by",               UUID(as_uuid=True), sa.ForeignKey("employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("resolved_at",               sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_misrouted_package_flags_company_id",      "misrouted_package_flags", ["company_id"])
    op.create_index("ix_misrouted_package_flags_walker_route_id", "misrouted_package_flags", ["walker_route_id"])


def downgrade() -> None:
    op.drop_table("misrouted_package_flags")
    op.drop_table("location_difficulty_flags")
    op.drop_table("walker_trips")
    op.drop_table("walker_routes")

"""ADR-504 D8: the survey form, version 2.

Delivery points move to their own table (up to three, with side, floor and
"which packages"); "also receives for" links; hours by day group; yes/no/
unknown for security desk and sign-in; "not a delivery point".

Revision ID: 55aa7a9444d4
Revises: c227c9f175f3
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "55aa7a9444d4"
down_revision = "c227c9f175f3"
branch_labels = None
depends_on = None

_TRI = "('yes', 'no', 'unknown')"
_DAY = "('open', 'closed', 'unknown')"
_GROUPS = ("weekday", "saturday", "sunday")


def upgrade():
    op.create_table(
        "survey_delivery_points",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("observation_id", UUID(as_uuid=True),
                  sa.ForeignKey("survey_observations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("point", sa.String(20), nullable=False),
        sa.Column("side", sa.String(120), nullable=True),
        sa.Column("floor", sa.Integer(), nullable=True),
        sa.Column("which_packages", sa.String(120), nullable=True),
        sa.CheckConstraint("point IN ('main_entrance', 'service_entrance', 'loading_dock', 'mailroom', 'front_desk')",
                           name="ck_survey_dp_point"),
        sa.CheckConstraint("position >= 1 AND position <= 3", name="ck_survey_dp_position"),
        sa.CheckConstraint("floor IS NULL OR (floor >= -5 AND floor <= 200)", name="ck_survey_dp_floor"),
        sa.UniqueConstraint("observation_id", "position", name="uq_survey_dp_position"),
    )
    op.create_index("ix_survey_delivery_points_observation_id", "survey_delivery_points", ["observation_id"])

    op.create_table(
        "survey_receives_for",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("observation_id", UUID(as_uuid=True),
                  sa.ForeignKey("survey_observations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("address", sa.String(200), nullable=False),
        sa.Column("bin", sa.String(20), nullable=True),
        sa.UniqueConstraint("observation_id", "address", name="uq_survey_rf_address"),
    )
    op.create_index("ix_survey_receives_for_observation_id", "survey_receives_for", ["observation_id"])

    # The single delivery point and hours pair are replaced.
    op.drop_constraint("ck_survey_obs_delivery_point", "survey_observations", type_="check")
    op.drop_column("survey_observations", "delivery_point")
    op.drop_column("survey_observations", "entrance_side")
    op.drop_column("survey_observations", "opens_at")
    op.drop_column("survey_observations", "closes_at")

    op.add_column("survey_observations", sa.Column("not_a_delivery_point", sa.Boolean(),
                                                   nullable=False, server_default="false"))

    # [E] Boolean → yes / no / unknown. Explicit mapping; NULL becomes "unknown".
    for col, ck in (("security_desk", "ck_survey_obs_security_desk"),
                    ("sign_in_required", "ck_survey_obs_sign_in")):
        op.alter_column("survey_observations", col, type_=sa.String(10),
                        postgresql_using=f"CASE WHEN {col} IS TRUE THEN 'yes' "
                                         f"WHEN {col} IS FALSE THEN 'no' ELSE 'unknown' END")
        op.execute(f"UPDATE survey_observations SET {col} = 'unknown' WHERE {col} IS NULL")
        op.alter_column("survey_observations", col, nullable=False, server_default="unknown")
        op.create_check_constraint(ck, "survey_observations", f"{col} IN {_TRI}")

    for g in _GROUPS:
        op.add_column("survey_observations", sa.Column(f"{g}_status", sa.String(10),
                                                       nullable=False, server_default="unknown"))
        op.add_column("survey_observations", sa.Column(f"{g}_open", sa.Time(), nullable=True))
        op.add_column("survey_observations", sa.Column(f"{g}_close", sa.Time(), nullable=True))
        op.create_check_constraint(
            f"ck_survey_obs_{g}_hours", "survey_observations",
            f"{g}_status IN {_DAY} AND ({g}_status <> 'open' OR ({g}_open IS NOT NULL AND {g}_close IS NOT NULL))")


def downgrade():
    for g in _GROUPS:
        op.drop_constraint(f"ck_survey_obs_{g}_hours", "survey_observations", type_="check")
        for suffix in ("status", "open", "close"):
            op.drop_column("survey_observations", f"{g}_{suffix}")
    for col, ck in (("security_desk", "ck_survey_obs_security_desk"),
                    ("sign_in_required", "ck_survey_obs_sign_in")):
        op.drop_constraint(ck, "survey_observations", type_="check")
        op.alter_column("survey_observations", col, server_default=None, nullable=True)
        op.alter_column("survey_observations", col, type_=sa.Boolean(),
                        postgresql_using=f"CASE {col} WHEN 'yes' THEN TRUE WHEN 'no' THEN FALSE ELSE NULL END")
    op.drop_column("survey_observations", "not_a_delivery_point")
    op.add_column("survey_observations", sa.Column("closes_at", sa.Time(), nullable=True))
    op.add_column("survey_observations", sa.Column("opens_at", sa.Time(), nullable=True))
    op.add_column("survey_observations", sa.Column("entrance_side", sa.String(120), nullable=True))
    op.add_column("survey_observations", sa.Column("delivery_point", sa.String(20), nullable=True))
    op.create_check_constraint(
        "ck_survey_obs_delivery_point", "survey_observations",
        "delivery_point IS NULL OR delivery_point IN "
        "('main_entrance', 'service_entrance', 'loading_dock', 'mailroom', 'front_desk')")
    op.drop_table("survey_receives_for")
    op.drop_table("survey_delivery_points")

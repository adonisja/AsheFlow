"""ADR-418: building category, security-desk flag, multi-select workloads

Adds the three new columns to all three profile tables and migrates the flat
legacy values onto the new taxonomy.

Revision ID: 46f04059c09f
Revises: c1e6dd96bf3a
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "46f04059c09f"
down_revision = "c1e6dd96bf3a"
branch_labels = None
depends_on = None

_TABLES = (
    "building_profiles",
    "building_profile_library",
    "collected_address_profiles",
)


def upgrade() -> None:
    for t in _TABLES:
        op.add_column(t, sa.Column("building_category", sa.String(length=20),
                                   nullable=False, server_default="unknown"))
        op.add_column(t, sa.Column("has_security_desk", sa.Boolean(),
                                   nullable=False, server_default="false"))
        op.add_column(t, sa.Column("workloads", postgresql.JSONB(),
                                   nullable=False, server_default="[]"))
        op.create_index(f"ix_{t}_building_category", t, ["building_category"])

    # FROZEN AT THIS REVISION, not imported from app.schemas.
    #
    # This originally did `from app.schemas.building_taxonomy import ...`, and
    # ADR-419 then renamed NOT_APPLICABLE to OTHER — so a fresh
    # `alembic upgrade head` crashed with ImportError while every existing
    # database, already past this revision, kept working. A migration runs
    # against TODAY's application code but must express the schema as it was at
    # its own revision; the only safe dependency is the standard library.
    LEGACY_TYPE_MAP = {
        "walkup":            "walkup",
        "elevator":          "elevator",
        "doorman":           "doorman_reception",
        "receptionist":      "doorman_reception",
        "mailroom":          "mailroom",
        "biz_front":         "storefront_front_door",
        "biz_freight":       "freight",
        "biz_security":      "storefront_front_door",   # + has_security_desk
        "biz_loading_dock":  "loading_dock",
        "unknown":           "unknown",
    }
    LEGACY_SECURITY_DESK = {"biz_security"}
    RESIDENTIAL = {"walkup", "elevator", "doorman_reception", "mailroom", "lockers"}
    COMMERCIAL = {
        "storefront_reception", "storefront_front_door", "freight",
        "loading_dock", "loading_dock_mailroom",
    }

    def category_for(building_type: str) -> str:
        if building_type in RESIDENTIAL:
            return "residential"
        if building_type in COMMERCIAL:
            return "commercial"
        return "unknown"

    # The workload tag this revision wrote. ADR-419 renamed it to "other" and
    # migration 9c32a580c1d3 rewrites these rows — so this must keep writing the
    # OLD name, or that later migration finds nothing to rename.
    NOT_APPLICABLE = "not_applicable"

    conn = op.get_bind()
    for t in _TABLES:
        rows = conn.execute(
            sa.text(f"SELECT id, building_type, workload_class FROM {t}")
        ).fetchall()
        for row_id, old_type, old_workload in rows:
            new_type = LEGACY_TYPE_MAP.get(old_type, "unknown")
            security = old_type in LEGACY_SECURITY_DESK

            # workload_class was DERIVED from building_type, never observed —
            # so carrying it across would assert something nobody checked.
            # ADR-418 makes workload collected, and `not_applicable` is the
            # honest value for a row that predates collection. It is also
            # visibly distinct from a real collector answer, which is the
            # point: these rows need re-collecting, and the data should say so.
            conn.execute(
                sa.text(
                    f"UPDATE {t} SET building_type = :t, building_category = :c, "
                    f"has_security_desk = :s, workloads = CAST(:w AS jsonb) "
                    f"WHERE id = :i"
                ),
                {
                    "t": new_type,
                    "c": category_for(new_type),
                    "s": security,
                    "w": f'["{NOT_APPLICABLE}"]',
                    "i": row_id,
                },
            )


def downgrade() -> None:
    # building_type is NOT reverted: the legacy map is many-to-one (doorman and
    # receptionist both became doorman_reception), so the original value cannot
    # be recovered from the new one. Dropping the columns is reversible; the
    # type collapse is not, and pretending otherwise would be worse.
    for t in _TABLES:
        op.drop_index(f"ix_{t}_building_category", table_name=t)
        op.drop_column(t, "workloads")
        op.drop_column(t, "has_security_desk")
        op.drop_column(t, "building_category")

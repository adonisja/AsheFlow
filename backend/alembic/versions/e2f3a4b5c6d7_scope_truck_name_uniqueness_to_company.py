"""scope truck name uniqueness to company

Revision ID: e2f3a4b5c6d7
Revises: z3a4b5c6d7e8
Create Date: 2026-06-01

Removes the global unique constraint on trucks.name and replaces it with a
composite (company_id, name) unique constraint. Two companies can now have
trucks with the same name without conflicting.
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'e2f3a4b5c6d7'
down_revision = 'z3a4b5c6d7e8'
branch_labels = None
depends_on = None


def upgrade():
    # Drop the old global unique constraint/index on name.
    # The index name varies by how it was originally created; handle both forms.
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'trucks_name_key' AND conrelid = 'trucks'::regclass
            ) THEN
                ALTER TABLE trucks DROP CONSTRAINT trucks_name_key;
            END IF;
        END$$;
    """)
    # Also drop any standalone unique index on name (in case it was created as an index).
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'trucks' AND indexname = 'ix_trucks_name'
            ) THEN
                DROP INDEX ix_trucks_name;
            END IF;
        END$$;
    """)

    # Create the new company-scoped unique constraint.
    op.create_unique_constraint(
        "uq_trucks_company_name",
        "trucks",
        ["company_id", "name"],
    )

    # Recreate a non-unique index on name alone for fast name-based lookups.
    op.create_index("ix_trucks_name", "trucks", ["name"])


def downgrade():
    op.drop_index("ix_trucks_name", table_name="trucks")
    op.drop_constraint("uq_trucks_company_name", "trucks", type_="unique")
    # Restore global unique constraint.
    op.create_unique_constraint("trucks_name_key", "trucks", ["name"])
    op.create_index("ix_trucks_name", "trucks", ["name"])

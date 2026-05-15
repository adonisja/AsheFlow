"""employees: enforce snowflake-only discord_id, resize column to String(20)

Revision ID: m4n5o6p7q8r9
Revises: l3m4n5o6p7q8
Create Date: 2026-05-09

Changes:
  - NULL out any discord_id that is not a pure numeric string (legacy name#discriminator
    values, placeholder strings, seed identifiers — none of these are usable by the bot)
  - ALTER COLUMN employees.discord_id TYPE VARCHAR(20)

After this migration the only valid values are 17-19 digit Discord snowflake strings.
Employees whose discord_id was cleared will need to re-enter it via the Assets page
or during re-registration.
"""

import sqlalchemy as sa
from alembic import op

revision = "m4n5o6p7q8r9"
down_revision = "l3m4n5o6p7q8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NULL out any value that isn't a pure integer string.
    # Postgres regex: '^[0-9]+$' — matches only digit-only strings.
    op.execute(
        """
        UPDATE employees
        SET discord_id = NULL
        WHERE discord_id IS NOT NULL
          AND discord_id !~ '^[0-9]+$'
        """
    )

    # Drop the NOT NULL constraint that the initial schema applied.
    # The ORM has always declared discord_id nullable=True; the constraint
    # was never explicitly removed by a prior migration.
    op.alter_column("employees", "discord_id", nullable=True, existing_type=sa.String())

    # Resize the column. Existing numeric values fit easily in 20 chars.
    op.alter_column(
        "employees",
        "discord_id",
        type_=sa.String(20),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "employees",
        "discord_id",
        type_=sa.String(100),
        existing_nullable=True,
    )
    # Data that was NULL'd cannot be restored — downgrade only reverts the type.

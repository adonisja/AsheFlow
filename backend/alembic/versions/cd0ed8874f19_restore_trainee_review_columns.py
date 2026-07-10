"""restore training_records trainee review columns

Revision ID: cd0ed8874f19
Revises: c2fcfe15c4ce
Create Date: 2026-07-10

trainee_comments and trainer_rating were dropped by j1k2l3m4n5o6 as "orphaned
in DB" after being removed from the ORM — but the /record/{id}/review endpoint,
pydantic schemas, and both rating UIs still used them. Assigning an unmapped
attribute on an ORM object is a silent no-op, so trainee reviews returned
200 OK and persisted nothing from 2026-05-08 until now.

Lesson encoded here: a column referenced by an endpoint is not an orphan —
check consumers before dropping, not just the model.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text

revision = 'cd0ed8874f19'
down_revision = 'c2fcfe15c4ce'
branch_labels = None
depends_on = None


def _column_exists(conn, table: str, column: str) -> bool:
    result = conn.execute(
        text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    )
    return result.fetchone() is not None


def upgrade() -> None:
    conn = op.get_bind()
    if not _column_exists(conn, "training_records", "trainee_comments"):
        op.add_column("training_records", sa.Column("trainee_comments", sa.Text(), nullable=True))
    if not _column_exists(conn, "training_records", "trainer_rating"):
        op.add_column("training_records", sa.Column("trainer_rating", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("training_records", "trainer_rating")
    op.drop_column("training_records", "trainee_comments")

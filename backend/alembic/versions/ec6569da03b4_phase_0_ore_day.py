"""training_records: phase-0 ORE columns (ADR-281)

A trainee's first day is ORE — Amazon's self-serve e-learning on AtoZ, run on a
day where a trainer walks the new hire through app install, website access and
the procedures on the page. Afterwards the trainee may stay or leave; leaving is
PERMITTED but affects pay for that date, so it has to be recorded and dispatch
has to know.

Six columns, two groups:

ATTESTATION (permanent) — ore_completed_at, ore_certificate_uploaded_by.
Retention for the certificate FILE is 48h because it carries the trainee's name
and an Amazon training id. If the file were the completion signal, the signal
would evaporate on day three, so the durable record is that ORE was completed
and who uploaded proof.

FILE POINTER (transient) — ore_certificate_key, ore_certificate_expires_at.
Nulled by the nightly sweep once the S3 object is deleted. A NULL key with a
non-null ore_completed_at means "certificate expired", which is a different
answer to a manager than "never uploaded".

DEPARTURE — left_early, left_early_at. Deliberately NOT fed to the scorecard and
NOT counted across the programme (ADR-281 D5): a tally is a judgement waiting
for a threshold, and this is a permitted choice.

No backfill. Existing records are phases 1-6 and were never ORE days; NULL is
the correct value for all of them, and left_early defaults false.

Revision ID: ec6569da03b4
Revises: f2b59de3fd4a
Create Date: 2026-08-20
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "ec6569da03b4"
down_revision = "f2b59de3fd4a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "training_records",
        sa.Column("ore_completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "training_records",
        sa.Column(
            "ore_certificate_uploaded_by",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_training_records_ore_uploaded_by",
        "training_records",
        "employees",
        ["ore_certificate_uploaded_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "training_records",
        sa.Column("ore_certificate_key", sa.String(length=300), nullable=True),
    )
    op.add_column(
        "training_records",
        sa.Column(
            "ore_certificate_expires_at", sa.DateTime(timezone=True), nullable=True
        ),
    )
    op.add_column(
        "training_records",
        sa.Column(
            "left_early", sa.Boolean(), nullable=False, server_default="false"
        ),
    )
    op.add_column(
        "training_records",
        sa.Column("left_early_at", sa.DateTime(timezone=True), nullable=True),
    )

    # The sweep queries "certificates past their expiry that still have a key".
    # Without this it is a sequential scan over every training record ever
    # written, nightly, to find at most a day's worth of rows.
    op.create_index(
        "ix_training_records_ore_expiry",
        "training_records",
        ["ore_certificate_expires_at"],
        postgresql_where=sa.text("ore_certificate_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_training_records_ore_expiry", table_name="training_records")
    op.drop_column("training_records", "left_early_at")
    op.drop_column("training_records", "left_early")
    op.drop_column("training_records", "ore_certificate_expires_at")
    op.drop_column("training_records", "ore_certificate_key")
    op.drop_constraint(
        "fk_training_records_ore_uploaded_by", "training_records", type_="foreignkey"
    )
    op.drop_column("training_records", "ore_certificate_uploaded_by")
    op.drop_column("training_records", "ore_completed_at")

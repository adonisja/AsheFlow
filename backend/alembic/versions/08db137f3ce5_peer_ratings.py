"""peer ratings: walker_ratings driver/walker → rater/ratee, drop present

Revision ID: 08db137f3ce5
Revises: 9b485b12c418
Create Date: 2026-07-13

ADR-201: generalize the driver→walker rating into a peer rating. Rename
driver_id→rater_id, walker_id→ratee_id; drop `present` (roll call owns
attendance now); make stars NOT NULL. No-show rows (present=false) are deleted
first — a no-show is not a rating. Old present=true rows survive as peer ratings
(rater=driver, ratee=walker).
"""
from alembic import op
import sqlalchemy as sa

revision = "08db137f3ce5"
down_revision = "9b485b12c418"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Remove no-show rows and any (defensive) null-star rows — not ratings.
    op.execute("DELETE FROM walker_ratings WHERE present = false OR stars IS NULL")

    # 2. Swap the unique constraint (old name → new columns).
    op.drop_constraint("uq_walker_ratings_driver_walker_date", "walker_ratings", type_="unique")

    # 3. Rename the FK columns to peer semantics.
    op.alter_column("walker_ratings", "driver_id", new_column_name="rater_id")
    op.alter_column("walker_ratings", "walker_id", new_column_name="ratee_id")

    # 4. Drop the attendance flag (roll call owns it) and tighten stars.
    op.drop_column("walker_ratings", "present")
    op.alter_column("walker_ratings", "stars", existing_type=sa.Integer(), nullable=False)

    op.create_unique_constraint(
        "uq_walker_ratings_rater_ratee_date", "walker_ratings", ["rater_id", "ratee_id", "date"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_walker_ratings_rater_ratee_date", "walker_ratings", type_="unique")
    op.alter_column("walker_ratings", "stars", existing_type=sa.Integer(), nullable=True)
    op.add_column("walker_ratings", sa.Column("present", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.alter_column("walker_ratings", "ratee_id", new_column_name="walker_id")
    op.alter_column("walker_ratings", "rater_id", new_column_name="driver_id")
    op.create_unique_constraint(
        "uq_walker_ratings_driver_walker_date", "walker_ratings", ["driver_id", "walker_id", "date"],
    )

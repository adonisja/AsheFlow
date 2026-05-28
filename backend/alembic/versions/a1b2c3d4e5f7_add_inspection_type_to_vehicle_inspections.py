"""add inspection_type to vehicle_inspections

Revision ID: a1b2c3d4e5f7
Revises: f4e891bc2d10
Create Date: 2026-05-01 00:00:00.000000

Adds inspection_type column ("pre_trip" | "eod") and relaxes the unique
constraint from (driver_id, date) to (driver_id, date, inspection_type) so
that each driver can submit one pre-trip and one EOD inspection per day.
"""
from alembic import op
import sqlalchemy as sa

revision = 'a1b2c3d4e5f7'
down_revision = 'f4e891bc2d10'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add the new column with a server default so existing rows get "pre_trip"
    op.add_column(
        'vehicle_inspections',
        sa.Column('inspection_type', sa.String(20), nullable=False, server_default='pre_trip'),
    )

    # 2. Drop the old unique constraint if it exists (may not exist on fresh databases)
    op.execute("""
        DO $$ BEGIN
            ALTER TABLE vehicle_inspections DROP CONSTRAINT IF EXISTS uq_vehicle_inspections_driver_date;
        END $$;
    """)

    # 3. Create the new broader unique constraint
    op.create_unique_constraint(
        'uq_vehicle_inspections_driver_date_type',
        'vehicle_inspections',
        ['driver_id', 'date', 'inspection_type'],
    )


def downgrade() -> None:
    op.drop_constraint('uq_vehicle_inspections_driver_date_type', 'vehicle_inspections', type_='unique')
    op.create_unique_constraint(
        'uq_vehicle_inspections_driver_date',
        'vehicle_inspections',
        ['driver_id', 'date'],
    )
    op.drop_column('vehicle_inspections', 'inspection_type')

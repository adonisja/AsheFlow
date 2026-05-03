"""add shift_ops tables: crew_compliance, driver_check_ins, rts_reports, station_handoffs

Revision ID: a5b6c7d8e9f0
Revises: f4a5b6c7d8e9
Create Date: 2026-05-01 00:00:05.000000

Four mid-shift tracking tables:
  - crew_compliance: AP arrival compliance per crew member per shift
  - driver_check_ins: 4 structured mid-shift progress check-ins per driver
  - rts_reports: field RTS summary + dispatch approval gate (driver gated until approved)
  - station_handoffs: physical totes/RTS return confirmation at the station (closes the loop)
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'a5b6c7d8e9f0'
down_revision = 'f4a5b6c7d8e9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # crew_compliance
    op.create_table(
        'crew_compliance',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('driver_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('employee_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('arrival_time', sa.Time(), nullable=True),
        sa.Column('uniform_pass', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('cart_cover_pass', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('submitted_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['driver_id'], ['employees.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('driver_id', 'employee_id', 'date', name='uq_crew_compliance_driver_emp_date'),
    )
    op.create_index('ix_crew_compliance_driver_id', 'crew_compliance', ['driver_id'])
    op.create_index('ix_crew_compliance_employee_id', 'crew_compliance', ['employee_id'])
    op.create_index('ix_crew_compliance_date', 'crew_compliance', ['date'])

    # driver_check_ins
    op.create_table(
        'driver_check_ins',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('driver_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('check_in_number', sa.Integer(), nullable=False),
        sa.Column('routes_remaining', sa.Integer(), nullable=False),
        sa.Column('help_requested', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('working_crew_count', sa.Integer(), nullable=False),
        sa.Column('ncns_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('submitted_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.CheckConstraint('check_in_number BETWEEN 1 AND 4', name='ck_driver_check_ins_number'),
        sa.ForeignKeyConstraint(['driver_id'], ['employees.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('driver_id', 'date', 'check_in_number', name='uq_driver_check_ins_driver_date_num'),
    )
    op.create_index('ix_driver_check_ins_driver_id', 'driver_check_ins', ['driver_id'])
    op.create_index('ix_driver_check_ins_date', 'driver_check_ins', ['date'])

    # rts_reports (field submission — dispatch approval gate)
    op.create_table(
        'rts_reports',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('driver_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('crew_confirmed', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('rts_packages', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('total_rts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('dispatch_notes', sa.Text(), nullable=True),
        sa.Column('reviewed_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('submitted_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['driver_id'], ['employees.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['reviewed_by'], ['employees.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('driver_id', 'date', name='uq_rts_reports_driver_date'),
    )
    op.create_index('ix_rts_reports_driver_id', 'rts_reports', ['driver_id'])
    op.create_index('ix_rts_reports_date', 'rts_reports', ['date'])

    # station_handoffs (physical return confirmation at the station)
    op.create_table(
        'station_handoffs',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('driver_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('totes_returned', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('rts_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('submitted_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['driver_id'], ['employees.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('driver_id', 'date', name='uq_station_handoffs_driver_date'),
    )
    op.create_index('ix_station_handoffs_driver_id', 'station_handoffs', ['driver_id'])
    op.create_index('ix_station_handoffs_date', 'station_handoffs', ['date'])


def downgrade() -> None:
    op.drop_index('ix_station_handoffs_date', table_name='station_handoffs')
    op.drop_index('ix_station_handoffs_driver_id', table_name='station_handoffs')
    op.drop_table('station_handoffs')

    op.drop_index('ix_rts_reports_date', table_name='rts_reports')
    op.drop_index('ix_rts_reports_driver_id', table_name='rts_reports')
    op.drop_table('rts_reports')

    op.drop_index('ix_driver_check_ins_date', table_name='driver_check_ins')
    op.drop_index('ix_driver_check_ins_driver_id', table_name='driver_check_ins')
    op.drop_table('driver_check_ins')

    op.drop_index('ix_crew_compliance_date', table_name='crew_compliance')
    op.drop_index('ix_crew_compliance_employee_id', table_name='crew_compliance')
    op.drop_index('ix_crew_compliance_driver_id', table_name='crew_compliance')
    op.drop_table('crew_compliance')

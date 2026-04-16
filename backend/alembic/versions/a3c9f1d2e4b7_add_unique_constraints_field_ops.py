"""add_unique_constraints_field_ops

Revision ID: a3c9f1d2e4b7
Revises: 6f6843738bc0
Create Date: 2026-04-11 02:00:00.000000

One record per employee per day for check_ins and departures;
one record per driver per day for fuel_mileage_logs and vehicle_inspections.
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'a3c9f1d2e4b7'
down_revision: Union[str, Sequence[str], None] = '6f6843738bc0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_check_ins_employee_date",
        "check_ins",
        ["employee_id", "date"],
    )
    op.create_unique_constraint(
        "uq_departures_employee_date",
        "departures",
        ["employee_id", "date"],
    )
    op.create_unique_constraint(
        "uq_fuel_mileage_logs_driver_date",
        "fuel_mileage_logs",
        ["driver_id", "date"],
    )
    op.create_unique_constraint(
        "uq_vehicle_inspections_driver_date",
        "vehicle_inspections",
        ["driver_id", "date"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_vehicle_inspections_driver_date", "vehicle_inspections")
    op.drop_constraint("uq_fuel_mileage_logs_driver_date",   "fuel_mileage_logs")
    op.drop_constraint("uq_departures_employee_date",        "departures")
    op.drop_constraint("uq_check_ins_employee_date",         "check_ins")

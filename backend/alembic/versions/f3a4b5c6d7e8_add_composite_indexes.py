"""add composite indexes for high-frequency company+date queries

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-06-01

Adds composite indexes to tables most frequently queried by (company_id, date)
or (company_id, trainee_id). Individual company_id indexes exist but the
composite allows the DB to satisfy these filters in a single index scan.
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'f3a4b5c6d7e8'
down_revision = 'e2f3a4b5c6d7'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "ix_time_off_requests_company_date",
        "time_off_requests",
        ["company_id", "date"],
    )
    op.create_index(
        "ix_dispatch_confirmations_company_date",
        "dispatch_confirmations",
        ["company_id", "date"],
    )
    op.create_index(
        "ix_training_records_company_record_date",
        "training_records",
        ["company_id", "record_date"],
    )
    op.create_index(
        "ix_walker_routes_company_route_date",
        "walker_routes",
        ["company_id", "route_date"],
    )
    op.create_index(
        "ix_graduation_quizzes_company_trainee",
        "graduation_quizzes",
        ["company_id", "trainee_id"],
    )


def downgrade():
    op.drop_index("ix_graduation_quizzes_company_trainee", table_name="graduation_quizzes")
    op.drop_index("ix_walker_routes_company_route_date", table_name="walker_routes")
    op.drop_index("ix_training_records_company_record_date", table_name="training_records")
    op.drop_index("ix_dispatch_confirmations_company_date", table_name="dispatch_confirmations")
    op.drop_index("ix_time_off_requests_company_date", table_name="time_off_requests")

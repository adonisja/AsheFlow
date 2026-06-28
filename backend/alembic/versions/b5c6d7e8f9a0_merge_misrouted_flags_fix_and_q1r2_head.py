"""merge misrouted_package_flags fix with q1r2s3t4u5v6 head

Revision ID: b5c6d7e8f9a0
Revises: q1r2s3t4u5v6, a4b5c6d7e8f9
Create Date: 2026-06-28

Merge-only migration — no DDL. Collapses the two heads produced when
a4b5c6d7e8f9 (misrouted_package_flags column fix + normalised_addresses)
branched from z3a4b5c6d7e8 independently of the existing q1r2s3t4u5v6 head.
"""
from alembic import op

revision = 'b5c6d7e8f9a0'
down_revision = ('q1r2s3t4u5v6', 'a4b5c6d7e8f9')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

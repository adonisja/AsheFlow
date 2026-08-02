"""Add injury_status to employees and wave_number to routes.

injury_status (injured|disabled|null) hard-blocks heavy route assignment.
wave_number (default 1) tracks first-wave vs second-wave assignments for
analytics and future auto-assignment model (ADR-139).

Revision ID: f8g9h0i1j2k3
Revises: 46336672ab3e
Create Date: 2026-06-25
"""
from alembic import op
import sqlalchemy as sa

# Loaded by path: alembic executes revision files standalone, so a package
# import ("alembic.shared...") resolves to the INSTALLED alembic library, not
# this directory. Load the helper from disk instead.
import importlib.util as _ilu, pathlib as _pl
_spec = _ilu.spec_from_file_location(
    "_routes_ddl", _pl.Path(__file__).resolve().parent.parent / "_shared" / "routes_ddl.py")
_routes_ddl = _ilu.module_from_spec(_spec); _spec.loader.exec_module(_routes_ddl)
create_routes_table = _routes_ddl.create_routes_table
routes_exists = _routes_ddl.routes_exists

revision = 'f8g9h0i1j2k3'
down_revision = '46336672ab3e'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('employees', sa.Column('injury_status',       sa.String(20),                 nullable=True))
    op.add_column('employees', sa.Column('injury_status_since', sa.DateTime(timezone=True),    nullable=True))

    # `routes` is created by j7e8f9a0b1c2, seven revisions LATER. On a fresh
    # database it does not exist yet, so this ALTER used to die with
    # UndefinedTable and no from-scratch provision could ever complete.
    # Existing databases already have the table and this is a no-op.
    create_routes_table()
    op.add_column('routes', sa.Column('wave_number', sa.Integer(), server_default='1', nullable=False))


def downgrade() -> None:
    if routes_exists():
        op.drop_column('routes', 'wave_number')
    op.drop_column('employees', 'injury_status_since')
    op.drop_column('employees', 'injury_status')

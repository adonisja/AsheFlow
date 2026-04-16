"""add_role_check_constraint_employees

Revision ID: b1d4e7f3a2c8
Revises: a3c9f1d2e4b7
Create Date: 2026-04-11 03:00:00.000000

Adds a DB-level CHECK constraint on employees.role so only the seven
known role values can be inserted or updated.
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'b1d4e7f3a2c8'
down_revision: Union[str, Sequence[str], None] = 'a3c9f1d2e4b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

VALID_ROLES = ("driver", "walker", "trainer", "trainee", "dispatch", "management", "admin")


def upgrade() -> None:
    role_list = ", ".join(f"'{r}'" for r in VALID_ROLES)
    op.execute(
        f"ALTER TABLE employees ADD CONSTRAINT ck_employees_role_valid "
        f"CHECK (role IN ({role_list}))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE employees DROP CONSTRAINT ck_employees_role_valid")

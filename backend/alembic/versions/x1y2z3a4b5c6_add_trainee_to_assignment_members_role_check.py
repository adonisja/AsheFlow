"""add trainee to assignment_members role check constraint

Revision ID: x1y2z3a4b5c6
Revises: w0x1y2z3a4b5
Create Date: 2026-05-29

The dispatch algorithm assigns trainees to trucks alongside their trainers.
The original check constraint only permitted driver/trainer/walker, causing
a CheckViolation when dispatch tried to insert trainee assignment_members rows.
"""

from alembic import op

revision = 'x1y2z3a4b5c6'
down_revision = 'w0x1y2z3a4b5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE assignment_members DROP CONSTRAINT IF EXISTS ck_assignment_members_role")
    op.execute(
        "ALTER TABLE assignment_members ADD CONSTRAINT ck_assignment_members_role "
        "CHECK (role IN ('driver', 'trainer', 'walker', 'trainee'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE assignment_members DROP CONSTRAINT IF EXISTS ck_assignment_members_role")
    op.execute(
        "ALTER TABLE assignment_members ADD CONSTRAINT ck_assignment_members_role "
        "CHECK (role IN ('driver', 'trainer', 'walker'))"
    )

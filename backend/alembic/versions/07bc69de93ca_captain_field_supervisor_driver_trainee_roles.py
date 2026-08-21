"""ADR-256/264: captain, field_supervisor, driver_trainee roles

Rewrites the two role CHECK constraints and adds the one-captain-per-truck index.

Both new-role ADRs land in ONE migration deliberately. ADR-256 (captain,
field_supervisor) and ADR-264 (driver_trainee) each drop and recreate the same two
named constraints; sequencing them separately means rewriting
`ck_employees_role_valid` and `ck_assignment_members_role` twice in a week.

Scope note: `driver_trainee` is added here as an ENUM VALUE ONLY. Its training
behaviour — phase compression, observation-last, promotion to driver, dispatch
pairing — belongs to ADR-264 and is not implemented here.

Two role namespaces, both touched:
  - `employees.role`         — job title      (+captain, +field_supervisor, +driver_trainee)
  - `assignment_members.role`— per-day slot   (+captain, +driver_trainee)
`field_supervisor` is NOT a truck slot: a field supervisor oversees the road, they
do not fill a seat on a specific truck's crew.

Revision ID: 07bc69de93ca
Revises: d5469c0fe260
Create Date: 2026-08-07
"""
from alembic import op

revision = "07bc69de93ca"
down_revision = "d5469c0fe260"
branch_labels = None
depends_on = None


# Kept literal rather than imported from app.models. A migration must describe the
# schema at ITS point in history — importing the live tuple would silently rewrite
# this migration's meaning the next time a role is added.
_EMPLOYEE_ROLES_NEW = (
    "driver", "walker", "trainer", "trainee", "dispatch", "management", "admin",
    "captain", "field_supervisor", "driver_trainee",
)
_EMPLOYEE_ROLES_OLD = (
    "driver", "walker", "trainer", "trainee", "dispatch", "management", "admin",
)

_MEMBER_ROLES_NEW = ("driver", "trainer", "trainee", "walker", "captain", "driver_trainee")
_MEMBER_ROLES_OLD = ("driver", "trainer", "trainee", "walker")


def _in_list(values) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    # ── employees.role ────────────────────────────────────────────────────────
    op.drop_constraint("ck_employees_role_valid", "employees", type_="check")
    op.create_check_constraint(
        "ck_employees_role_valid",
        "employees",
        f"role IN ({_in_list(_EMPLOYEE_ROLES_NEW)})",
    )

    # ── assignment_members.role (the per-day slot namespace) ──────────────────
    op.drop_constraint("ck_assignment_members_role", "assignment_members", type_="check")
    op.create_check_constraint(
        "ck_assignment_members_role",
        "assignment_members",
        f"role IN ({_in_list(_MEMBER_ROLES_NEW)})",
    )

    # ── ADR-256 D2: exactly one captain per truck ─────────────────────────────
    # Partial unique index, not a service check: two dispatchers assigning
    # concurrently would both read "no captain", both insert, and both succeed.
    # IF NOT EXISTS so a re-run against a partially-applied DB is safe.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_assignment_members_one_captain "
        "ON assignment_members (assignment_id) WHERE role = 'captain'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_assignment_members_one_captain")

    # Rows using the new values must go before the narrower constraint is restored,
    # or the CHECK fails to validate against existing data.
    op.execute("DELETE FROM assignment_members WHERE role IN ('captain', 'driver_trainee')")
    op.drop_constraint("ck_assignment_members_role", "assignment_members", type_="check")
    op.create_check_constraint(
        "ck_assignment_members_role",
        "assignment_members",
        f"role IN ({_in_list(_MEMBER_ROLES_OLD)})",
    )

    # Employees are NOT deleted — a person is not disposable schema. Park them on
    # a role the old constraint accepts and let an operator re-file them.
    op.execute(
        "UPDATE employees SET role = 'walker' "
        "WHERE role IN ('captain', 'field_supervisor', 'driver_trainee')"
    )
    op.drop_constraint("ck_employees_role_valid", "employees", type_="check")
    op.create_check_constraint(
        "ck_employees_role_valid",
        "employees",
        f"role IN ({_in_list(_EMPLOYEE_ROLES_OLD)})",
    )
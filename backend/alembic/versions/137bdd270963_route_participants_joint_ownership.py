"""route_participants: joint route ownership (ADR-212)

Revision ID: 137bdd270963
Revises: a367f2386766
Create Date: 2026-07-20

ADR-212: replace the single-owner Route.assigned_to / assigned_to_name /
paired_trainee_id model with a RouteParticipant join table (role: executor |
supervisor). Exactly one executor per route (partial unique index); zero-or-more
supervisors. Backfill from the old columns, then drop them.

RTS note: RTSPackage.assigned_to is a DIFFERENT column on a different table and is
untouched by this migration — only routes.* columns are dropped.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "137bdd270963"
down_revision = "a367f2386766"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create the participant table.
    op.create_table(
        "route_participants",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", UUID(as_uuid=True), nullable=False),
        sa.Column("route_id", UUID(as_uuid=True), nullable=False),
        sa.Column("employee_id", UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["route_id"], ["routes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("route_id", "employee_id", name="uq_route_participant_route_employee"),
    )
    op.create_index("ix_route_participants_company_id", "route_participants", ["company_id"])
    op.create_index("ix_route_participants_route_id", "route_participants", ["route_id"])
    # Exactly one executor per route.
    op.create_index(
        "uq_route_participant_one_executor",
        "route_participants",
        ["route_id"],
        unique=True,
        postgresql_where=sa.text("role = 'executor'"),
    )

    # 2. Backfill from the old single-owner columns.
    #    - executor  = every route with an assigned_to
    #    - supervisor = the trainer paired to a route's trainee, resolved via
    #      AssignmentMember.paired_trainer_id for that trainee on the route's truck.
    conn = op.get_bind()

    # Executor rows: one per assigned route.
    conn.execute(sa.text("""
        INSERT INTO route_participants (id, company_id, route_id, employee_id, role)
        SELECT gen_random_uuid(), r.company_id, r.id, r.assigned_to, 'executor'
        FROM routes r
        WHERE r.assigned_to IS NOT NULL
    """))

    # Supervisor rows: for routes carrying a paired trainee, find the trainer the
    # trainee is paired to (AssignmentMember on the same truck assignment).
    conn.execute(sa.text("""
        INSERT INTO route_participants (id, company_id, route_id, employee_id, role)
        SELECT gen_random_uuid(), r.company_id, r.id, am.paired_trainer_id, 'supervisor'
        FROM routes r
        JOIN assignment_members am
          ON am.assignment_id = r.truck_assignment_id
         AND am.employee_id   = r.paired_trainee_id
         AND am.company_id    = r.company_id
        WHERE r.paired_trainee_id IS NOT NULL
          AND am.paired_trainer_id IS NOT NULL
    """))

    # 3. Drop the old single-owner columns from routes.
    op.drop_column("routes", "assigned_to")
    op.drop_column("routes", "assigned_to_name")
    op.drop_column("routes", "paired_trainee_id")


def downgrade() -> None:
    # Re-add the columns (nullable — data not fully recoverable).
    op.add_column("routes", sa.Column("assigned_to", UUID(as_uuid=True), nullable=True))
    op.add_column("routes", sa.Column("assigned_to_name", sa.String(length=100), nullable=True))
    op.add_column("routes", sa.Column("paired_trainee_id", UUID(as_uuid=True), nullable=True))
    # Best-effort restore of assigned_to from the executor participant.
    conn = op.get_bind()
    conn.execute(sa.text("""
        UPDATE routes SET assigned_to = rp.employee_id
        FROM route_participants rp
        WHERE rp.route_id = routes.id AND rp.role = 'executor'
    """))
    op.create_foreign_key(
        "routes_assigned_to_fkey", "routes", "employees",
        ["assigned_to"], ["id"], ondelete="SET NULL",
    )
    op.create_index("ix_routes_assigned_to", "routes", ["assigned_to"])
    op.drop_index("uq_route_participant_one_executor", table_name="route_participants")
    op.drop_index("ix_route_participants_route_id", table_name="route_participants")
    op.drop_index("ix_route_participants_company_id", table_name="route_participants")
    op.drop_table("route_participants")

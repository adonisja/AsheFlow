"""Shared DDL for the `routes` table.

`routes` is created by j7e8f9a0b1c2, which sits at position 89 in the chain —
AFTER two migrations that depend on it:

    pos 82  f8g9h0i1j2k3  ALTER TABLE routes ADD wave_number
    pos 83  m6n7o8p9q0r1  CREATE TABLE ... FOREIGN KEY -> routes.id

On staging and prod that never mattered: `routes` predates both, so the ALTER
found its target and the FKs resolved. Every from-scratch provision died at
position 82 with `UndefinedTable: relation "routes" does not exist`.

Reordering the revisions was rejected — they have shipped, and moving them
would break the already-migrated databases in order to fix the empty one.
Instead the DDL lives here and is applied by whichever migration reaches it
first; the later ones no-op when the table already exists. Both a fresh
database and an existing one converge on the same schema.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, UUID


def routes_exists() -> bool:
    return sa.inspect(op.get_bind()).has_table('routes')


def create_routes_table() -> None:
    """Create `routes` if it is not already there. Safe to call more than once."""
    if routes_exists():
        return

    op.create_table(
        'routes',
        sa.Column('id',                    UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('company_id',            UUID(as_uuid=True), nullable=False),
        sa.Column('truck_assignment_id',   UUID(as_uuid=True), sa.ForeignKey('truck_assignments.id', ondelete='CASCADE'), nullable=False),
        sa.Column('route_date',            sa.Date(), nullable=False),
        sa.Column('route_number',          sa.Integer(), nullable=False),

        # Geographic identity — persisted (was discarded in WalkerTrip)
        sa.Column('block_keys',            ARRAY(sa.Text()), nullable=False, server_default='{}'),

        # Tote and package lists
        sa.Column('tote_ids',              ARRAY(sa.Text()), nullable=False, server_default='{}'),
        sa.Column('tba_numbers',           ARRAY(sa.Text()), nullable=False, server_default='{}'),
        sa.Column('tag_numbers',           ARRAY(sa.Text()), nullable=False, server_default='{}'),

        # Capacity — half-slot integer arithmetic (×2 scale)
        sa.Column('slot_cost',             sa.Integer(), nullable=False, default=0),
        sa.Column('capacity_limit',        sa.Integer(), nullable=False),        # base, set at sort time
        sa.Column('capacity_limit_paired', sa.Integer(), nullable=True),         # set at arrival if pair confirmed

        # Effort classification
        sa.Column('effort_class',          sa.String(20), nullable=False, server_default='standard'),  # easy|standard|heavy
        sa.Column('workload_source',       sa.String(20), nullable=False, server_default='default'),   # profile|flag|default

        # Assignment — nullable until wave distribution
        sa.Column('assigned_to',           UUID(as_uuid=True), sa.ForeignKey('employees.id', ondelete='SET NULL'), nullable=True),
        sa.Column('assigned_to_name',      sa.String(100), nullable=True),

        # Trainer+trainee pairing
        sa.Column('paired_trainee_id',     UUID(as_uuid=True), sa.ForeignKey('employees.id', ondelete='SET NULL'), nullable=True),
        sa.Column('trainee_phase',         sa.Integer(), nullable=True),          # 1-5
        sa.Column('phase4_solo_opted_in',  sa.Boolean(), nullable=False, server_default='false'),

        # Status lifecycle
        # NOTE: wave_number is deliberately NOT here. f8g9h0i1j2k3 adds it by
        # ALTER immediately after calling this helper, so declaring it here too
        # would raise DuplicateColumn on a fresh database.
        sa.Column('status',                sa.String(20), nullable=False, server_default='unassigned'),  # unassigned|assigned|in_progress|completed
        sa.Column('departed_at',           sa.DateTime(timezone=True), nullable=True),
        sa.Column('returned_at',           sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at',            sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )



"""ADR-256: split the Discord trainer and captain roles

`discord_role_captain` has always held the guild role granted on TRAINER promotion —
`bot/cogs/dispatch.py::sync_trainer_role` docstring: "Grant or revoke the Captain
(trainer) Discord role". In Discord, "Captain" was the label for trainers.

ADR-256 D5 makes captain and trainer different levels of authority, so they need
different guild roles. Reusing `discord_role_captain` for the new employee-captain
would give every trainer route-lead channel access.

THE VALUE MOVES, IT IS NOT REUSED:

    discord_role_captain (old, = the trainer role)  ->  discord_role_trainer
    discord_role_captain                            ->  NULL, awaiting the new role

Nulling it is deliberate. A null reads as "not configured yet" and `sync_role`
already logs and no-ops on that, so no captain gets a wrong role in the window
between this migration and an admin creating the new guild role. Leaving the old id
in place would silently grant trainers' role to captains — the exact failure this
migration exists to prevent.

Manual guild work this expects, in order:
  1. rename the existing Discord role "Captain" -> "Trainer"   (ids are stable, so
     `discord_role_trainer` keeps pointing at it)
  2. create a new "Captain" role
  3. set discord_role_captain to the new role id in company settings

Revision ID: ff90779895f6
Revises: de0cd30c177d
Create Date: 2026-08-08
"""
from alembic import op
import sqlalchemy as sa

revision = "ff90779895f6"
down_revision = "de0cd30c177d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("companies", sa.Column("discord_role_trainer", sa.BigInteger(), nullable=True))

    # Move, do not copy: the old column held the trainer role all along.
    op.execute("UPDATE companies SET discord_role_trainer = discord_role_captain")
    op.execute("UPDATE companies SET discord_role_captain = NULL")


def downgrade() -> None:
    # Put the trainer role id back where it was, for a chain that predates the split.
    op.execute(
        "UPDATE companies SET discord_role_captain = discord_role_trainer "
        "WHERE discord_role_trainer IS NOT NULL"
    )
    op.drop_column("companies", "discord_role_trainer")

"""An acknowledgement outlives the notification it refers to (ADR-494 D8 finding)

Revision ID: 045d62ef7d08
Revises: 2ee24680c67f
Create Date: 2026-10-11

THE DEFECT THIS FIXES
=====================
`notification_acknowledgements.notification_id` was the PRIMARY KEY with
`ON DELETE CASCADE`. `prune_notifications` (tasks/cleanup.py) deletes
notifications after `notification_retention_days` -- **3** -- and immediately
once `expires_at` passes. So every acknowledgement was destroyed three days
after it was made.

ADR-494 D7 exists because *"an employee who confirmed the hours and one who
skipped have told you different things, and a dispute six weeks later turns on
which it was."* A three-day record cannot serve that, and the loss would have
been silent: the rows simply would not be there when someone looked.

WHAT CHANGES
============
  id                 NEW surrogate PK (the old PK could not be nullable)
  notification_id    PK -> nullable UNIQUE, CASCADE -> SET NULL
  notification_type  NEW, NOT NULL -- snapshot
  message_snapshot   NEW, NOT NULL -- snapshot

The two snapshots are the point. After the notification is pruned, its type and
message are not recoverable from anywhere, and "they confirmed something" is not
evidence of anything.

`notification_id` stays UNIQUE so one acknowledgement per notification still
holds -- that was the original PK's real job, and a unique constraint does it
without tying this row's lifetime to the notification's.

SAFE ON A POPULATED TABLE
=========================
It is empty in every environment today (the endpoint shipped in this same
session and no gate has been answered), but this is written not to depend on
that: the new NOT NULL columns are added with a server_default, backfilled,
then the default is dropped. A row that predates the snapshots gets
'(unknown)' rather than blocking the migration.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "045d62ef7d08"
down_revision = "2ee24680c67f"
branch_labels = None
depends_on = None


def upgrade():
    # 1. The surrogate key. Added nullable, filled, then made the PK -- a
    #    column cannot become a primary key while any row has NULL in it.
    op.add_column(
        "notification_acknowledgements",
        sa.Column("id", UUID(as_uuid=True), nullable=True),
    )
    op.execute("UPDATE notification_acknowledgements SET id = gen_random_uuid() WHERE id IS NULL")
    op.alter_column("notification_acknowledgements", "id", nullable=False)

    # 2. The snapshots, with a server_default so NOT NULL is satisfiable on an
    #    existing row, then the default removed so future inserts must supply
    #    a real value rather than silently recording '(unknown)'.
    op.add_column(
        "notification_acknowledgements",
        sa.Column("notification_type", sa.String(64), nullable=False,
                  server_default="(unknown)"),
    )
    op.add_column(
        "notification_acknowledgements",
        sa.Column("message_snapshot", sa.Text(), nullable=False,
                  server_default="(unknown)"),
    )
    op.alter_column("notification_acknowledgements", "notification_type",
                    server_default=None)
    op.alter_column("notification_acknowledgements", "message_snapshot",
                    server_default=None)

    # 3. Swap the primary key. Dropping the old PK also drops the FK that
    #    depended on it, so the FK is recreated explicitly below.
    op.drop_constraint("notification_acknowledgements_notification_id_fkey",
                       "notification_acknowledgements", type_="foreignkey")
    op.drop_constraint("notification_acknowledgements_pkey",
                       "notification_acknowledgements", type_="primary")
    op.create_primary_key("notification_acknowledgements_pkey",
                          "notification_acknowledgements", ["id"])

    # 4. notification_id becomes nullable + unique, with SET NULL. This is the
    #    whole fix: the prune nulls the reference instead of deleting the row.
    op.alter_column("notification_acknowledgements", "notification_id",
                    existing_type=UUID(as_uuid=True), nullable=True)
    op.create_unique_constraint("uq_ack_notification",
                                "notification_acknowledgements", ["notification_id"])
    op.create_foreign_key(
        "notification_acknowledgements_notification_id_fkey",
        "notification_acknowledgements", "notifications",
        ["notification_id"], ["id"], ondelete="SET NULL",
    )


def downgrade():
    # Reversing this DELETES evidence: any acknowledgement whose notification
    # was already pruned has notification_id IS NULL and cannot satisfy the old
    # NOT NULL primary key. Those rows are removed, which is data loss and the
    # reason this downgrade is here for completeness rather than for use.
    op.drop_constraint("notification_acknowledgements_notification_id_fkey",
                       "notification_acknowledgements", type_="foreignkey")
    op.drop_constraint("uq_ack_notification",
                       "notification_acknowledgements", type_="unique")
    op.execute("DELETE FROM notification_acknowledgements WHERE notification_id IS NULL")
    op.alter_column("notification_acknowledgements", "notification_id",
                    existing_type=UUID(as_uuid=True), nullable=False)
    op.drop_constraint("notification_acknowledgements_pkey",
                       "notification_acknowledgements", type_="primary")
    op.create_primary_key("notification_acknowledgements_pkey",
                          "notification_acknowledgements", ["notification_id"])
    op.create_foreign_key(
        "notification_acknowledgements_notification_id_fkey",
        "notification_acknowledgements", "notifications",
        ["notification_id"], ["id"], ondelete="CASCADE",
    )
    op.drop_column("notification_acknowledgements", "message_snapshot")
    op.drop_column("notification_acknowledgements", "notification_type")
    op.drop_column("notification_acknowledgements", "id")

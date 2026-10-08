"""ADR-487 D3: notification delivery state

Four nullable columns recording what happened to the SENDS a notification row
implied. The row itself was always the durable record; nothing tracked whether
the push, the Discord post or the held release actually happened.

  dispatched_at       the after-commit hook enqueued delivery. NULL past the
                      sweep window means the enqueue was LOST — a broker restart
                      or a worker killed between commit and .delay().
  release_at          a held push (quiet hours, D5). A row survives a broker
                      restart; a Celery countdown= does not.
  delivery_failed_at  a TERMINAL failure — retries exhausted, or a response
                      that must not be retried (403 revoked, 404 gone).
  delivery_error      a short classification. Never a raw exception string
                      (Dimension 6).

Indexed on dispatched_at and release_at because both are swept: "rows enqueued
nowhere" and "rows whose hold has expired" are the two recurring queries.

Revision ID: c717f49fbae6
Revises: 5be4ac675afb
Create Date: 2026-10-05
"""
from alembic import op
import sqlalchemy as sa

revision = "c717f49fbae6"
down_revision = "5be4ac675afb"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # IF NOT EXISTS on each: this chain is applied to databases built from
    # different baselines, and a redeploy re-runs it against an already-migrated
    # one (ci.yml's "Re-run is idempotent" step).
    op.execute("ALTER TABLE notifications ADD COLUMN IF NOT EXISTS dispatched_at TIMESTAMPTZ")
    op.execute("ALTER TABLE notifications ADD COLUMN IF NOT EXISTS release_at TIMESTAMPTZ")
    op.execute("ALTER TABLE notifications ADD COLUMN IF NOT EXISTS delivery_failed_at TIMESTAMPTZ")
    op.execute("ALTER TABLE notifications ADD COLUMN IF NOT EXISTS delivery_error VARCHAR(80)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_notifications_dispatched_at "
        "ON notifications (dispatched_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_notifications_release_at "
        "ON notifications (release_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_notifications_release_at")
    op.execute("DROP INDEX IF EXISTS ix_notifications_dispatched_at")
    op.execute("ALTER TABLE notifications DROP COLUMN IF EXISTS delivery_error")
    op.execute("ALTER TABLE notifications DROP COLUMN IF EXISTS delivery_failed_at")
    op.execute("ALTER TABLE notifications DROP COLUMN IF EXISTS release_at")
    op.execute("ALTER TABLE notifications DROP COLUMN IF EXISTS dispatched_at")

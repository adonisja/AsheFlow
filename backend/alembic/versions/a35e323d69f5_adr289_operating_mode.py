"""ADR-289 — operating_mode on company_configs, defaulting to workforce

Revision ID: a35e323d69f5
Revises: b778b371da7f
Create Date: 2026-08-23

One column, but NOT a pure DDL default — this is a data migration.

`server_default="workforce"` is correct for rows created from now on: a new DSP has
no Amazon package feed until someone grants one. Applied blindly to a live table it
would silently DOWNGRADE every existing tenant, gating ~40 endpoints for companies
that are currently running the full package pipeline.

So the column is added WITH the default (so new rows are right) and then every
existing row is set to 'full' (so current tenants keep working). The UPDATE is the
point of this migration; the default is the incidental part.

nullable=False deliberately — see the model comment. A null operating_mode cannot
distinguish "new company, not yet configured" from "config was lost", which is the
ADR-283 failure this column must not reproduce.
"""
from alembic import op
import sqlalchemy as sa

revision = "a35e323d69f5"
# Re-parented onto ADR-295 (b778b371da7f): both were authored against
# 2347526ecd7d in the same session, which left two heads and would have failed
# `alembic upgrade head` on deploy. Neither had been applied anywhere, so
# re-parenting is safe and keeps one linear chain (CLAUDE.md: merge branches).
down_revision = "b778b371da7f"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "company_configs",
        sa.Column(
            "operating_mode",
            sa.String(length=20),
            nullable=False,
            server_default="workforce",
        ),
    )
    # Every company that exists at migration time predates the mode and is running
    # the full pipeline. Without this they would all be gated off on deploy.
    op.execute("UPDATE company_configs SET operating_mode = 'full'")


def downgrade():
    op.drop_column("company_configs", "operating_mode")

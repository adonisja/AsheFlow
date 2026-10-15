"""ADR-509: a contributor row knows its Cognito username and sign-in email.

Revision ID: cd152324408d
Revises: 55aa7a9444d4
"""
from alembic import op
import sqlalchemy as sa

revision = "cd152324408d"
down_revision = "55aa7a9444d4"
branch_labels = None
depends_on = None


def upgrade():
    # Nullable: rows admitted before ADR-509 (by sub only) have neither.
    op.add_column("survey_contributors", sa.Column("cognito_username", sa.String(128), nullable=True))
    op.add_column("survey_contributors", sa.Column("email", sa.String(255), nullable=True))


def downgrade():
    op.drop_column("survey_contributors", "email")
    op.drop_column("survey_contributors", "cognito_username")

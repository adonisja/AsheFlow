"""ADR-468 D1: `registered` becomes a real account_status.

Builds ADR-379 D3, designed 2026-09-05 and never implemented. The column carried
two meanings in one value -- `pending_verification` meant BOTH "invited, no
Cognito account" and "Cognito account created, never signed in", because
complete_registration deliberately leaves the status alone
(registration.py, its own comment).

That ambiguity was not cosmetic. DELETE /companies/{id}/bootstrap guarded on
`!= "pending_verification"` to mean "has completed registration" and therefore
let a REGISTERED owner through -- deleting the Employee row while making no
Cognito call, orphaning a live account with a valid password in the pool.

THE BACKFILL IS THE FIX FOR EXISTING ROWS. It keys on `username`, the same
marker ADR-379 D1 chose for the invite sweep, and deliberately NOT on
`cognito_sub`: complete_registration tolerates a null cognito_sub on a genuinely
registered employee, so cognito_sub can be NULL where username is set.

Self-contained: no import from app.* (tests/test_migrations_are_self_contained).

Revision ID: a0ac4a1bc433
Revises: db8751d428ad
Create Date: 2026-09-28
"""
from alembic import op
import sqlalchemy as sa

revision = "a0ac4a1bc433"
down_revision = "db8751d428ad"
branch_labels = None
depends_on = None

_CK = "ck_employees_account_status_valid"
_OLD = "account_status IN ('pending_verification', 'active', 'deactivated')"
_NEW = "account_status IN ('pending_verification', 'registered', 'active', 'deactivated')"


def upgrade() -> None:
    # Widen the constraint BEFORE the backfill, or the UPDATE violates it.
    op.drop_constraint(_CK, "employees", type_="check")
    op.create_check_constraint(_CK, "employees", _NEW)

    # Rows already in the state the new value names. Reported, because a silent
    # backfill on a lifecycle column is not something to discover later.
    conn = op.get_bind()
    moved = conn.execute(sa.text(
        "UPDATE employees SET account_status = 'registered' "
        " WHERE account_status = 'pending_verification' "
        "   AND username IS NOT NULL"
    )).rowcount
    print(f"ADR-468: moved {moved} registered-but-not-signed-in row(s)")


def downgrade() -> None:
    """Folds `registered` back into `pending_verification`.

    Lossy by nature -- that is the ambiguity this migration removed, so a
    downgrade necessarily restores it. Said plainly rather than left implicit:
    after this runs, the destructive delete_owner guard is wrong again unless the
    application code is also rolled back.
    """
    conn = op.get_bind()
    conn.execute(sa.text(
        "UPDATE employees SET account_status = 'pending_verification' "
        " WHERE account_status = 'registered'"
    ))
    op.drop_constraint(_CK, "employees", type_="check")
    op.create_check_constraint(_CK, "employees", _OLD)

"""Registration is not sign-in, and the column must say which (ADR-468).

Builds ADR-379 D3, designed 2026-09-05 and never implemented. Until now
`account_status = 'pending_verification'` meant TWO things -- "invited, no Cognito
account" and "Cognito account created, never signed in" -- because
complete_registration deliberately left the status alone.

That ambiguity had already produced a destructive bug, which is what turned
ADR-379's deferred D3 into this ADR: DELETE /companies/{id}/bootstrap guarded on
`!= "pending_verification"` to mean "has completed registration", so a fully
registered owner passed the guard and was deleted -- DB row only, no Cognito
call, leaving a live account with a valid password orphaned in the pool.

No test covered the registration->active transition or that guard, which is why
the suite stayed green while both were wrong.
"""
import ast
import inspect
import pathlib

from app.api import deps
from app.models.employee import VALID_ACCOUNT_STATUSES
from app.routers import companies, employees, registration
from app.tasks import cleanup

ROOT = pathlib.Path(__file__).resolve().parents[2]


# ── D1: the state exists, end to end ────────────────────────────────────────

def test_registered_is_a_valid_status():
    assert "registered" in VALID_ACCOUNT_STATUSES


def test_the_check_constraint_is_derived_not_retyped():
    """The literal list and the tuple were two places to add a value, and only
    one of them was obvious. A drifted CHECK rejects a status the app writes."""
    src = pathlib.Path(ROOT / "backend/app/models/employee.py").read_text()
    block = src.split("__table_args__", 1)[1].split("UniqueConstraint", 1)[0]
    assert "VALID_ACCOUNT_STATUSES" in block, (
        "the account_status CHECK hardcodes its values again"
    )
    assert "'registered'" not in block, "hardcoded literal is back"


def test_complete_registration_stamps_registered():
    src = inspect.getsource(registration)
    fn = src.split("def complete_registration", 1)[1].split("\ndef ", 1)[0]
    assert 'employee.account_status = "registered"' in fn, (
        "registration leaves the row pending_verification, so the column still "
        "cannot distinguish 'invited' from 'registered'"
    )


def test_first_signin_promotes_from_either_pre_active_state():
    """ADP-created rows and bootstrap owners never pass through
    complete_registration, so they are still pending_verification when they first
    call. Dropping either arm strands one population as not-active forever."""
    src = inspect.getsource(deps)
    assert 'account_status in ("pending_verification", "registered")' in src


def test_the_migration_widens_the_constraint_before_backfilling():
    """The UPDATE writes a value the old CHECK forbids -- ordered wrongly, the
    migration fails halfway with the constraint already dropped."""
    mig = next(pathlib.Path(ROOT / "backend/alembic/versions").glob("*adr468*.py"))
    src = mig.read_text()
    assert src.index("create_check_constraint") < src.index("UPDATE employees")


def test_the_backfill_keys_on_username_not_cognito_sub():
    """complete_registration tolerates a null cognito_sub on a genuinely
    registered employee (ADR-379 D1's reasoning), so cognito_sub would miss rows
    that username catches."""
    mig = next(pathlib.Path(ROOT / "backend/alembic/versions").glob("*adr468*.py"))
    src = mig.read_text()
    upgrade = src.split("def upgrade", 1)[1].split("def downgrade", 1)[0]
    assert "username IS NOT NULL" in upgrade
    assert "cognito_sub" not in upgrade


def test_the_migration_is_self_contained():
    mig = next(pathlib.Path(ROOT / "backend/alembic/versions").glob("*adr468*.py"))
    tree = ast.parse(mig.read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            name = getattr(node, "module", None) or node.names[0].name
            assert not str(name).startswith("app."), f"imports {name}"


# ── D2: the destructive reader ──────────────────────────────────────────────

def test_delete_owner_refuses_a_registered_owner():
    """THE bug. A registered owner has a live Cognito account, and this endpoint
    deletes the DB row WITHOUT any Cognito call -- orphaning it."""
    src = inspect.getsource(companies.delete_owner)
    assert "admin.username is not None" in src, (
        "the guard still keys on the status alone, so a registered owner passes "
        "it and their Cognito account is orphaned"
    )


def test_delete_owner_still_makes_no_cognito_call():
    """Pins the premise of the test above. If this ever gains a Cognito delete,
    the guard reasoning changes and this test should be revisited deliberately."""
    # Strip comments: the guard's own explanation NAMES Cognito, which made the
    # first version of this test fail on prose rather than on a call.
    src = inspect.getsource(companies.delete_owner)
    code = "\n".join(
        l for l in src.splitlines() if not l.strip().startswith("#")
    )
    for call in ("admin_delete_user(", "cognito.", "boto3."):
        assert call not in code, (
            "delete_owner now touches Cognito -- re-read ADR-468 D2, whose guard "
            "reasoning assumes it does not"
        )


def test_the_name_lock_keys_on_the_registration_marker():
    src = inspect.getsource(companies)
    fn = src.split("def update_owner", 1)[1].split("\ndef ", 1)[0] \
        if "def update_owner" in src else src
    assert "confirmed = admin.username is not None" in src, (
        "a registered owner is still treated as unconfirmed, so their name -- "
        "already in their Cognito account and audit rows -- can be rewritten"
    )


def test_invite_sent_is_not_derived_from_the_status():
    src = inspect.getsource(companies)
    assert "invite_sent = admin.username is not None" in src


# ── D2: the readers that would have silently died ───────────────────────────

def test_the_registered_unused_sweep_still_matches_something():
    """It selected pending_verification AND username IS NOT NULL -- exactly the
    population the migration moves to 'registered'. Left alone, the two terms
    become mutually exclusive and the sweep matches nothing, silently, forever.
    A dead sweep logs "nothing to expire" and looks healthy."""
    src = inspect.getsource(cleanup)
    fn = src.split("def expire_registered_unused", 1)[1].split("\ndef ", 1)[0]
    assert 'in_(("pending_verification", "registered"))' in fn, (
        "the registered-unused sweep can no longer match a registered row"
    )
    assert "username.isnot(None)" in fn


def test_the_invite_sweep_is_untouched_and_still_correct():
    """ADR-379 D1 regression. Its `username IS NULL` term means the migration
    never moves these rows, so it needs no change -- and must not get one."""
    src = inspect.getsource(cleanup)
    fn = src.split("def expire_pending_invites", 1)[1].split("\ndef ", 1)[0]
    assert 'Employee.account_status == "pending_verification"' in fn
    assert "username.is_(None)" in fn


def test_the_wrong_email_recovery_reaches_a_registered_employee():
    """This arm is FOR the registered case (its own comment says so) and found it
    via pending_verification + username. Under D1 that matched nothing, so every
    registered wrong-email recovery fell through to the shell-account arm, which
    deletes by email -- a Username a registered account does not have."""
    src = inspect.getsource(employees.update_employee)
    assert 'account_status in ("pending_verification", "registered")' in src


def test_the_role_group_sync_reaches_a_registered_employee():
    """Was `!= "pending_verification"`, true only for 'active' -- so a registered
    employee never had their Cognito group synced and their FIRST token carried
    the old role."""
    src = inspect.getsource(employees.update_employee)
    assert "and db_employee.username:" in src, (
        "the role sync still keys on the status, skipping registered employees"
    )


def test_the_shell_account_arm_stays_pending_only():
    """Now exact rather than incidental: this arm is the row with no username,
    and 'registered' by definition has one."""
    src = inspect.getsource(employees.update_employee)
    # The narrow arm must NOT have been widened along with the one above.
    assert src.count('account_status in ("pending_verification", "registered")') == 1


# ── client consumers ────────────────────────────────────────────────────────

def test_the_super_admin_badge_map_names_the_new_state():
    """Without an entry the badge renders the raw column value, so a super admin
    reads "registered" in a row of sentence-case labels."""
    src = (ROOT / "frontend/src/pages/superadmin/CompanyDetail.tsx").read_text()
    block = src.split("ACCOUNT_STATUS_BADGE", 1)[1].split("};", 1)[0]
    assert "registered:" in block


def test_the_pending_tile_still_counts_registered_employees():
    """Counting only pending_verification drops every registered employee out of
    the tile the moment the migration runs."""
    src = (ROOT / "frontend/src/pages/Assets.tsx").read_text()
    assert "e.account_status === 'registered'" in src
    tile = src.split("const pendingCount", 1)[1].split(";", 1)[0]
    assert "registered" in tile


def test_the_resend_invite_button_stays_pending_only():
    """A registered admin has already USED their invite; resending it is the
    wrong action, and resend-credentials is the right one."""
    src = (ROOT / "frontend/src/pages/superadmin/CompanyDetail.tsx").read_text()
    i = src.index("resendInvite(admin)")
    gate = src[max(0, i - 500):i]
    assert "=== 'pending_verification'" in gate
    assert "'registered'" not in gate


def test_the_client_lifecycle_reads_the_column_first():
    src = (ROOT / "frontend/src/pages/Assets.tsx").read_text()
    fn = src.split("function getLifecycle", 1)[1].split("\n}", 1)[0]
    assert "e.account_status === 'registered'" in fn
    # the username inference is KEPT as a fallback, not replaced
    assert "if (e.username) return 'registered'" in fn

"""ADR-452: the Owner is a role, not a provisioning artefact.

THE GAP THIS CLOSES. Before it, every employee-mutating endpoint scoped by
company_id and stopped, so ANY admin could delete, deactivate or demote the
founder — and a company with no Owner has nobody who can appoint one. ADR-451
D3 protected that row from the BOOTSTRAP endpoint while the ordinary employee
endpoints stayed wide open.
"""
import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
EMPLOYEES = ROOT / "backend" / "app" / "routers" / "employees.py"
MIGRATION = (ROOT / "backend" / "alembic" / "versions"
             / "db8751d428ad_adr452_owner_rename.py")


def _fn(name: str):
    tree = ast.parse(EMPLOYEES.read_text())
    return next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == name)


class TestTheOwnerCannotBeRemovedOrDemoted:
    @pytest.mark.parametrize("fn_name", [
        "delete_employee", "deactivate_employee", "demote_employee",
    ])
    def test_each_endpoint_refuses_the_owner(self, fn_name):
        called = {
            n.func.id for n in ast.walk(_fn(fn_name))
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }
        assert "_refuse_if_owner" in called, (
            f"{fn_name} does not guard the Owner — any admin can remove the "
            "founder, and a company with no Owner cannot appoint one "
            "(ADR-452 D2)"
        )

    def test_the_guard_actually_raises(self):
        """Asserting the CALL is not enough if the helper is a no-op."""
        fn = _fn("_refuse_if_owner")
        assert any(isinstance(n, ast.Raise) for n in ast.walk(fn))
        assert "is_owner" in ast.dump(fn)

    def test_it_applies_to_the_owner_themselves(self):
        """Self-deletion is refused for the SAME reason: the mistake is not
        recoverable from inside the tenant."""
        src = EMPLOYEES.read_text()
        start = src.index("def _refuse_if_owner")
        body = src[start:start + 1200]
        assert "INCLUDING THEMSELVES" in body.upper()
        # No caller-vs-target comparison that would let the Owner through.
        assert "caller.id" not in body

    def test_the_refusal_names_the_way_out(self):
        """A 409 that only refuses leaves the operator stuck."""
        src = EMPLOYEES.read_text()
        start = src.index("def _refuse_if_owner")
        assert "Transfer ownership" in src[start:start + 1200]


class TestOwnershipTransfers:
    def test_only_the_current_owner_may_transfer(self):
        """An ordinary admin handing ownership to themselves is a privilege
        escalation with extra steps."""
        body = ast.dump(_fn("transfer_ownership"))
        assert "is_owner" in body
        assert "403" in body or "HTTP_403_FORBIDDEN" in body

    def test_the_target_must_be_an_active_admin(self):
        """Promoting and transferring in one call would hide which happened."""
        src = EMPLOYEES.read_text()
        start = src.index("def transfer_ownership")
        body = src[start:start + 2600]
        assert 'target.role != "admin"' in body
        assert "not target.is_active" in body

    def test_the_old_owner_is_cleared_before_the_new_one_is_set(self):
        """THE BUG THIS ENCODES.

        `ix_employees_owner` is a UNIQUE PARTIAL INDEX, and a unique index
        cannot be DEFERRABLE in Postgres — it is checked per statement. Setting
        the new Owner first (SQLAlchemy's default flush order when both rows
        are dirty) raises UniqueViolation on the momentary two-Owner state, so
        the endpoint failed on EVERY call until the order was forced.
        """
        src = EMPLOYEES.read_text()
        start = src.index("def transfer_ownership")
        body = src[start:start + 2600]
        clear = body.index("caller.is_owner = False")
        setnew = body.index("target.is_owner = True")
        assert clear < setnew, "the new Owner is set before the old is cleared"
        between = body[clear:setnew]
        assert "db.flush()" in between, (
            "no flush between clearing and setting — both UPDATEs land in one "
            "statement batch and the unique index rejects them (ADR-452 D3)"
        )

    def test_it_is_audited_as_a_transfer(self):
        body = ast.dump(_fn("transfer_ownership"))
        assert "company.ownership_transferred" in body

    def test_transferring_to_yourself_is_refused(self):
        src = EMPLOYEES.read_text()
        start = src.index("def transfer_ownership")
        assert "already the Owner" in src[start:start + 2600]


class TestTheRenameIsComplete:
    def test_no_bootstrap_admin_identifier_survives(self):
        """Two columns meaning the same thing is how they drift."""
        for f in (EMPLOYEES, ROOT / "backend" / "app" / "routers" / "companies.py",
                  ROOT / "backend" / "app" / "models" / "employee.py"):
            assert "is_bootstrap_admin" not in f.read_text(), \
                f"{f.name} still references the old column name"

    def test_the_migration_renames_rather_than_adding(self):
        src = MIGRATION.read_text()
        assert "new_column_name=\"is_owner\"" in src
        assert "add_column" not in src, (
            "the migration adds a column instead of renaming — the old one "
            "would still be written by paths nobody updated"
        )

    def test_the_index_is_rebuilt_not_renamed(self):
        """Its WHERE clause names the column; a renamed index would still
        reference `is_bootstrap_admin` and fail on the next write."""
        src = MIGRATION.read_text()
        assert "drop_index" in src and "CREATE UNIQUE INDEX" in src


class TestOwnerIsAFlagNotARole:
    def test_role_stays_admin(self):
        """A fourth role string would mean auditing every role list in the
        codebase, and missing one silently removes access from the most
        privileged user in the tenant."""
        src = EMPLOYEES.read_text()
        start = src.index("def transfer_ownership")
        body = src[start:start + 2600]
        assert 'target.role = "owner"' not in body
        assert 'role="owner"' not in body

    def test_no_rolechecker_gained_an_owner_string(self):
        src = EMPLOYEES.read_text()
        assert '"owner"' not in src.replace('"ownership"', ''), \
            "an 'owner' role string leaked into a role list (ADR-452 D4)"

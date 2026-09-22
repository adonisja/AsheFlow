"""ADR-450: purging a tenant is driven by the schema, not a list.

THE MEASUREMENT THAT SHAPED THIS, against the live prod schema:

    tables carrying company_id .......... 94
    foreign keys pointing at companies .. 35

Fifty-nine tables have no referential link, so a cascade never reaches them and
a hand-written list is wrong the day a gitignored module adds a table. The ORM
sees 63 models; the database sees 94 tables.
"""
import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SERVICE = ROOT / "backend" / "app" / "services" / "purge_company.py"
ROUTER = ROOT / "backend" / "app" / "routers" / "companies.py"

from app.services import purge_company as P  # noqa: E402


class TestTheTableListComesFromTheDatabase:
    def test_it_queries_information_schema(self):
        """Not a constant and not a model walk.

        Only information_schema sees proprietary tables, migrations applied out
        of band, and tables added after this ADR was written.
        """
        src = SERVICE.read_text()
        assert "information_schema.columns" in src
        assert "column_name = 'company_id'" in src

    def test_there_is_no_hardcoded_table_list(self):
        """A list that must be maintained to stay correct will not be."""
        tree = ast.parse(SERVICE.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, (ast.List, ast.Tuple, ast.Set)):
                names = [t.id for t in node.targets if isinstance(t, ast.Name)]
                items = [e.value for e in node.value.elts if isinstance(e, ast.Constant)]
                # A literal collection of many table-ish strings is the smell.
                assert len(items) < 5, (
                    f"{names} looks like a hardcoded table list ({len(items)} "
                    "entries) — ADR-450 D1 requires the schema as the source"
                )


class TestDeletionOrderIsChildrenFirst:
    def test_unconstrained_tables_sort_before_their_parents(self):
        """The 35 FK-constrained tables must not fail on order.

        Uses a stub session so the ordering logic is tested without a database:
        the rule is graph depth, and graph depth does not need Postgres.
        """
        class _Stub:
            def execute(self, *_a, **_k):
                class R:
                    @staticmethod
                    def fetchall():
                        # child -> parent
                        return [("grandchild", "child"), ("child", "parent")]
                return R()

        order = P._delete_order(_Stub(), ["parent", "child", "grandchild", "loose"])
        assert order.index("grandchild") < order.index("child") < order.index("parent"), \
            "a child is deleted after its parent — the FK will reject it"
        # A table with NO foreign key is unordered ON PURPOSE: nothing
        # references it, so deleting it late cannot break another delete, and
        # it references nothing, so deleting it early cannot either. Asserting
        # a position for it would pin an arbitrary implementation detail.
        assert set(order) == {"parent", "child", "grandchild", "loose"}, \
            "every table must appear exactly once"

    def test_a_foreign_key_cycle_does_not_recurse_forever(self):
        """FK cycles exist in real schemas and would hang the purge."""
        class _Stub:
            def execute(self, *_a, **_k):
                class R:
                    @staticmethod
                    def fetchall():
                        return [("a", "b"), ("b", "a")]
                return R()

        P._delete_order(_Stub(), ["a", "b"])        # must terminate


class TestTheReportIsTheEvidence:
    def test_it_carries_per_table_counts(self):
        """"Done" tells an operator nothing about whether it found 233
        employees or zero (ADR-450 D2)."""
        r = P.PurgeReport(company_id="c", company_name="X")
        r.rows_by_table = {"employees": 233, "companies": 1}
        assert r.total_rows == 234

    def test_an_empty_purge_reports_zero_not_an_error(self):
        r = P.PurgeReport(company_id="c", company_name="X")
        assert r.total_rows == 0


class TestCognitoIsTornDownBeforeTheRows:
    def test_the_endpoint_calls_cognito_first(self):
        """It reads employees to learn which usernames exist.

        After the database purge those rows are gone, so the wrong order leaves
        users who can still authenticate against a tenant that does not exist.
        """
        src = ROUTER.read_text()
        start = src.index("def purge_company_endpoint")
        body = src[start:start + 4000]
        assert body.index("purge_cognito(") < body.index("purge_company("), \
            "the database purge runs before the Cognito teardown (ADR-450 D3)"

    def test_a_missing_user_is_not_an_error(self):
        """The desired end state already holds."""
        src = SERVICE.read_text()
        assert "UserNotFoundException" in src

    def test_failures_are_collected_not_raised(self):
        """A half-purged tenant must be VISIBLE; the remedy is manual, and a
        Cognito error must not roll back a correct database purge."""
        src = SERVICE.read_text()
        assert "cognito_errors.append" in src

    def test_the_error_names_no_employee_email(self):
        """Dimension 7: the employee id is enough to find the row."""
        src = SERVICE.read_text()
        start = src.index("def purge_cognito")
        body = src[start:]
        assert "employee.email" not in body


class TestTheEndpointGuards:
    def _fn(self):
        tree = ast.parse(ROUTER.read_text())
        return next(n for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef) and n.name == "purge_company_endpoint")

    def test_it_is_super_admin_only(self):
        """A company admin must not be able to delete their own history."""
        deco = " ".join(ast.dump(d) for d in self._fn().decorator_list)
        args = ast.dump(self._fn().args)
        assert "get_super_admin" in args or "get_super_admin" in deco

    def test_an_active_company_cannot_be_purged(self):
        """The destructive action must not be reachable from the state an
        operating tenant is in (ADR-450 D4)."""
        body = ast.dump(self._fn())
        assert "is_active" in body and "409" in body

    def test_the_name_must_be_typed(self):
        """Clicking a button next to a row is not a deliberate act."""
        body = ast.dump(self._fn())
        assert "confirm_name" in body

    def test_the_audit_is_written_before_the_delete_and_outside_the_tenant(self):
        """An audit row scoped to this company would be deleted by its own
        purge, leaving no record that the purge happened."""
        src = ROUTER.read_text()
        start = src.index("def purge_company_endpoint")
        body = src[start:start + 4000]
        assert body.index("write_audit(") < body.index("purge_company("), \
            "the audit is written after the purge — it would be deleted by it"
        audit = body[body.index("write_audit("):body.index("write_audit(") + 400]
        assert "company_id=None" in audit, \
            "the audit is scoped to the company being purged (ADR-450 D5)"

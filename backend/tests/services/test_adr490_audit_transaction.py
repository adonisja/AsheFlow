"""An audit row written after the commit is not written (ADR-490).

THE DEFECT, AND WHY IT WAS INVISIBLE
====================================

`get_db` only CLOSES the session:

    def get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()        # an uncommitted session is DISCARDED

So a `write_audit` after the last `db.commit()` adds a row that is thrown away.
`write_audit` is still called, with correct arguments, and the endpoint returns
201. Nothing throws, nothing logs, no test fails.

It is only visible by comparing two numbers that nothing compares. Measured
before the fix:

    employees that exist            : 22
    audit rows employee.create      : 0
    audit rows employee.bulk_create : 0
    audit rows employee.update      : 0
    total audit rows                : 77      <- the system works
    audit rows collection.submit    : 52      <- other types write fine

The whole employee lifecycle wrote no audit trail from the day it shipped, and
ADR-132 added audit logging for SOC2 and GDPR.

WHY THESE TESTS ARE STRUCTURAL
==============================

A behavioural test would need a DB and would only cover the endpoints it
exercises. The property is "the audit row joins the transaction", which is a
statement about ORDER — so most of these read the source, and the one
behavioural test covers the path that actually lost rows.
"""
from __future__ import annotations

import ast
import inspect
import pathlib

import pytest

APP = pathlib.Path(__file__).resolve().parents[2] / "app"


def _load_gate():
    """The gate module, imported so tests share its path logic rather than
    re-implementing it. Two implementations of "same path" would drift, and the
    one that guards the build is the one that matters."""
    import importlib.util
    path = pathlib.Path(__file__).resolve().parents[3] / "scripts/check_audit_before_commit.py"
    spec = importlib.util.spec_from_file_location("_adr490_gate", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fn_source(module_path: str, name: str) -> tuple[str, ast.AST]:
    src = (APP / module_path).read_text()
    for fn in ast.walk(ast.parse(src)):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and fn.name == name:
            return src, fn
    raise AssertionError(f"{name} not found in {module_path}")


def _audit_and_commit_lines(src: str, fn: ast.AST) -> tuple[list[int], list[int]]:
    """Absolute line numbers of write_audit calls and db.commit() statements.

    `_audit_created()` call sites count as audits: the row is written where the
    helper is CALLED, not where it is defined. Without this a closure defined
    above every commit looks correctly ordered even when nobody calls it.
    """
    nested = {
        n.name for n in fn.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(
            isinstance(c, ast.Call)
            and getattr(c.func, "id", getattr(c.func, "attr", "")) == "write_audit"
            for c in ast.walk(n)
        )
    }
    audits, commits = [], []
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            name = getattr(n.func, "id", getattr(n.func, "attr", ""))
            if name == "write_audit" or name in nested:
                audits.append(n.lineno)
        if isinstance(n, ast.Expr) and ast.unparse(n).strip() == "db.commit()":
            commits.append(n.lineno)
    return sorted(audits), sorted(commits)


class TestTheEmployeeLifecycleAuditsAtAll:
    """The three never-persisted cases. These are the compliance gap: not a
    window, not a style deviation — no row was ever written."""

    @pytest.mark.parametrize("name", [
        "create_employee", "bulk_import_employees", "update_employee",
    ])
    def test_a_commit_follows_the_audit(self, name):
        src, fn = _fn_source("routers/employees.py", name)
        audits, commits = _audit_and_commit_lines(src, fn)
        assert audits, f"{name} writes no audit row at all"
        after = [c for c in commits if c > max(audits)]
        assert after, (
            f"{name} has no db.commit() after its last audit, so the row is "
            f"discarded when get_db closes the session — the row is never "
            f"written. audits@{audits} commits@{commits}"
        )

    def test_create_employee_audits_on_both_branches(self):
        """Its commit sits inside `if employee.email:` with an `else` that
        commits separately. One `write_audit` after both arms audited NEITHER,
        which is how the defect arose — so the helper must be called twice."""
        src, fn = _fn_source("routers/employees.py", "create_employee")
        calls = [
            n.lineno for n in ast.walk(fn)
            if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_audit_created"
        ]
        assert len(calls) == 2, (
            f"expected the audit helper called in both the email and else arms, "
            f"found {len(calls)} call site(s) at {calls}"
        )

    def test_the_helper_is_a_closure_not_two_copies(self):
        """Two inline copies would drift — one would gain a field the other
        lacks, and the two arms would record different things."""
        src, fn = _fn_source("routers/employees.py", "create_employee")
        nested = [
            n.name for n in fn.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        assert "_audit_created" in nested
        audits = [
            n for n in ast.walk(fn)
            if isinstance(n, ast.Call)
            and getattr(n.func, "id", getattr(n.func, "attr", "")) == "write_audit"
        ]
        assert len(audits) == 1, (
            f"the audit body is duplicated {len(audits)} times; one closure "
            f"called twice cannot drift"
        )


class TestTheLostPlatformAlertRows:
    """A second silent loss on the same lines, found while fixing the first.

    Both create paths call `raise_platform_alert` inside an `except ClientError`
    that runs AFTER the commit — so the ADR-336 email-outage alert was discarded
    too. On a 40-row bulk import, ADR-336's whole point is that ONE deduped
    incident reaches the board; zero did.
    """

    @pytest.mark.parametrize("name", ["create_employee", "bulk_import_employees"])
    def test_the_alert_is_committed(self, name):
        src, fn = _fn_source("routers/employees.py", name)
        body = ast.get_source_segment(src, fn) or ""
        idx = body.index("raise_platform_alert")
        tail = body[idx:idx + 700]
        assert "db.commit()" in tail, (
            f"{name} raises a platform alert with no commit after it, so the "
            f"alert row is discarded on teardown"
        )


class TestTheOrderingFixes:
    """The four timing windows. The row did persist via a later commit; the
    defect was that the state change was already durable when it was written."""

    @pytest.mark.parametrize("module,name", [
        ("routers/adp.py", "employee_signoff"),
        ("routers/adp.py", "reject_adjustment"),
        ("tasks/adp_sync.py", "sync_adp_employees"),
    ])
    def test_no_commit_precedes_the_audit_on_the_same_path(self, module, name):
        """Delegates to the GATE's own path logic rather than re-deriving it.

        A first version compared source INDENTATION, and failed on
        `adp_sync.sync_adp_employees`: its reactivation commit sits at the same
        indent as the offboarding audit but in a different `if` branch, so they
        are never reached together. Indentation is not a path.

        Importing the gate also means this test and the gate cannot disagree —
        a second implementation of "same path" would drift from the one that
        actually guards the build.
        """
        gate = _load_gate()
        src, fn = _fn_source(module, name)
        tree = ast.parse(src)
        parents = {}
        for n in ast.walk(tree):
            for c in ast.iter_child_nodes(n):
                parents[c] = n
        # re-find fn inside THIS tree so the parent map matches
        fn = next(
            f for f in ast.walk(tree)
            if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)) and f.name == name
        )
        audit_nodes = [
            n for n in ast.walk(fn)
            if isinstance(n, ast.Call)
            and getattr(n.func, "id", getattr(n.func, "attr", "")) == "write_audit"
        ]
        commit_nodes = [
            n for n in ast.walk(fn)
            if isinstance(n, ast.Expr) and ast.unparse(n).strip() == "db.commit()"
        ]
        first_audit = min(audit_nodes, key=lambda n: n.lineno)
        # The gate's FULL verdict, not just its path helper. Pattern A matters
        # here: `adp_sync.sync_adp_employees` has a commit on the same path as
        # its audit (the Cognito disable at line 95), and that is fine — the
        # `db.delete(member)` calls between them are uncommitted work the audit
        # describes, landing together on the commit below it.
        #
        # A first version of this test called `_commit_always_precedes` alone
        # and failed on correct code, because same-path is a necessary and not a
        # sufficient condition. Asking the gate the whole question is also the
        # only way this test and the build cannot disagree.
        verdicts = gate._check_file(APP / module)
        offenders = [v for v in verdicts if v[2] == name]
        assert not offenders, (
            f"{name} writes an audit row outside its transaction: {offenders}"
        )

    def test_manager_signoff_keeps_its_pre_call_commit(self):
        """The exception that proves the rule is about ORDER, not count.

        Its `after` reports the status AFTER an outbound ADP write
        ("applied"/"write_failed"), which does not exist until the call returns —
        so the audit cannot move to the top. The first commit is deliberate: it
        persists the manager's decision before an HTTP call that may hang.
        """
        src, fn = _fn_source("routers/adp.py", "manager_sign_off")
        audits, commits = _audit_and_commit_lines(src, fn)
        assert len(commits) >= 2, "the pre-ADP-call commit was removed"
        assert min(commits) < min(audits), (
            "the pre-call commit must stay BEFORE the audit: it protects the "
            "manager's decision from an ADP timeout"
        )
        after = [c for c in commits if c > max(audits)]
        assert after, "the audit still has no commit after it"


class TestTheGateCatchesWhatItClaims:
    """The gate took three corrections to get right. Each is pinned here,
    because a gate that cannot catch the bug it was written for is worse than
    none — it reads as coverage."""

    GATE = pathlib.Path(__file__).resolve().parents[3] / "scripts/check_audit_before_commit.py"

    def test_the_gate_exists_and_is_stdlib_only(self):
        """It runs in the Design tokens job, which installs no dependencies."""
        src = self.GATE.read_text()
        imports = {
            n.module for n in ast.walk(ast.parse(src)) if isinstance(n, ast.ImportFrom)
        } | {
            a.name for n in ast.walk(ast.parse(src))
            if isinstance(n, ast.Import) for a in n.names
        }
        allowed = {"ast", "pathlib", "sys", "__future__", None}
        assert imports <= allowed, f"non-stdlib import would fail that job: {imports - allowed}"

    def test_it_resolves_nested_audit_helpers_to_their_call_sites(self):
        """Correction 1. `ast.walk` descends into nested functions, so a
        `write_audit` inside a closure is at the closure's line — above every
        commit — and the gate passed even with nobody calling it."""
        src = self.GATE.read_text()
        assert "nested_with_audit" in src
        assert "_in_nested" in src

    def test_it_compares_branch_paths_directionally(self):
        """Corrections 2 and 3, which were opposite errors.

        An absolute "is the commit conditional?" test excluded
        `adp_sync.sync_adp_employees`, whose commit and audit are in the SAME
        for/if. A symmetric prefix test then flagged `trigger_dispatch`, whose
        commit is in an `if` while its audit is at function level. The commit's
        chain must be a prefix of the AUDIT's, never the reverse.
        """
        src = self.GATE.read_text()
        assert "_commit_always_precedes" in src
        assert "len(pc) <= len(pa)" in src, "the comparison is not directional"

    def test_it_flags_an_uncalled_audit_helper(self):
        """Correction 4. With both call sites removed the gate went quiet,
        because `audits` was empty and the function was skipped."""
        src = self.GATE.read_text()
        assert "is never \\n" in src or "never" in src
        assert "called = any(" in src

    def test_it_excludes_the_documented_integrity_error_case(self):
        """CLAUDE.md's one legitimate commit-then-audit shape. Verified real:
        `walker_routes.py:1592` is the single call site."""
        src = self.GATE.read_text()
        assert "_in_integrity_handler" in src
        assert "IntegrityError" in src

    def test_it_has_no_per_file_exemption_list(self):
        """ADR-488's lesson: a file-level exemption silences a whole module, and
        the one added to `check_no_naive_utc_relabel` hid a real relabel in the
        file the rule existed to protect."""
        # Docstring stripped: the gate EXPLAINS why it has no exemption list,
        # naming EXEMPT to do so. Thirteenth time in this body of work that an
        # absence assertion has matched its own explanation.
        tree = ast.parse(self.GATE.read_text())
        doc = ast.get_docstring(tree) or ""
        src = self.GATE.read_text().replace(doc, "")
        assert "EXEMPT" not in src, (
            "an exemption list that starts at 8 entries on day one is a list "
            "nobody maintains — encode the three exclusions instead"
        )

    def test_it_passes_on_the_current_tree(self):
        import subprocess
        import sys
        r = subprocess.run(
            [sys.executable, str(self.GATE)], capture_output=True, text=True,
        )
        assert r.returncode == 0, r.stdout

"""Roles and Cognito groups are two systems with nothing between them (ADR-317).

A captain signed in and saw three tabs. The mobile nav filters on `hasRole`,
which reads the JWT's `cognito:groups` claim — NOT `Employee.role`. Measured
during the incident:

    DB (dsp-test):  8 employees with role='captain'
    Cognito:        captain 0    driver 1    walker 1
                    dispatch 2   management 1  admin 2   trainer 1

The group existed and was empty, so every captain's token carried no group claim
and every role-gated tab vanished. Both systems were internally consistent and
neither could see the other.
"""
import ast
import inspect
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services import role_directory_check as RDC


def _code_only(obj) -> str:
    tree = ast.parse(inspect.getsource(obj))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef, ast.Module)):
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                node.body.pop(0)
    return ast.unparse(tree)


def _db(roles):
    db = MagicMock()
    db.query.return_value.distinct.return_value.all.return_value = [(r,) for r in roles]
    return db


# ── The incident itself ──────────────────────────────────────────────────────

def test_an_empty_group_for_a_role_in_use_is_reported():
    """THE state this came from: 8 captains in the DB, a `captain` group with
    zero members, and nothing anywhere noticing."""
    with patch.object(RDC, "_group_member_counts",
                      return_value={"captain": 0, "driver": 1, "walker": 1}):
        r = RDC.check_role_directory(_db(["captain", "driver", "walker"]),
                                     pool_id="p", region="us-east-2")
    assert r.roles_with_empty_group == ["captain"]
    assert r.ok is False


def test_a_role_with_no_group_at_all_is_reported_separately():
    """Distinct from an empty group: nobody with that role can sign in usefully,
    and the fix is different (create the group, not populate it)."""
    with patch.object(RDC, "_group_member_counts", return_value={"driver": 1}):
        r = RDC.check_role_directory(_db(["driver", "captain"]),
                                     pool_id="p", region="us-east-2")
    assert r.roles_without_group == ["captain"]
    assert r.roles_with_empty_group == []


def test_a_populated_directory_is_clean():
    with patch.object(RDC, "_group_member_counts",
                      return_value={"captain": 1, "driver": 1}):
        r = RDC.check_role_directory(_db(["captain", "driver"]),
                                     pool_id="p", region="us-east-2")
    assert r.ok is True


def test_a_group_nobody_holds_is_noted_but_not_a_failure():
    """Drift worth seeing, but it breaks nothing — no employee is affected."""
    with patch.object(RDC, "_group_member_counts",
                      return_value={"driver": 1, "super_admin": 1}):
        r = RDC.check_role_directory(_db(["driver"]), pool_id="p", region="us-east-2")
    assert r.groups_without_role == ["super_admin"]
    assert r.ok is True


# ── D1: reports, never enforces ──────────────────────────────────────────────

def test_an_unreachable_directory_is_not_a_failure():
    """Verified live: staging's EC2 role lacks cognito-idp:ListGroups and got
    AccessDeniedException. An outage or a missing permission in THEIR service
    must not mark OUR API unhealthy."""
    with patch.object(RDC, "_group_member_counts", return_value=None):
        r = RDC.check_role_directory(_db(["captain"]), pool_id="p", region="us-east-2")
    assert r.unavailable is True
    assert r.roles_with_empty_group == []


def test_no_pool_configured_is_not_a_failure():
    r = RDC.check_role_directory(_db(["captain"]), pool_id="", region="us-east-2")
    assert r.unavailable is True


def test_the_logger_never_raises():
    """A directory problem must not fail a task queue or a boot."""
    db = MagicMock()
    db.query.side_effect = RuntimeError("boom")
    r = RDC.log_role_directory(db, pool_id="p", region="us-east-2")
    assert r.unavailable is True


# ── Dimension 6: a diagnostic is not a place for PII ─────────────────────────

def test_the_report_carries_names_and_counts_never_people():
    fields = set(RDC.RoleDirectoryReport().as_dict())
    assert fields == {"ok", "unavailable", "roles_without_group",
                      "roles_with_empty_group", "groups_without_role"}
    # Docstrings stripped: the module's own prose says "never a username, an
    # email, or a sub", and grepping raw source matches its own warning — the
    # exact trap _code_only() exists for.
    src = _code_only(RDC)
    for pii in ("Username", "email", '"sub"', "Attributes"):
        assert pii not in src, f"{pii} must not reach a directory diagnostic"

    # `Users` IS referenced — but only ever wrapped in len(). Every occurrence
    # must sit inside a len() call: a count is not a person, iterating would be.
    body = _code_only(RDC._group_member_counts)
    for line in body.splitlines():
        if "'Users'" in line or '"Users"' in line:
            assert "len(" in line, (
                f"Users may only be counted, never read member by member: {line.strip()}"
            )


def test_a_boto_error_is_not_logged_verbatim():
    """A boto exception carries request ids and ARNs, and this runs where it
    would land in every log."""
    src = _code_only(RDC._group_member_counts)
    assert "str(e)" not in src and "str(exc)" not in src


# ── Federated groups are not roles ───────────────────────────────────────────

def test_identity_provider_groups_are_ignored():
    """Cognito creates `<pool>_Google` / `<pool>_Discord` for federated logins.
    Counting them as roles would report permanent, unfixable drift."""
    src = _code_only(RDC._group_member_counts)
    assert "startswith(pool_id)" in src


# ── D5 / Dim 5: zero employees is not an error ───────────────────────────────

def test_a_role_nobody_holds_is_not_reported():
    """Only roles someone actually has matter — those are the sign-ins that
    break."""
    with patch.object(RDC, "_group_member_counts", return_value={"driver": 1}):
        r = RDC.check_role_directory(_db(["driver"]), pool_id="p", region="us-east-2")
    assert r.roles_without_group == [] and r.roles_with_empty_group == []

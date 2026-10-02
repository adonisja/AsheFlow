"""Tenant discovery for platform campaigns (ADR-485 D9).

The address study stays platform-owned; tenants get a route IN, not a copy. The
security machinery already existed — `_authorise_scope` has required tenant
membership since ADR-423 D2 — so all that was missing is discovery.

The two constraints are the tests that matter, because both failures are
silent: an open-scoped token surfaced inside the app looks like any other row,
and a cross-tenant token looks like one of yours.
"""
import ast
import datetime
import inspect
import textwrap
import uuid
from unittest.mock import MagicMock

import pytest

from app.models.collection import CollectionToken
from app.routers import collection as C
from app.schemas.collection import MyCampaignOut


def _code(fn) -> str:
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.Module)) \
                and ast.get_docstring(node):
            node.body = node.body[1:]
    return ast.unparse(tree)


# ── constraint 1: never an open-scoped token ────────────────────────────────

def test_it_filters_to_company_scope():
    """An open-scoped token is the anonymous public study. Surfacing one inside
    the app puts a link with NO tenant check into a place that implies one."""
    src = _code(C.my_campaigns)
    assert "CollectionToken.scope == SCOPE_COMPANY" in src


def test_it_never_mentions_the_open_scope():
    assert "SCOPE_OPEN" not in _code(C.my_campaigns)


# ── constraint 2: only this caller's tenant ─────────────────────────────────

def test_it_filters_to_the_callers_company():
    """ADR-115 D1, stated rather than inferred from the scope filter: a future
    edit that loosens the scope must not silently widen the tenant too."""
    assert "CollectionToken.company_id == caller.company_id" in _code(C.my_campaigns)


def test_it_requires_an_authenticated_caller():
    """get_caller_employee, NOT the anonymous-tolerant variant the submit paths
    use — discovery is the authenticated half of this router."""
    # Inspect the SIGNATURE, not the source text: an earlier version scanned
    # for the word "anonymous" and failed on a COMMENT describing open-scoped
    # tokens as the anonymous public study. Eighth prose-not-code match in this
    # body of work.
    import typing
    hints = typing.get_type_hints(C.my_campaigns)
    sig = inspect.signature(C.my_campaigns)
    dep = sig.parameters["caller"].default
    assert dep.dependency is C.get_caller_employee, (
        f"caller resolves via {dep.dependency.__name__}, not get_caller_employee")


# ── liveness ────────────────────────────────────────────────────────────────

def test_a_revoked_campaign_is_not_listed():
    assert "revoked_at.is_(None)" in _code(C.my_campaigns)


def test_a_never_expiring_campaign_is_still_listed():
    """`expires_at` is nullable and "never expires" is a legitimate state. A
    SQL `expires_at > now` would drop those rows silently, so the filter is in
    Python and handles None explicitly."""
    src = _code(C.my_campaigns)
    assert "expires_at is None" in src


def test_an_expired_campaign_is_not_listed():
    src = _code(C.my_campaigns)
    assert "expires_at > now" in src


# ── what it returns ─────────────────────────────────────────────────────────

def test_it_returns_the_token():
    """Deliberate. _authorise_scope re-checks tenant membership on every
    submit, so a forwarded token is no more useful than it is today — and the
    token is what carries daily_cap, revocation and the dataset gate. A
    per-user submit path that bypassed it would be a second way in."""
    assert "token" in MyCampaignOut.model_fields


def test_it_returns_the_dataset():
    """A link is issued for ONE study (ADR-439). The client has to know which,
    or it submits an address to a routes campaign and gets a 404 it cannot
    explain."""
    assert "dataset" in MyCampaignOut.model_fields


def test_it_does_not_leak_the_cap_or_the_creator():
    """daily_cap is a defence; telling a caller the number tells them where it
    stops. created_by is a super admin's identity, which a tenant has no reason
    to see."""
    fields = set(MyCampaignOut.model_fields)
    assert "daily_cap" not in fields
    assert "created_by" not in fields and "created_by_name" not in fields


def test_the_token_model_is_untouched():
    """D9 reverses an earlier ask for per-tenant address campaigns. The tables
    stay separate: merging them would make the anonymous path's daily_cap,
    per-IP limits and bulk-undo into optional flags on a shared code path."""
    cols = {c.key for c in CollectionToken.__table__.columns}
    assert "tenant_visible" not in cols, (
        "the ADR mentions a tenant-visible marker that does not exist and "
        "should not: a company_id IS NULL token is open-scope by construction")


# ── issuing is unchanged ────────────────────────────────────────────────────

def test_minting_a_token_is_still_super_admin_only():
    """A tenant admin can see and distribute a campaign they were given; they
    cannot mint one, because minting decides which study the data joins."""
    src = inspect.getsource(C.create_token)
    assert "get_super_admin" in src

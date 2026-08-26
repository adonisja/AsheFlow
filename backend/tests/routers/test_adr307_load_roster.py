"""Workforce tote check-off: presence only, never removals (ADR-307 D1a/D1b).

A workforce driver DOES check totes onto the truck — they say which they
received and which they did not, and that is the moment a missing bag is caught.
It happens whether or not the company has a package feed.

What it cannot do is explain what was lost. Full mode turns an unchecked tote
into a PackageRemoval (ADR-176) because the manifest says which packages were
inside and where they were going. Workforce mode has no per-package address
data: a missing tote is a bag id and a colour. So check-off records PRESENCE and
stops there.
"""
import ast
import inspect

import pytest

from app.models.tote_ops import ToteLoadCheck
from app.routers import workforce_routes as W


def _code_only(obj) -> str:
    """Source with docstrings stripped — grep matches its own prose otherwise.

    Three tests in an earlier module failed against a comment explaining why a
    model is NOT used. Parse, do not grep.
    """
    tree = ast.parse(inspect.getsource(obj))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef, ast.Module)):
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                node.body.pop(0)
    return ast.unparse(tree)


# ── D1b: presence only ───────────────────────────────────────────────────────

def test_check_off_never_creates_a_removal():
    """THE invariant this ADR turns on.

    Asserted on the CODE rather than a response, because a fabricated
    PackageRemoval would be silent — the endpoint would still return a healthy
    roster while having invented a custody record for contents it cannot see.
    """
    src = _code_only(W.check_tote)
    assert "PackageRemoval" not in src, (
        "workforce mode has no per-package address data — a removal record would "
        "claim knowledge of what was in the tote (ADR-307 D1b)"
    )
    assert "removal" not in src.lower()


def test_the_roster_reports_unchecked_rather_than_resolving_it():
    """An unchecked tote is a COUNT, not an event."""
    f = W.LoadRosterOut.model_fields
    assert "unchecked_count" in f
    assert "removals" not in f and "removal_count" not in f


# ── D1a: ToteLoadCheck is reused, not duplicated ─────────────────────────────

def test_check_state_uses_the_existing_mode_agnostic_table():
    """`ToteLoadCheck` has no zone, manifest or TBA reference — it was always
    mode-agnostic and only its READERS were full-mode gated. A parallel
    workforce table would split one operational fact across two schemas."""
    cols = {c.name for c in ToteLoadCheck.__table__.columns}
    assert cols == {
        "id", "company_id", "load_date", "truck_id", "bag_id",
        "checked_by", "checked_by_name", "checked_at",
    }
    for coupled in ("zone_id", "tba", "tba_numbers", "manifest_id", "zone_label"):
        assert coupled not in cols, f"{coupled} would make this full-mode-only"

    assert "ToteLoadCheck" in _code_only(W.check_tote)


def test_a_mode_switch_keeps_one_continuous_history():
    """Both modes write the same table with the same keys, so a tenant that
    flips does not lose or fork its check-off record."""
    src = _code_only(W.check_tote)
    for key in ("company_id", "load_date", "truck_id", "bag_id"):
        assert key in src


# ── The guards, mirrored from sort.py ────────────────────────────────────────

def test_double_check_and_double_uncheck_both_409():
    """A double-tap on a phone in a warehouse must not silently write a second
    row or read as a confusing no-op."""
    src = _code_only(W.check_tote)
    assert src.count("HTTP_409_CONFLICT") == 2


def test_a_bag_not_on_the_sheet_is_a_404():
    """Otherwise a typo creates a check for a tote nobody expects and the counts
    stop reconciling against the sheet."""
    src = _code_only(W.check_tote)
    assert "HTTP_404_NOT_FOUND" in src
    assert "BTRSheet.sheet_date == load_date" in src


def test_the_write_is_audited():
    src = _code_only(W.check_tote)
    assert "write_audit" in src
    assert "workforce.tote_checked" in src and "workforce.tote_unchecked" in src


# ── No sheet is not an empty truck ───────────────────────────────────────────

def test_missing_sheet_is_flagged_not_rendered_as_zero_totes():
    """"No sheet imported" and "this truck has no totes" are different facts.

    An empty roster with no flag would read as the second, and a driver would
    tick nothing and move on.
    """
    assert "no_sheet" in W.LoadRosterOut.model_fields
    src = _code_only(W.load_roster)
    assert "no_sheet=True" in src


# ── Dimension 1 and 9 ────────────────────────────────────────────────────────

def test_every_query_is_company_scoped():
    for fn in (W.load_roster, W.check_tote):
        src = _code_only(fn)
        queries = src.count("db.query(")
        scoped = src.count("company_id ==")
        assert scoped >= queries, (
            f"{fn.__name__}: {queries} queries but only {scoped} company_id filters"
        )


def test_the_request_body_is_typed_and_closed():
    f = W.ToteCheckIn.model_fields
    assert W.ToteCheckIn.model_config.get("extra") == "forbid"
    assert f["checked"].annotation is bool
    assert "UUID" in str(f["truck_assignment_id"].annotation)
    for name, field in f.items():
        assert "Any" not in str(field.annotation)
        assert "dict" not in str(field.annotation).lower()


def test_the_roster_read_admits_field_staff_but_the_write_does_not():
    """A walker reads what is on the truck; ticking it off is route-lead work."""
    def roles(fn):
        return next(
            (g for g in (
                getattr(p.default.dependency, "allowed_roles", None)
                for p in inspect.signature(fn).parameters.values()
                if getattr(p.default, "dependency", None) is not None
            ) if g),
            [],
        )

    assert "walker" in roles(W.load_roster)
    assert "walker" not in roles(W.check_tote)
    assert "captain" in roles(W.check_tote)


# ── Not a rename of full mode's endpoint ─────────────────────────────────────

def test_the_roster_comes_from_the_btr_sheet_not_truckzone():
    """`/sort/{date}/rosters` returns TruckZone rosters — the station sort's
    clustering output, which does not exist here. Same question, different
    source."""
    src = _code_only(W.load_roster)
    assert "BTRBag" in src and "BTRSheet" in src
    assert "TruckZone" not in src

"""An audit snapshot holds whatever the column holds (ADR-481).

PATCH /companies/my-config returned 500 on every save touching a time field --
in prod, on the Company Setup form an Owner must complete before the platform is
usable.

    before = {k: getattr(config, k, None) for k in changed}  # time(11, 0)
    after  = payload.model_dump(exclude_unset=True)          # "11:00"

`after` comes from the request (strings). `before` comes from the ORM, where
shift_start is Column(Time). Both go into a JSONB column, and datetime.time has
no JSON encoder -- so the two halves of one snapshot had different types and
only one survived.

Six call sites build snapshots this way (companies.py 607/1128/1550/1969/2091,
trucks.py 205), so the fix is at the boundary rather than in the callers.
"""
import datetime
import json
import uuid
from decimal import Decimal

import pytest

from app.services.audit import _jsonable, _safe_snapshot


# ── D1: the coercion ────────────────────────────────────────────────────────

def test_a_time_survives_the_boundary():
    """THE bug. Column(Time) reads back as datetime.time."""
    out = _jsonable(datetime.time(11, 0))
    assert out == "11:00:00"
    json.dumps(out)


def test_datetime_is_not_flattened_to_a_date():
    """datetime subclasses date, so an isinstance chain that checks date first
    silently drops the time half of every timestamp."""
    out = _jsonable(datetime.datetime(2026, 9, 29, 11, 30, 5))
    assert out.startswith("2026-09-29T11:30")


def test_the_other_orm_types_json_does_not_cover():
    assert _jsonable(datetime.date(2026, 9, 29)) == "2026-09-29"
    assert _jsonable(Decimal("12.50")) == 12.5
    u = uuid.uuid4()
    assert _jsonable(u) == str(u)


def test_plain_values_pass_through_unchanged():
    """Coercion must not reshape what already works -- an audit trail that
    stringifies every int is harder to read and to query."""
    for v in (None, "x", True, 5, 1.5):
        assert _jsonable(v) is v


def test_it_recurses_into_containers():
    out = _jsonable({"a": [datetime.time(9, 0)], "b": {"c": datetime.date(2026, 1, 1)}})
    assert out == {"a": ["09:00:00"], "b": {"c": "2026-01-01"}}
    json.dumps(out)


def test_an_unknown_type_is_stringified_rather_than_raising():
    class Odd:
        def __str__(self): return "odd-value"
    json.dumps(_jsonable({"k": Odd()}))


# ── D2: an audit write must never fail the action ───────────────────────────

def test_a_whole_snapshot_becomes_json_safe():
    """The real shape from the prod failure: ORM times beside plain ints."""
    snap = {"shift_start": datetime.time(11, 0), "graduation_threshold_days": 5}
    json.dumps(_safe_snapshot(snap, "before", "company_config.update"))


def test_an_unserialisable_snapshot_yields_a_placeholder_not_an_exception():
    """The record is OF the action, not the action. A snapshot that cannot be
    encoded must not 500 a save that otherwise succeeded."""
    class Hostile:
        def __str__(self): raise RuntimeError("nope")
    out = _safe_snapshot({"k": Hostile()}, "before", "x.y")
    assert out is not None and out.get("_unserialisable") is True
    json.dumps(out)


def test_the_placeholder_is_visible_rather_than_silent():
    """A missing snapshot that looks like 'nothing changed' is worse than one
    that says it failed."""
    class Hostile:
        def __str__(self): raise RuntimeError("nope")
    out = _safe_snapshot({"k": Hostile()}, "before", "x.y")
    assert "_error" in out


def test_none_stays_none():
    """NULL before_snapshot is meaningful -- it marks a create."""
    assert _safe_snapshot(None, "before", "x.y") is None


# ── the boundary is actually wired in ───────────────────────────────────────

def test_write_audit_routes_both_snapshots_through_the_coercion():
    """Without this the helper exists and nothing calls it -- the shape of bug
    that shipped ADR-381's unreachable endpoints."""
    import inspect
    from app.services import audit
    src = inspect.getsource(audit.write_audit)
    assert "_safe_snapshot(before" in src and "_safe_snapshot(after" in src

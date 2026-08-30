"""Truck names come from the payload; summaries update on every state change (ADR-332).

Two findings from the ADR-331 simulator verification.

1. `truck_assignments` carried no `truck_name`, so three consumers worked around
   it: NotificationsScreen regexed the message prose and rendered "Truck the",
   DriverSurveyScreen read a field that has never existed, and the bot re-queries.

2. ADR-327 gave the day summaries receipts but wired the upsert into the BULK
   finalize only. `publish_assignments` bare-sent and `hub_finalize_truck` — the
   per-truck path actually in use — posted no summary at all. Measured: zero
   DispatchDaySummary rows on staging after a day of publishes and a per-truck
   finalize.
"""
import ast
import inspect
import os
import re

import pytest

from app.models.dispatch_day_summary import DispatchDaySummary
from app.routers import dispatch as D

BOT = os.path.join(os.path.dirname(__file__), "..", "..", "..", "bot")
MOBILE = os.path.join(os.path.dirname(__file__), "..", "..", "..", "mobile", "src")


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


def _read(base, rel):
    p = os.path.abspath(os.path.join(base, rel))
    if not os.path.exists(p):
        pytest.fail(f"{rel} not found at {p}")
    return open(p).read()


def _strip_docstrings(src: str) -> str:
    """Docstrings describe their own subject and match greps aimed at code.

    `test_the_refresh_never_fails_the_operation` failed against correct code
    because the docstring says "Never raises". Fourth variant of this shape
    this week — grep the code, not the explanation of the code.
    """
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef, ast.Module)):
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                node.body.pop(0)
    return ast.unparse(tree)


def _cog_fn(name: str) -> str:
    tree = ast.parse(_read(BOT, "cogs/dispatch.py"))
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name), None)
    assert fn is not None, f"{name} not found in the cog"
    return ast.unparse(fn)


# ── Part 1: the name is data ─────────────────────────────────────────────────

def test_the_payload_carries_the_truck_name():
    # ast.unparse normalises quotes to single — match quote-agnostically.
    src = _code_only(D.get_daily_dispatch)
    assert "'truck_name': truck_names.get(a.truck_id)" in src


def test_the_name_lookup_is_company_scoped():
    """Dim 1 — an unscoped lookup could render another tenant's name."""
    tree = ast.parse(_code_only(D.get_daily_dispatch))
    assign = next(
        (ast.unparse(n) for n in ast.walk(tree)
         if isinstance(n, ast.Assign)
         and any(getattr(t, "id", None) == "truck_names" for t in n.targets)),
        None,
    )
    assert assign is not None, "truck_names lookup not found"
    assert "Truck.company_id == caller.company_id" in assign


def test_the_prose_regex_is_deleted_not_improved():
    """A better pattern would still parse a human sentence for a machine fact,
    and the sentence will change. "Truck the" is worse than no truck line."""
    s = _read(MOBILE, "screens/Notifications/NotificationsScreen.tsx")
    assert "extractTruckName" not in s
    assert "assigned to" not in s or "match(" not in s


def test_the_hook_returns_the_name():
    s = _read(MOBILE, "hooks/useMyTruck.ts")
    assert "truckName: string | null" in s
    assert "truckName: ta?.truck_name ?? null" in s


def test_the_modal_reads_the_hook_not_the_message():
    s = _read(MOBILE, "screens/Notifications/NotificationsScreen.tsx")
    assert "setTruckName(mine.truckName)" in s


# ── Part 2: every state change updates the summaries ─────────────────────────

@pytest.mark.parametrize("fn_name", ["publish_assignments", "hub_finalize_truck"])
def test_the_missing_paths_now_refresh_the_summaries(fn_name):
    """THE operator-reported gap. hub_finalize_truck touched NONE of the three
    channels, so a per-truck finalize never updated any summary."""
    body = _cog_fn(fn_name)
    assert "_refresh_day_summaries" in body, (
        f"{fn_name} still does not update the standing day summaries"
    )


def test_the_refresh_builds_from_the_whole_day():
    """A standing per-day message edited with one truck's payload drops the
    others (ADR-327 D3).

    Asserted on the ARGUMENTS actually passed. A first version checked only that
    `_day_trucks_summary(` and `api.get_dispatch(` appear somewhere in the body,
    and survived a mutation replacing the fetched crews with `{}` — the exact
    regression this test exists to catch.
    """
    tree = ast.parse(_cog_fn("_refresh_day_summaries"))
    call = next(
        (n for n in ast.walk(tree)
         if isinstance(n, ast.Call)
         and getattr(n.func, "id", None) == "_day_trucks_summary"),
        None,
    )
    assert call is not None, "_day_trucks_summary is never called"
    first = ast.unparse(call.args[0]) if call.args else ""
    assert "assigned_crews" in first, (
        f"the day's crews are not passed in (got {first!r}) — the summary would "
        "be built from nothing and silently drop every truck"
    )
    assert "api.get_dispatch(" in _cog_fn("_refresh_day_summaries")


def test_the_refresh_covers_all_three_channels():
    body = _cog_fn("_refresh_day_summaries")
    for ch in ("drivers_channel", "trainers_channel", "captains_channel"):
        assert ch in body, f"{ch} is not refreshed"


def test_the_empty_guards_survive_the_upsert():
    """ADR-327 D1 — an upsert must not turn "nothing to report" into a posted
    empty embed.

    THIS TEST SHIPPED THE ADR-334 BUG. It asserted `"if embed.fields:" in body`
    — the guard's PRESENCE — while that expression was permanently false,
    because the builder renders into `description` and never calls add_field.
    Presence is not reachability (ADR-333), one day later in a test I wrote
    after writing that lesson.

    Now asserts the guard is bound to a value the builder actually produces.
    """
    body = _cog_fn("_refresh_day_summaries")
    assert "if has_pairings:" in body, "trainers empty-guard lost"
    assert "has_pairings) = await _build_trainers_chat_embed" in body \
        or "has_pairings = await _build_trainers_chat_embed" in body, (
        "the guard is not bound from the builder — it could be permanently false"
    )
    assert "if lines:" in body, "captains empty-guard lost"


def test_the_refresh_never_fails_the_operation():
    """A summary is reporting; it must not fail a finalize that has already
    posted crews and cannot be undone."""
    body = _strip_docstrings(_cog_fn("_refresh_day_summaries"))
    assert "except Exception" in body
    # Grep the CODE: the docstring says "Never raises" and matched itself.
    assert "raise" not in body


def test_the_captains_post_is_upserted_not_bare_sent():
    body = _cog_fn("finalize_assignments")
    assert "captains_channel.send(embed=embed)" not in body
    # ast.unparse normalises the kwarg quoting.
    assert "kind='captains'" in body or 'kind="captains"' in body


# ── The receipt store ────────────────────────────────────────────────────────

def test_the_captains_receipt_column_exists():
    assert "captains_summary_message_id" in {
        c.name for c in DispatchDaySummary.__table__.columns
    }


def test_the_endpoints_accept_the_captains_channel():
    assert "captains" in str(D.DaySummaryMessageRequest.model_fields["channel"].annotation)
    src = _code_only(D.record_day_summary_message)
    assert "row.captains_summary_message_id = value" in src
    assert "captains_summary_message_id" in _code_only(D.get_day_summary_messages)


def test_the_migration_matches_the_model():
    """Dim 3 — a column in the model and not the migration fails on a fresh DB."""
    vers = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "alembic", "versions"))
    hit = [f for f in os.listdir(vers) if "adr332" in f]
    assert hit, "no ADR-332 migration"
    mig = open(os.path.join(vers, hit[0])).read()
    assert "captains_summary_message_id" in mig
    assert "BigInteger" in mig

"""Clearing a day retracts it from Discord too (ADR-328).

clear_daily_dispatch was thorough about the database — ADR-182 and ADR-231
taught it that date-keyed siblings do not cascade — and touched nothing in
Discord. After a clear the guild still showed a crew embed per truck, both day
summaries, and every DM. Discord is where the crew actually looks, so the
authoritative-looking artifact was the stale one.
"""
import ast
import inspect
import os

import pytest

from app.routers import dispatch as D


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


BOT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "bot")


def _bot_source(rel: str) -> str:
    path = os.path.abspath(os.path.join(BOT_DIR, rel))
    if not os.path.exists(path):
        pytest.fail(f"{rel} not found at {path}")
    return open(path).read()


# ── D1: ordering is the design ───────────────────────────────────────────────

def test_the_message_ids_are_collected_before_the_rows_are_deleted():
    """THE invariant.

    crew_embed_message_id is a column ON TruckAssignment. Collect after the
    delete and you hand the bot an empty list, orphan every message
    permanently, and report success — a refactor that moves this later turns the
    whole feature into a silent no-op.
    """
    src = _code_only(D.clear_daily_dispatch)
    collect = src.index("discord_payload")
    delete = src.index("db.delete(a)")
    assert collect < delete, (
        "the ids must be gathered BEFORE the TruckAssignment rows that hold them "
        "are deleted (ADR-328 D1)"
    )


def test_the_bot_is_called_before_the_deletes_too():
    src = _code_only(D.clear_daily_dispatch)
    assert "/internal/clear-day" in src
    assert src.index("internal/clear-day") < src.index("db.delete(a)")


# ── D2: a Discord outage does not block the clear ────────────────────────────

def test_a_dead_bot_does_not_block_the_clear():
    """ADR-324 D1 in the same shape: the operator's intent is "remove this day",
    and a dispatcher who cannot clear a day because a chat bot is down cannot do
    their job."""
    src = _code_only(D.clear_daily_dispatch)
    handler = src[src.index("except aiohttp.ClientError"):]
    handler = handler[:handler.index("assignment_ids") if "assignment_ids" in handler else 900]
    assert "raise" not in handler, "a Discord failure must not fail the clear"
    assert "alert_admins_integration_down" in handler, "but an admin must be told"


def test_the_outcome_is_reported_not_swallowed():
    """A 204 cannot carry a partial failure, so the dispatcher would never learn
    messages were left standing."""
    src = _code_only(D.clear_daily_dispatch)
    assert "'discord_cleared': discord_cleared" in src
    assert "'discord_failures': discord_failures" in src


# ── D3: only what we recorded ────────────────────────────────────────────────

def test_the_bot_deletes_only_recorded_ids_never_a_history_sweep():
    """A bot matching on message SHAPE has unbounded delete authority over a
    customer's guild, and one embed-format change makes it delete the wrong
    things."""
    src = _bot_source("main.py")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "clear_day_messages")
    body = ast.unparse(fn)
    assert "history(" not in body, "no channel history sweep — recorded ids only"
    assert "purge" not in body


def test_dms_are_not_deleted():
    """A DM lives in the recipient's private history and they have already acted
    on it. Retracting it is a surprising amount of authority."""
    src = _bot_source("main.py")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "clear_day_messages")
    body = ast.unparse(fn)
    assert "create_dm" not in body and "send_dm" not in body


def test_an_already_deleted_message_is_not_an_error():
    """Someone tidying by hand produced the desired end state."""
    src = _bot_source("main.py")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "clear_day_messages")
    body = ast.unparse(fn)
    assert "NotFound" in body


# ── D4: every dispatch notification, and the summary receipts ────────────────

def test_all_dispatch_notification_types_are_cleared():
    """It removed only dispatch_assignment. dispatch_finalized is an ADR-179 SSE
    terminal event — leaving it means dashboards still hold "the day was
    finalized" after it was wiped."""
    src = _code_only(D.clear_daily_dispatch)
    for t in ("dispatch_assignment", "dispatch_finalized", "dispatch_no_captain",
              "crew_all_confirmed", "captain_declined"):
        assert t in src, f"{t} survives a clear"


def test_the_types_are_enumerated_not_prefix_matched():
    """`like("dispatch%")` would sweep up an unrelated future notification."""
    src = _code_only(D.clear_daily_dispatch)
    assert "like(" not in src and "startswith" not in src


def test_the_day_summary_receipts_are_deleted():
    """Otherwise the next finalize EDITS a summary for a day that was cleared,
    which looks freshly maintained — worse than a stale post.

    Asserted on a DELETE call specifically. A bare `"DispatchDaySummary" in src`
    passed even with the delete removed, because the name also appears in the
    READ that gathers the ids for the bot — the same false-confidence bug
    ADR-326's mutation run exposed.
    """
    tree = ast.parse(_code_only(D.clear_daily_dispatch))
    deletes = [
        ast.unparse(n) for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and getattr(n.func, "attr", None) == "delete"
        and "DispatchDaySummary" in ast.unparse(n)
    ]
    assert deletes, (
        "the summary receipts are read but never deleted — the next finalize "
        "would edit a summary for a day that was cleared"
    )


# ── Dimension 1 ──────────────────────────────────────────────────────────────

def test_the_channel_lookup_is_company_scoped():
    """Passing a foreign truck's channel would have the bot delete another
    tenant's message."""
    tree = ast.parse(_code_only(D.clear_daily_dispatch))
    lookups = [
        ast.unparse(n) for n in ast.walk(tree)
        if isinstance(n, ast.Assign) and any(
            getattr(t, "id", None) in ("_channels", "_names") for t in n.targets
        )
    ]
    assert lookups, "channel/name lookups not found"
    for src in lookups:
        assert "Truck.company_id == caller.company_id" in src, (
            "an unscoped truck lookup would delete another tenant's messages"
        )


def test_the_summary_lookup_is_company_scoped():
    src = _code_only(D.clear_daily_dispatch)
    block = src[src.index("day_summary ="):src.index("discord_payload")]
    assert "DispatchDaySummary.company_id == caller.company_id" in block

"""A per-truck finalize must reach the bot as a per-truck finalize (ADR-325).

Finalizing Falcon alone posted a crew embed into all six truck rooms, five of
them empty. Not a loop bug: the backend gained a `truck_id` query parameter and
the webhook contract was never widened, so the bot received only
{date, company_id} and did the only thing it could — the whole day.

These tests pin BOTH SIDES of that contract and, crucially, that they agree.
A test of either side alone would have passed while the bug was live.
"""
import ast
import inspect
import os
import re

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


def _bot_source(relpath: str) -> str:
    path = os.path.abspath(os.path.join(BOT_DIR, relpath))
    if not os.path.exists(path):
        pytest.fail(
            f"{relpath} not found at {path} — the bot half of the ADR-325 "
            "contract cannot be verified"
        )
    return open(path).read()


# ── The backend half ─────────────────────────────────────────────────────────

def test_the_backend_sends_truck_id_to_the_finalize_webhook():
    """THE bug. The endpoint scoped itself and told the bot nothing."""
    src = _code_only(D.finalize_dispatch)
    call = src[src.index("/internal/finalize"):]
    call = call[:call.index("timeout")]
    assert "truck_id" in call, (
        "the finalize webhook payload carries no truck_id — the bot cannot "
        "know this was a per-truck finalize and will post to every room"
    )


def test_a_bulk_finalize_still_sends_null_rather_than_omitting_the_key():
    """Explicit None keeps one contract for both callers. An omitted key would
    make 'whole day' and 'malformed request' indistinguishable on the bot side."""
    src = _code_only(D.finalize_dispatch)
    assert "str(truck_id) if truck_id else None" in src


# ── The bot half ─────────────────────────────────────────────────────────────

def test_the_webhook_handler_reads_truck_id():
    src = _bot_source("main.py")
    handler = src[src.index("async def handle_finalize"):]
    handler = handler[:handler.index("async def handle_dm")]
    assert 'data.get("truck_id")' in handler
    assert "trigger_finalize(dispatch_date, company_id, truck_id)" in handler


def test_the_cog_scopes_the_loop_to_the_named_truck():
    src = _bot_source("cogs/dispatch.py")
    fn = src[src.index("async def finalize_assignments"):]
    fn = fn[:fn.index("\n    @") if "\n    @" in fn else len(fn)]
    assert "assigned_crews = {truck_id: assigned_crews[truck_id]}" in fn, (
        "the cog does not narrow assigned_crews — it will iterate every truck"
    )


def test_an_unknown_truck_does_not_widen_to_the_whole_day():
    """The load-bearing guard.

    A missing/unmatched scope silently widening to the maximum IS this bug. If
    the filter is written as a plain `if truck_id in assigned_crews:` with no
    else, an unknown id falls through and posts everywhere — the exact failure,
    reintroduced by a fix that looks correct.
    """
    src = _bot_source("cogs/dispatch.py")
    fn = src[src.index("async def finalize_assignments"):]
    fn = fn[:fn.index("\n    @") if "\n    @" in fn else len(fn)]

    guard = fn[fn.index("if truck_id:"):]
    guard = guard[:guard.index("assigned_crews = {truck_id")]
    assert "return" in guard, (
        "an unknown truck_id must abort, not fall through to the whole day"
    )
    assert "report_error" in guard, "the refusal must be visible to a dispatcher"


# ── The two halves agree ─────────────────────────────────────────────────────

def test_both_sides_use_the_same_key_name():
    """A test of either side alone would have passed while the bug was live:
    the backend was self-consistent and so was the bot. Only the CONTRACT was
    broken, so only a test spanning both catches it."""
    backend = _code_only(D.finalize_dispatch)
    bot = _bot_source("main.py")

    sent = set(re.findall(r'"(\w+)":\s*str\(|"(\w+)":\s*str\(\w+\) if', backend))
    payload = backend[backend.index("/internal/finalize"):]
    payload = payload[:payload.index("timeout")]
    keys_sent = set(re.findall(r"'(\w+)':", payload)) | set(re.findall(r'"(\w+)":', payload))

    handler = bot[bot.index("async def handle_finalize"):]
    handler = handler[:handler.index("async def handle_dm")]
    keys_read = set(re.findall(r'data\.get\("(\w+)"\)', handler))

    unread = keys_sent - keys_read
    assert not unread, (
        f"the backend sends {sorted(unread)} that the bot never reads — "
        "that is how truck_id was lost"
    )

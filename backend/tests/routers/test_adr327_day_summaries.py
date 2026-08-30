"""Day summaries are standing state, not an event stream (ADR-327).

#trainers-chat posted "No trainer-trainee pairings on today's dispatch." twice,
and #drivers-chat carried a stale all-six-trucks table beside the correct
Falcon-only one. Two defects:

  1. the trainer embed posted unconditionally, logging has_fields=0 and sending
     anyway — while the captains block ten lines below has always guarded on
     `if captain_lines:`;
  2. neither summary recorded a message id, so both could only APPEND. Nearly
     invisible while finalize was a whole-day operation; ADR-325 made it
     per-truck, so a six-truck day stacks six contradictory summaries.
"""
import ast
import inspect
import os

import pytest

from app.models.dispatch_day_summary import DispatchDaySummary
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


def _cog_finalize() -> str:
    src = _bot_source("cogs/dispatch.py")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "finalize_assignments")
    return ast.unparse(fn)


# ── D1: silence when there is nothing to say ─────────────────────────────────

def test_an_empty_trainer_embed_is_not_posted():
    """It logged has_fields=0 and sent anyway, so the channel filled with posts
    whose entire content was that there was nothing to report."""
    fn = _cog_finalize()
    assert "if embed.fields:" in fn, (
        "the trainer summary must be guarded on having content, the way the "
        "captains roster already is (ADR-327 D1)"
    )


def test_the_empty_case_is_silent_not_a_nothing_to_report_post():
    """Teaching a channel that most posts are empty is how the one that matters
    gets skimmed past — so the else branch must log, never send.

    An earlier version of this test ended in a conditional expression that
    evaluated to True whenever the string it looked for was absent, i.e. it
    asserted nothing. Walk the AST instead.
    """
    src = _bot_source("cogs/dispatch.py")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "finalize_assignments")
    guard = next(
        (n for n in ast.walk(fn)
         if isinstance(n, ast.If) and "embed.fields" in ast.unparse(n.test)),
        None,
    )
    assert guard is not None, "no `if embed.fields:` guard"
    assert guard.orelse, "no else branch — the empty case is unhandled"
    else_src = "".join(ast.unparse(n) for n in guard.orelse)
    assert "send" not in else_src, (
        "the empty branch posts something; silence is the correct output"
    )
    assert "logger" in else_src, "the empty case should still be logged"


# ── D2: edited in place, not stacked ─────────────────────────────────────────

def test_both_summaries_go_through_the_upsert_not_a_bare_send():
    fn = _cog_finalize()
    assert "_upsert_summary" in fn
    # the old unconditional sends must be gone
    assert "await drivers_channel.send(embed=_build_drivers_chat_embed" not in fn
    assert "await trainers_channel.send(embed=embed)" not in fn


def test_a_deleted_summary_is_reposted_rather_than_breaking_forever():
    """The branch that matters most: a channel someone tidied by hand must not
    permanently break the summary (the ADR-295 D2 fallback)."""
    src = _bot_source("cogs/dispatch.py")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "_upsert_summary")
    body = ast.unparse(fn)
    assert "NotFound" in body, "no fallback when the message is gone"
    assert "channel.send" in body, "the fallback must post a fresh message"
    assert "record_day_summary" in body, "and re-record the new id"


def test_the_upsert_never_fails_the_finalize():
    """A summary is reporting. It must not fail an operation that has already
    posted crews to Discord and cannot be undone."""
    src = _bot_source("cogs/dispatch.py")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "_upsert_summary")
    handlers = [h for h in ast.walk(fn) if isinstance(h, ast.ExceptHandler)]
    assert handlers, "no exception handling at all"
    outermost = ast.unparse(handlers[-1])
    assert "raise" not in outermost


# ── D3: the summary describes the DAY, the crew embeds describe a truck ──────

def test_the_day_summary_is_built_from_every_truck_not_the_scoped_one():
    """trucks_summary is ADR-325-scoped to the finalized truck. Editing a
    standing day summary with that payload would silently drop trucks that
    finalized earlier."""
    fn = _cog_finalize()
    assert "assigned_crews_all" in fn, "the unscoped crews are not preserved"
    assert "_day_trucks_summary(" in fn


def test_adr325_scoping_is_not_reopened():
    """The crew EMBEDS stay per-truck — one room, one truck. Only the day
    summary is day-scoped."""
    fn = _cog_finalize()
    assert "assigned_crews = {truck_id: assigned_crews[truck_id]}" in fn


# ── The receipt store ────────────────────────────────────────────────────────

def test_the_receipt_is_keyed_per_company_day():
    cols = {c.name for c in DispatchDaySummary.__table__.columns}
    assert {"company_id", "date",
            "drivers_summary_message_id", "trainers_summary_message_id"} <= cols
    names = {c.name for c in DispatchDaySummary.__table__.constraints}
    assert "uq_dispatch_day_summary_company_date" in names, (
        "without the unique constraint two concurrent finalizes race to insert"
    )


def test_snowflakes_are_bigint_not_integer():
    """An Integer column silently truncates a Discord snowflake."""
    for col in ("drivers_summary_message_id", "trainers_summary_message_id"):
        assert "BIGINT" in str(DispatchDaySummary.__table__.columns[col].type).upper()


# ── Dimensions 1 and 9 ───────────────────────────────────────────────────────

def test_both_endpoints_are_company_scoped():
    for fn in (D.record_day_summary_message, D.get_day_summary_messages):
        src = _code_only(fn)
        assert "DispatchDaySummary.company_id == caller.company_id" in src, (
            f"{fn.__name__} would read or write another tenant's receipts"
        )


def test_the_request_body_is_typed_and_closed():
    R = D.DaySummaryMessageRequest
    assert R.model_config.get("extra") == "forbid"
    assert "Literal" in str(R.model_fields["channel"].annotation)
    for name, field in R.model_fields.items():
        assert "Any" not in str(field.annotation)
        assert "dict" not in str(field.annotation).lower()


def test_the_clear_sentinel_survives_to_the_column():
    """0 means "the message is gone" — it must land as NULL, not as literal 0,
    or the next finalize tries to edit message 0 forever."""
    src = _code_only(D.record_day_summary_message)
    assert "body.message_id or None" in src


def test_the_write_is_audited():
    src = _code_only(D.record_day_summary_message)
    assert "write_audit" in src and "day_summary_recorded" in src

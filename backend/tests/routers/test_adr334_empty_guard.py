"""The empty-guard tested the wrong emptiness (ADR-334).

My own regression. ADR-327 D1 decided a summary with nothing to say is not
posted — correct. It implemented that as `if embed.fields:`, and
_build_trainers_chat_embed calls add_field ZERO times: it renders its table into
`description`. So the guard was permanently false and the trainer summary was
suppressed on every path, INCLUDING when pairings existed. ADR-332 D4 then
copied it into the shared refresh.

Confirmed on staging: drivers_summary_message_id set, trainers_summary_message_id
None.

Why the tests missed it: `test_the_empty_guards_survive_the_upsert` asserted the
guard was PRESENT, never that it could be TRUE — the same "presence is not
reachability" defect as ADR-333's surviving mutation, one day later.
"""
import ast
import os
import re

import pytest

BOT = os.path.join(os.path.dirname(__file__), "..", "..", "..", "bot")


def _bot_src() -> str:
    p = os.path.abspath(os.path.join(BOT, "cogs", "dispatch.py"))
    if not os.path.exists(p):
        pytest.fail(f"cogs/dispatch.py not found at {p}")
    return open(p).read()


def _fn(name: str) -> str:
    tree = ast.parse(_bot_src())
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name), None)
    assert fn is not None, f"{name} not found"
    return ast.unparse(fn)


def _strip_docstrings(src: str) -> str:
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef, ast.Module)):
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                node.body.pop(0)
    return ast.unparse(tree)


# ── The bug ──────────────────────────────────────────────────────────────────

def test_no_caller_guards_on_a_field_the_builder_never_sets():
    """THE bug. `embed.fields` is always [] for this builder, so the guard was
    permanently false and no trainer summary was ever posted."""
    for caller in ("_refresh_day_summaries", "finalize_assignments"):
        code = _strip_docstrings(_fn(caller))
        assert "embed.fields" not in code, (
            f"{caller} still guards on embed.fields, which this builder never populates"
        )


def test_the_builder_really_does_not_use_fields():
    """The premise of the bug — asserted, so that a future builder switching to
    fields makes this test fail loudly rather than silently re-enabling a guard
    nobody re-checked."""
    code = _strip_docstrings(_fn("_build_trainers_chat_embed"))
    assert "add_field" not in code
    assert "embed.description" in code


# ── D2: the builder reports its own emptiness ────────────────────────────────

def test_the_builder_returns_whether_it_has_pairings():
    """Comparing against the display sentence would couple the caller to copy a
    designer may reword. The producer reports emptiness."""
    code = _strip_docstrings(_fn("_build_trainers_chat_embed"))
    assert "has_pairings = len(rows) > 2" in code
    assert "return (embed, has_pairings)" in code or "return embed, has_pairings" in code


@pytest.mark.parametrize("caller", ["_refresh_day_summaries", "finalize_assignments"])
def test_both_callers_use_the_builders_answer(caller):
    code = _strip_docstrings(_fn(caller))
    assert "has_pairings" in code, f"{caller} ignores the builder's emptiness flag"
    assert "if has_pairings:" in code


# ── Dim 5: the guard is exercised in BOTH directions ─────────────────────────

def test_the_guard_can_actually_be_true():
    """The assertion that would have caught this.

    `if <expr>:` where <expr> is permanently false is indistinguishable, to a
    presence check, from a working guard. This binds the guard's identifier to
    the builder's return so a permanently-false expression cannot satisfy it.
    """
    code = _strip_docstrings(_fn("_refresh_day_summaries"))
    tree = ast.parse(code)
    guard = next(
        (n for n in ast.walk(tree)
         if isinstance(n, ast.If) and "has_pairings" in ast.unparse(n.test)),
        None,
    )
    assert guard is not None, "no guard on has_pairings"
    # the name must be BOUND from the builder in the same function
    assert re.search(r"\(embed, has_pairings\) = await _build_trainers_chat_embed",
                     code) or "embed, has_pairings = await _build_trainers_chat_embed" in code, (
        "has_pairings is guarded on but never bound from the builder"
    )


def test_the_empty_case_still_posts_nothing():
    """ADR-327 D1 must survive: a day with no pairings posts nothing."""
    code = _strip_docstrings(_fn("_refresh_day_summaries"))
    tree = ast.parse(code)
    guard = next(n for n in ast.walk(tree)
                 if isinstance(n, ast.If) and "has_pairings" in ast.unparse(n.test))
    assert not guard.orelse, "an else branch would post on the empty day"
    assert "_upsert_summary" in ast.unparse(guard)


# ── D3: the captains guard was verified, not assumed ─────────────────────────

def test_the_captains_guard_tests_the_list_it_builds():
    """The same class of bug could hide here with an identical symptom."""
    code = _strip_docstrings(_fn("_refresh_day_summaries"))
    assert "lines = _captain_lines(day)" in code
    assert "if lines:" in code

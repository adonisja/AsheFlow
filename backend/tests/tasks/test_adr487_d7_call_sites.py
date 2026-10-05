"""Every Discord send goes through the task, and its kind is one that exists (ADR-487 D7).

WHY A SOURCE-WALKING TEST AND NOT A BEHAVIOURAL ONE
===================================================

The defect this guards is an ABSENCE: somebody adds a Discord send and reaches
for the idiom already in the file —

    threading.Thread(target=_run, daemon=True).start()

— which is what ten sites did, each copied from the last. No request fails, no
test goes red, and the send has no retry and no response check. A behavioural
test cannot see a thread that was never supposed to be there; walking the source
can.

The second half is sharper. `send_discord.delay("crew-embed-updates", ...)` is
well-shaped, correctly spelled, reads exactly like working code, and raises
`ValueError` only when a worker picks it up — in a task, where the traceback
lands in a log nobody is watching. A typo'd `kind` is the Dimension 3 failure
shape applied to a string: valid at import, wrong at runtime.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

APP = pathlib.Path(__file__).resolve().parents[2] / "app"

# The Redis writes in dispatch.py are not Discord and not this decision's scope:
# they run an asyncio loop in a thread to call an async Redis client from sync
# code, a different problem with a different answer (D6).
#
# Exempted by WHAT THE FUNCTION DOES, not by name. The first version of this
# list hardcoded `_fire_redis_clear`, a name I had not read — the real one is
# `_fire_redis_cancel` — so the test failed on a thread that was legitimately
# exempt. A name list is a second source of truth that drifts the moment
# somebody renames a helper; "does the thread body touch the bot?" cannot.
def _thread_body_calls_the_bot(src: str, fn: ast.AST) -> bool:
    seg = ast.get_source_segment(src, fn) or ""
    return "/internal/" in seg

# discord_invite.send_on_first_login. Documented and deliberate: fetch_and_send
# needs the bot's RESPONSE BODY (the invite_url) to then send an email, so it
# cannot be fire-and-forget, and ADR-443 built the resend endpoint precisely
# because this path cannot give itself a second chance. Converting it would mean
# redesigning the invite flow, not moving a call.
_ALLOWED_THREAD_FILES = {"discord_invite.py"}


def _modules():
    for p in sorted(APP.rglob("*.py")):
        yield p, p.read_text()


class TestNoDiscordSendStartsAThread:
    def test_every_remaining_thread_is_accounted_for(self):
        """Ten sites were migrated. This is what stops an eleventh appearing."""
        offenders = []
        for p, src in _modules():
            if p.name == "discord_delivery.py":
                continue   # its docstring quotes the old idiom as the thing it replaced
            tree = ast.parse(src)
            for n in ast.walk(tree):
                if not isinstance(n, ast.Call):
                    continue
                seg = ast.get_source_segment(src, n) or ""
                if "threading.Thread" not in seg:
                    continue
                if p.name in _ALLOWED_THREAD_FILES:
                    continue
                enclosing = [
                    fn for fn in ast.walk(tree)
                    if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and fn.lineno <= n.lineno <= (fn.end_lineno or fn.lineno)
                ]
                if not any(_thread_body_calls_the_bot(src, fn) for fn in enclosing):
                    continue   # not a Discord send — Redis, or something else
                names = sorted({fn.name for fn in enclosing})
                offenders.append(f"{p.relative_to(APP.parent)}:{n.lineno} in {names}")
        assert not offenders, (
            "a Discord send started a daemon thread instead of calling "
            "send_discord.delay(...) — no retry, no response check, and "
            "daemon=True drops it when the container stops:\n  "
            + "\n  ".join(offenders)
        )

    def test_no_module_posts_to_the_bot_directly_with_requests(self):
        """The exemptions are the two that need a RETURN VALUE.

        `mfa_deadline_warnings._send_dm` returns a bool its caller counts, and
        `discord_invite.fetch_and_send` needs the invite_url out of the response
        body. A fire-and-forget task cannot hand either back, so both stay
        synchronous — and both already check the response, which is the property
        that actually mattered.
        """
        allowed = {"mfa_deadline_warnings.py", "discord_invite.py",
                   "discord_bot_invite.py", "integration_health.py"}
        offenders = []
        for p, src in _modules():
            if p.name == "discord_delivery.py" or p.name in allowed:
                continue
            if "/internal/" not in src:
                continue
            for n in ast.walk(ast.parse(src)):
                if isinstance(n, ast.Call):
                    seg = ast.get_source_segment(src, n) or ""
                    if "/internal/" in seg and (
                        "requests.post" in seg or "http_requests.post" in seg
                    ):
                        offenders.append(f"{p.relative_to(APP.parent)}:{n.lineno}")
        assert not offenders, (
            "a direct POST to the bot bypasses the task's retry and response "
            f"classification: {offenders}"
        )


class TestEveryKindIsOneTheTaskAccepts:
    """A typo'd `kind` raises ValueError in a WORKER, not at import.

    This is Dimension 3's failure shape applied to a string: well-formed,
    plausible, and wrong only when something picks it up.
    """

    def test_every_literal_kind_is_declared(self):
        from app.tasks.discord_delivery import KINDS

        found, bad = [], []
        for p, src in _modules():
            for n in ast.walk(ast.parse(src)):
                if not isinstance(n, ast.Call):
                    continue
                f = n.func
                if not (isinstance(f, ast.Attribute) and f.attr == "delay"):
                    continue
                inner = f.value
                name = getattr(inner, "id", getattr(inner, "attr", ""))
                if name != "send_discord" or not n.args:
                    continue
                first = n.args[0]
                if not isinstance(first, ast.Constant) or not isinstance(first.value, str):
                    continue   # a variable kind — covered by the next test
                found.append((str(p.relative_to(APP.parent)), n.lineno, first.value))
                if first.value not in KINDS:
                    bad.append(f"{p.relative_to(APP.parent)}:{n.lineno} kind={first.value!r}")

        assert found, "no literal send_discord.delay call sites found — the walk is broken"
        assert not bad, (
            "a kind not in KINDS raises ValueError inside the worker, where the "
            f"traceback is a log line nobody reads: {bad}\nKINDS={sorted(KINDS)}"
        )

    def test_a_variable_kind_would_escape_the_check_above(self):
        """Recorded rather than enforced: the literal walk above cannot see a
        kind built at runtime, exactly as an earlier AST walk in this work
        missed nine live notification types raised through variables. Today
        every site passes a literal; this test says so, and fails if that
        changes so the gap is noticed rather than assumed away."""
        variable_sites = []
        for p, src in _modules():
            for n in ast.walk(ast.parse(src)):
                if not isinstance(n, ast.Call):
                    continue
                f = n.func
                if not (isinstance(f, ast.Attribute) and f.attr == "delay"):
                    continue
                inner = f.value
                name = getattr(inner, "id", getattr(inner, "attr", ""))
                if name != "send_discord" or not n.args:
                    continue
                if not isinstance(n.args[0], ast.Constant):
                    variable_sites.append(f"{p.relative_to(APP.parent)}:{n.lineno}")
        assert not variable_sites, (
            "a send_discord kind is built at runtime, so the literal check "
            f"above no longer covers it — validate it at the call site: {variable_sites}"
        )


class TestAccessChangesAreAuditedNotStamped:
    def test_revoke_and_role_sync_are_declared_as_access_kinds(self):
        """They have no Notification behind them, so there is no
        delivery_failed_at to stamp. A silently-failed revoke leaves a removed
        crew member reading a truck channel."""
        from app.tasks.discord_delivery import _ACCESS_KINDS, KINDS

        assert _ACCESS_KINDS == {"revoke-member", "role-sync"}
        assert _ACCESS_KINDS <= KINDS, "an access kind the task would reject"

    def test_every_access_send_passes_a_company_id(self):
        """Without it there is no tenant to attribute the audit row to, and an
        audit row with a NULL company_id is invisible to every tenant query."""
        missing = []
        for p, src in _modules():
            tree = ast.parse(src)
            for n in ast.walk(tree):
                if not isinstance(n, ast.Call):
                    continue
                f = n.func
                if not (isinstance(f, ast.Attribute) and f.attr == "delay"):
                    continue
                inner = f.value
                if getattr(inner, "id", getattr(inner, "attr", "")) != "send_discord":
                    continue
                if not n.args or not isinstance(n.args[0], ast.Constant):
                    continue
                if n.args[0].value not in {"revoke-member", "role-sync"}:
                    continue
                if not any(kw.arg == "company_id" for kw in n.keywords):
                    missing.append(f"{p.relative_to(APP.parent)}:{n.lineno}")
        assert not missing, (
            f"an access-change send with no company_id to audit against: {missing}"
        )

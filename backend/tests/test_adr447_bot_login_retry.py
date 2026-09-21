"""ADR-447: an invalid token must not be retried; a retryable one must back off.

THE INCIDENT: a container held a stale token, `bot.start` raised LoginFailure,
the process exited non-zero, and `restart: unless-stopped` restarted it
instantly — 13,999 times. Discord counted the logins and reset our token.

The retry POLICY is imported and executed (bot/services/login_retry.py is pure
and has no discord.py dependency — the backend test environment has no such
module). The STRUCTURE of main.py's handler is read with AST, because importing
it would need discord.py and the point of extracting the policy was that logic
no test can execute is what caused this.

The backoff tests assert on the DISTRIBUTION: the property that matters —
clients do not retry in lockstep — is invisible in any single delay.
"""
import ast
import pathlib
import sys

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
BOT_MAIN = ROOT / "bot" / "main.py"
COMPOSE = ROOT / "docker-compose.yml"

sys.path.insert(0, str(ROOT / "bot"))
from services.login_retry import (  # noqa: E402
    MAX_LOGIN_ATTEMPTS,
    RETRY_BASE_SECONDS,
    RETRY_CAP_SECONDS,
    backoff_delay,
    is_last_attempt,
)


class TestTheBackoffIsExponentialWithFullJitter:
    def test_the_ceiling_doubles_each_attempt(self):
        """Exponential, not linear — a linear ramp is 8 attempts in ~72s."""
        for attempt in range(6):
            expected = min(RETRY_BASE_SECONDS * (2 ** attempt), RETRY_CAP_SECONDS)
            draws = [backoff_delay(attempt) for _ in range(200)]
            assert max(draws) <= expected + 1e-9, \
                f"attempt {attempt} exceeded its ceiling {expected}"
            # 200 draws from U(0, ceiling) land the max near the ceiling; far
            # below would mean the ceiling is not what it claims.
            assert max(draws) > expected * 0.5

    def test_the_ceiling_is_capped(self):
        """Without a cap, attempt 20 would be weeks."""
        assert max(backoff_delay(20) for _ in range(100)) <= RETRY_CAP_SECONDS

    def test_the_jitter_is_full_not_a_narrow_band(self):
        """THE POINT OF THE JITTER.

        A ±10% band keeps every client retrying at roughly the same moment, so
        a Discord outage ends in a thundering herd on recovery. Full jitter
        spreads attempts across the whole interval.

        Asserted as a distribution: draws must reach both the bottom and the
        top of the range, which a narrow band around the ceiling cannot do.
        """
        ceiling = min(RETRY_BASE_SECONDS * (2 ** 4), RETRY_CAP_SECONDS)
        draws = [backoff_delay(4) for _ in range(500)]
        assert min(draws) < ceiling * 0.1, (
            "no draw landed in the bottom 10% — this is a narrow band, not full "
            "jitter, and synchronised clients still retry in lockstep"
        )
        assert max(draws) > ceiling * 0.9, "no draw landed in the top 10%"

    def test_delays_are_not_all_identical(self):
        """A constant delay is the behaviour this replaces."""
        assert len({backoff_delay(3) for _ in range(50)}) > 40

    def test_the_draw_is_injectable_so_the_bound_is_exact(self):
        """Pinning the RNG proves the ceiling arithmetic, not just its spread."""
        assert backoff_delay(0, rand=lambda lo, hi: hi) == RETRY_BASE_SECONDS
        assert backoff_delay(3, rand=lambda lo, hi: hi) == RETRY_BASE_SECONDS * 8
        assert backoff_delay(99, rand=lambda lo, hi: hi) == RETRY_CAP_SECONDS
        assert backoff_delay(5, rand=lambda lo, hi: lo) == 0.0

    def test_a_negative_attempt_is_refused(self):
        """Silently returning a tiny delay would be a retry storm."""
        with pytest.raises(ValueError):
            backoff_delay(-1)

    def test_only_the_final_attempt_is_last(self):
        assert not is_last_attempt(0)
        assert not is_last_attempt(MAX_LOGIN_ATTEMPTS - 2)
        assert is_last_attempt(MAX_LOGIN_ATTEMPTS - 1)


class TestAPermanentFailureIsNotRetried:
    """Structure, via AST — importing main.py needs discord.py."""

    def _run_bot(self):
        tree = ast.parse(BOT_MAIN.read_text())
        return next(n for n in ast.walk(tree)
                    if isinstance(n, ast.AsyncFunctionDef) and n.name == "_run_bot")

    def test_login_failure_is_caught_separately_from_generic_errors(self):
        """A bad token and a network blip must not share a handler.

        Retrying the first is what triggered the reset; not retrying the second
        would make the bot fragile.
        """
        handlers = [h for h in ast.walk(self._run_bot())
                    if isinstance(h, ast.ExceptHandler)]
        caught = " ".join(ast.dump(h.type) for h in handlers if h.type)
        assert "LoginFailure" in caught, (
            "_run_bot does not catch LoginFailure separately — a bad token "
            "would fall into the retry branch (ADR-447 D1)"
        )
        assert "PrivilegedIntentsRequired" in caught, (
            "a missing intent is equally unfixable at runtime and must not retry"
        )

    def test_the_permanent_handler_returns_zero(self):
        """Exit 0 so `restart:` does NOT restart — Docker restarts on non-zero."""
        handler = next(
            h for h in ast.walk(self._run_bot())
            if isinstance(h, ast.ExceptHandler) and h.type
            and "LoginFailure" in ast.dump(h.type)
        )
        returns = [n.value.value for n in ast.walk(handler)
                   if isinstance(n, ast.Return) and isinstance(n.value, ast.Constant)]
        assert returns == [0], (
            f"the permanent-failure handler returns {returns}, not [0]. A "
            "non-zero exit is what Docker restarts — that is the loop "
            "(ADR-447 D1)."
        )

    def test_the_permanent_handler_does_not_sleep_or_continue(self):
        """One attempt only. Retrying a bad token is the incident."""
        handler = next(
            h for h in ast.walk(self._run_bot())
            if isinstance(h, ast.ExceptHandler) and h.type
            and "LoginFailure" in ast.dump(h.type)
        )
        body = ast.dump(handler)
        assert "sleep" not in body, "the permanent handler backs off — it must not retry"
        assert "Continue" not in body, "the permanent handler continues the retry loop"

    def test_the_log_names_the_remedy(self):
        """'Improper token' alone sent nobody to SSM. The log must say where."""
        src = BOT_MAIN.read_text()
        block = src[src.index("except (discord.LoginFailure"):][:1200]
        assert "DISCORD_BOT_TOKEN" in block
        assert "NOT retrying" in block


class TestARetryableFailureBacksOffAndGivesUp:
    def _run_bot(self):
        tree = ast.parse(BOT_MAIN.read_text())
        return next(n for n in ast.walk(tree)
                    if isinstance(n, ast.AsyncFunctionDef) and n.name == "_run_bot")

    def test_the_generic_handler_sleeps_with_the_backoff(self):
        src = BOT_MAIN.read_text()
        assert "backoff_delay(attempt)" in src, \
            "the retry branch does not use the jittered backoff (ADR-447 D2)"

    def test_giving_up_is_nonzero(self):
        """So the orchestrator and the health probe both see a failure."""
        fn = self._run_bot()
        returns = {n.value.value for n in ast.walk(fn)
                   if isinstance(n, ast.Return) and isinstance(n.value, ast.Constant)}
        assert 1 in returns, "_run_bot never returns 1 — exhaustion looks like success"
        assert 0 in returns, "_run_bot never returns 0 — the permanent path is gone"

    def test_cancellation_is_not_treated_as_a_failure(self):
        """SIGTERM during a deploy must not burn retry attempts."""
        handlers = [h for h in ast.walk(self._run_bot())
                    if isinstance(h, ast.ExceptHandler) and h.type]
        caught = " ".join(ast.dump(h.type) for h in handlers)
        assert "CancelledError" in caught, (
            "a deploy's SIGTERM falls into the retry branch and sleeps "
            "(ADR-447 D2)"
        )


class TestTheRestartPolicyIsBounded:
    def test_the_bot_service_caps_its_restarts(self):
        """`unless-stopped` has maxretry=0 — unbounded, which reached 13,999."""
        compose = yaml.safe_load(COMPOSE.read_text())
        policy = compose["services"]["bot"].get("restart", "")
        assert policy.startswith("on-failure:"), (
            f"bot restart policy is {policy!r}; an uncapped policy can produce "
            "an unbounded login loop (ADR-447 D3)"
        )
        limit = int(policy.split(":")[1])
        assert 0 < limit <= 10, f"retry limit {limit} is not a meaningful cap"

    def test_main_exits_through_the_retry_wrapper(self):
        """A bare `bot.start` in main() bypasses every decision above."""
        tree = ast.parse(BOT_MAIN.read_text())
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.AsyncFunctionDef) and n.name == "main")
        called = {n.func.id for n in ast.walk(fn)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        assert "_run_bot" in called, \
            "main() no longer goes through the retry wrapper (ADR-447)"

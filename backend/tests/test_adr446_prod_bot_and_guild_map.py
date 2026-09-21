"""ADR-446: prod runs the bot, and the guild map is warmed before events.

Two failures are pinned here, and neither raises anything at runtime:

  D1  the prod deploy removed `asheflow_bot` and never started it. Every bot
      call site fails soft, so dispatch reports success and delivers nothing.
  D2  `_guild_to_company` was filled only as a side effect of ordinary traffic,
      so after a restart `on_member_join` assigned no roles and logged at debug.

Both are read from source (AST and text) rather than executed: the workflow is
YAML, and the bot needs a Discord connection to run. That is the same approach
as tests/routers/test_adr362_bot_auth_challenge.py.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CI = ROOT / ".github" / "workflows" / "ci.yml"
BOT_MAIN = ROOT / "bot" / "main.py"
GUILD_CFG = ROOT / "bot" / "services" / "guild_config.py"
INTERNAL = ROOT / "backend" / "app" / "routers" / "internal.py"


def _deploy_lines() -> list[str]:
    return [ln.strip() for ln in CI.read_text().splitlines()
            if "up -d postgres redis backend" in ln]


class TestProdStartsTheBot:
    def test_both_environments_start_the_bot(self):
        """Staging and prod must agree.

        They differed by one word for months: staging ended `caddy bot`, prod
        ended `caddy`. Nothing failed because prod had not launched.
        """
        lines = _deploy_lines()
        assert len(lines) == 2, (
            f"expected 2 deploy lines (staging + prod), found {len(lines)}. "
            "If a third environment was added it needs the bot too (ADR-446)."
        )
        missing = [ln for ln in lines if not ln.rstrip('"').endswith("bot")]
        assert not missing, (
            "a deploy line starts the stack without the bot container. Every "
            "bot call site fails soft, so dispatch would report success and "
            "deliver nothing to Discord (ADR-446 D1):\n  " + "\n  ".join(missing)
        )

    def test_the_bot_container_is_not_removed_without_being_restarted(self):
        """`docker rm -f asheflow_bot` is only safe if something starts it again."""
        text = CI.read_text()
        removes = text.count("asheflow_bot")
        assert removes > 0, "the deploy no longer cleans up the bot container"
        for line in _deploy_lines():
            assert " bot" in line, (
                "asheflow_bot is force-removed but a deploy line does not "
                "bring it back (ADR-446 D1)"
            )


class TestTheGuildMapIsWarmed:
    def test_on_ready_warms_the_map(self):
        """The map must be populated BEFORE any event is handled.

        Without this, a member joining right after a restart gets no roles and
        leaves only a debug line — indistinguishable from "Discord is not set
        up for this company".
        """
        tree = ast.parse(BOT_MAIN.read_text())
        fn = next((n for n in ast.walk(tree)
                   if isinstance(n, ast.AsyncFunctionDef) and n.name == "on_ready"), None)
        assert fn is not None, "on_ready is gone — did the bot class change?"
        called = {
            n.func.id for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }
        assert "warm_guild_map" in called, (
            "on_ready does not warm the guild map, so on_member_join will skip "
            "role assignment after every restart (ADR-446 D2)"
        )

    def test_joining_a_guild_maps_it_immediately(self):
        """Onboarding a company IS joining a guild.

        Warming only at startup would leave a newly onboarded company unmapped
        until the next restart — the launch path, not an edge case.
        """
        tree = ast.parse(BOT_MAIN.read_text())
        fn = next((n for n in ast.walk(tree)
                   if isinstance(n, ast.AsyncFunctionDef) and n.name == "on_guild_join"), None)
        assert fn is not None, (
            "no on_guild_join handler — a guild joined at runtime stays "
            "unmapped until the bot restarts (ADR-446 D2)"
        )
        called = {
            n.func.id for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }
        assert "warm_guild_map" in called

    def test_warming_never_stops_the_bot_starting(self):
        """Best effort by design.

        A backend that is slow at bot startup must not prevent the bot from
        coming up: a failed warm leaves exactly the pre-ADR behaviour, which is
        strictly better than not running at all.
        """
        tree = ast.parse(BOT_MAIN.read_text())
        for name in ("on_ready", "on_guild_join"):
            fn = next(n for n in ast.walk(tree)
                      if isinstance(n, ast.AsyncFunctionDef) and n.name == name)
            guarded = any(
                isinstance(h, ast.Try)
                and any("warm_guild_map" in ast.dump(b) for b in h.body)
                for h in ast.walk(fn)
            )
            assert guarded, f"{name} calls warm_guild_map outside a try (ADR-446 D2)"

    def test_the_warm_is_idempotent(self):
        """Called at startup AND on join, so it must not re-ask for known guilds."""
        src = GUILD_CFG.read_text()
        assert "if guild_id in _guild_to_company" in src, (
            "warm_guild_map re-fetches guilds it already knows; it runs on "
            "every join as well as at startup (ADR-446 D2)"
        )


class TestTheLookupEndpoint:
    def test_guild_owner_is_gated_and_rate_limited(self):
        """Same gate as every internal route, plus a limit.

        ADR-441 widened what INTERNAL_SECRET is worth: a leaked secret probing
        guild ids must not enumerate the tenant estate quickly.
        """
        tree = ast.parse(INTERNAL.read_text())
        fn = next((n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef) and n.name == "get_guild_owner"), None)
        assert fn is not None, "GET /internal/guild-owner/{guild_id} is missing (ADR-446 D2)"
        deco_src = " ".join(ast.dump(d) for d in fn.decorator_list)
        assert "_verify_secret" in deco_src, "guild-owner is not behind _verify_secret"
        assert "limit" in deco_src, "guild-owner is not rate limited (ADR-446 D2)"

    def test_there_is_no_endpoint_listing_every_company_guild(self):
        """The rejected alternative, pinned.

        A "list all companies and their guilds" route would hand anyone holding
        INTERNAL_SECRET a complete tenant roster in one request. Asking per
        guild returns only what the caller could see by being in the guild.
        """
        src = INTERNAL.read_text()
        for banned in ("/guild-owners", "/guilds", "/all-guilds"):
            assert banned not in src, (
                f"{banned} enumerates tenants in one call — ADR-446 D2 chose a "
                "per-guild lookup deliberately"
            )

    def test_an_ambiguous_guild_is_refused_not_guessed(self):
        """discord_guild_id has NO unique constraint.

        Two companies can be configured with the same guild id. `.first()`
        would silently resolve members of one tenant's guild to the other
        tenant's company — a cross-tenant mix-up that looks like working
        software rather than failing.
        """
        tree = ast.parse(INTERNAL.read_text())
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "get_guild_owner")
        body = ast.dump(fn)
        assert "'first'" not in body, (
            "get_guild_owner uses .first(), which silently picks one of several "
            "companies claiming a guild (ADR-446 D2)"
        )
        assert "HTTP_409_CONFLICT" in body, (
            "an ambiguous guild must be refused, not resolved arbitrarily"
        )

    def test_the_conflict_does_not_leak_tenant_names(self):
        """Dimension 7 at the error path.

        The caller is entitled to know the mapping is broken, not to a list of
        tenants. Ids go to the log; the response says nothing specific.
        """
        src = INTERNAL.read_text()
        start = src.index("def get_guild_owner")
        body = src[start:start + 2000]
        detail_line = next(
            (ln for ln in body.splitlines() if "detail=" in ln and "claimed" in ln), ""
        )
        assert "name" not in detail_line.lower(), (
            "the 409 detail appears to expose company names (ADR-446 / Dim 7)"
        )


class TestTheLookupActuallyRuns:
    """The gap that let an AttributeError reach production.

    Every other test in this file reads source with AST. That proved the
    endpoint was gated, rate limited and used `.all()` — and said nothing about
    whether the query could execute. `Company` and `CompanyConfig` live in the
    same module, `discord_guild_id` is on the SECOND one, and the endpoint
    referenced the first: a 500 on every call, with all 10 source tests green.

    These execute the route.
    """

    def _client(self, monkeypatch, rows):
        """A throwaway app whose session returns `rows` from the lookup query.

        No real schema: this test exists to prove the ROUTE RUNS — that the
        model attribute it references exists and the handler reaches its 404 or
        409. A stub session proves exactly that and nothing about SQLite, which
        is what turned the first three attempts at this fixture into a fight
        with table creation rather than a test of the endpoint.

        Not `app.main.app`: that object is shared process-wide, and a
        dependency_overrides entry left by any of 4000 other tests wins over one
        set here — which is why an earlier version passed alone and failed in a
        full run.
        """
        from unittest.mock import MagicMock
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.api.deps import get_db
        from app.routers import internal as I
        from slowapi import _rate_limit_exceeded_handler
        from slowapi.errors import RateLimitExceeded
        from app.api.ratelimit import limiter

        monkeypatch.setenv("INTERNAL_SECRET", "test-secret-for-route")
        # _INTERNAL_SECRET is bound at import time, so patch the value too.
        monkeypatch.setattr(I, "_INTERNAL_SECRET", "test-secret-for-route")

        session = MagicMock()
        session.query.return_value.filter.return_value.all.return_value = rows

        # THE LIMITER IS SWITCHED OFF for these tests, and it has to be done on
        # the shared object: @limiter.limit captured it at import time, so
        # pointing app.state at a different Limiter changes nothing.
        #
        # Its storage is Redis wherever Redis is reachable -- true in CI, and
        # true here too -- so the 30/min counter is SHARED AND PERSISTENT across
        # the whole suite. Once spent, these tests get 429 where they assert
        # 200/404/409, and a bare app has no RateLimitExceeded handler so it
        # surfaces as 500. That is exactly how this passed locally and failed in
        # CI: the counter had been consumed there and not here.
        #
        # The limit itself is pinned by test_guild_owner_is_gated_and_rate_limited,
        # which reads the decorator -- the right tool for "is it limited". These
        # tests are for "does the route run".
        monkeypatch.setattr(limiter, "enabled", False)

        local = FastAPI()
        local.state.limiter = limiter          # the @limiter.limit decorator needs this
        # The real app registers this (main.py:53). Without it a tripped limit
        # raises RateLimitExceeded uncaught and surfaces as a 500 -- which is
        # what happened in CI, where Redis IS reachable so the limiter uses
        # shared storage and the 30/min counter survives across the suite.
        # Locally Redis is absent, the limiter falls back to in-memory, and the
        # counter never trips: green locally, red in CI.
        local.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
        local.include_router(I.router, prefix="/api/v1")
        local.dependency_overrides[get_db] = lambda: session
        # raise_server_exceptions=True so a failure surfaces the ACTUAL
        # exception. With it False the assertion only ever says "500", which is
        # exactly as uninformative in CI as the bug this file exists to catch.
        return TestClient(local, raise_server_exceptions=True)

    def test_an_unknown_guild_returns_404_not_500(self, monkeypatch):
        """The bug exactly: the query must be runnable, not merely well-shaped."""
        c = self._client(monkeypatch, rows=[])
        r = c.get("/api/v1/internal/guild-owner/1",
                  headers={"X-Internal-Secret": "test-secret-for-route"})
        assert r.status_code != 500, (
            f"guild-owner raised a server error: {r.text[:200]}. The query does "
            "not execute — check that discord_guild_id is read from "
            "CompanyConfig, not Company (ADR-446)."
        )
        assert r.status_code == 404

    def test_two_companies_on_one_guild_returns_409(self, monkeypatch):
        """The D4 path, executed rather than read.

        With no unique constraint this is reachable, and a 500 here would be
        just as wrong as silently picking one.
        """
        from unittest.mock import MagicMock
        a, b = MagicMock(), MagicMock()
        a.company_id, b.company_id = "aaa", "bbb"
        c = self._client(monkeypatch, rows=[a, b])
        r = c.get("/api/v1/internal/guild-owner/1",
                  headers={"X-Internal-Secret": "test-secret-for-route"})
        assert r.status_code == 409, f"expected 409, got {r.status_code}: {r.text[:200]}"
        assert "aaa" not in r.text and "bbb" not in r.text, \
            "the 409 body leaks tenant identifiers (Dim 7)"

    def test_one_company_resolves(self, monkeypatch):
        """The happy path must return company_id, not the config row's own id."""
        from unittest.mock import MagicMock
        row = MagicMock()
        row.company_id = "the-company"
        c = self._client(monkeypatch, rows=[row])
        r = c.get("/api/v1/internal/guild-owner/1",
                  headers={"X-Internal-Secret": "test-secret-for-route"})
        assert r.status_code == 200, r.text[:200]
        assert r.json()["company_id"] == "the-company"

    def test_a_bad_secret_is_still_refused(self, monkeypatch):
        c = self._client(monkeypatch, rows=[])
        r = c.get("/api/v1/internal/guild-owner/1",
                  headers={"X-Internal-Secret": "wrong"})
        assert r.status_code in (401, 403)

    def test_the_response_carries_the_company_id_not_the_config_id(self):
        """CompanyConfig has its own primary key.

        Returning `.id` would hand the bot an identifier that resolves to
        nothing — every subsequent guild-config fetch would 404, and the guild
        would look unconfigured rather than broken.
        """
        # AST, not a character slice: a fixed-width window silently missed the
        # return line as soon as a comment was added above it.
        tree = ast.parse(INTERNAL.read_text())
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "get_guild_owner")
        returns = [n for n in ast.walk(fn) if isinstance(n, ast.Return) and n.value]
        # The ATTRIBUTE NAMES read inside the return, not a dump substring --
        # ast.dump output is long enough that a naive `in` check reads whatever
        # happened to fit.
        attrs = {n.attr for r in returns for n in ast.walk(r)
                 if isinstance(n, ast.Attribute)}
        assert "company_id" in attrs and "id" not in (attrs - {"company_id"}), (
            "guild-owner returns the CompanyConfig row's own id rather than "
            "company_id (ADR-446)"
        )

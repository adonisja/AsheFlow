"""ADR-448: the bot must be invited before a guild id means anything.

THE GAP: Company Settings asks for a Server ID and fourteen channel/role ids.
Every one can be correct and Discord still does nothing, because `get_guild()`
reads the bot's own list of JOINED servers and only a server admin can authorise
it. Before this ADR the OAuth URL existed nowhere in the product — the failure
surfaced as DiscordInviteError("bot", "Check Discord settings"), which is
accurate about the stage and misleading about the remedy.
"""
import ast
import pathlib
from unittest.mock import MagicMock, patch

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
COMPANIES = ROOT / "backend" / "app" / "routers" / "companies.py"
SETTINGS_TSX = ROOT / "frontend" / "src" / "pages" / "CompanySettings.tsx"
BOT_MAIN = ROOT / "bot" / "main.py"

from app.services import discord_bot_invite as S  # noqa: E402


class TestTheInviteUrl:
    def test_it_carries_both_required_scopes(self):
        """`bot` alone joins the server but registers no slash commands.

        /setup would silently never appear, which is indistinguishable from the
        bot being absent — the exact confusion this ADR removes.
        """
        url = S.build_invite_url("123")
        assert "client_id=123" in url
        assert "bot" in url and "applications.commands" in url

    def test_it_is_built_from_the_running_bots_application_id(self):
        """NOT a constant.

        Staging and prod are different Discord applications. A build-time id
        would send prod admins to invite the staging bot, and the settings would
        look correct while nothing worked.
        """
        src = (ROOT / "backend" / "app" / "services" / "discord_bot_invite.py").read_text()
        tree = ast.parse(src)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "get_status")
        called = {n.func.id for n in ast.walk(fn)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        assert "build_invite_url" in called
        # and the id must come from the response, not a literal
        assert "application_id" in ast.dump(fn)


class TestStatusDegradesRatherThanFailing:
    def _resp(self, payload):
        r = MagicMock()
        r.json.return_value = payload
        r.raise_for_status.return_value = None
        return r

    def test_an_unreachable_bot_gives_none_not_false(self):
        """"Could not ask" and "it is not there" are DIFFERENT facts.

        Collapsing them puts a red cross next to a correct configuration every
        time the bot restarts during a deploy.
        """
        with patch.object(S.requests, "get", side_effect=OSError("down")):
            st = S.get_status(123)
        assert st.in_guild is None, "an unreachable bot must not report 'not in guild'"
        assert st.invite_url is None
        assert st.ready is False

    def test_a_present_bot_reports_true(self):
        with patch.object(S.requests, "get", return_value=self._resp(
                {"application_id": "9", "in_guild": True, "ready": True})):
            st = S.get_status(123)
        assert st.in_guild is True
        assert st.invite_url and "client_id=9" in st.invite_url

    def test_an_absent_bot_reports_false_with_a_link(self):
        """The state the whole ADR exists for: correct ids, bot not authorised."""
        with patch.object(S.requests, "get", return_value=self._resp(
                {"application_id": "9", "in_guild": False, "ready": True})):
            st = S.get_status(123)
        assert st.in_guild is False
        assert st.invite_url, "an absent bot must come with the link to fix it"


class TestTheEmailFiresOnTheTransitionOnly:
    """ADR-448 D4. Automatic, but ONCE."""

    def _caller(self, company_id="c1", email="admin@example.com"):
        c = MagicMock()
        c.company_id, c.email, c.name, c.id = company_id, email, "Admin", "e1"
        return c

    def _send(self, old, new, *, in_guild=False, url="https://discord/x"):
        from app.routers import companies as C
        st = S.BotGuildStatus(invite_url=url, in_guild=in_guild, ready=True)
        with patch.object(S, "get_status", return_value=st), \
             patch("app.services.email.send_bot_setup_email") as send:
            C._maybe_send_bot_setup_email(
                db=MagicMock(), caller=self._caller(),
                old_guild_id=old, new_guild_id=new,
            )
        return send

    def test_it_sends_when_a_guild_id_is_first_set(self):
        assert self._send(None, 555).called

    def test_it_does_not_send_when_the_guild_id_is_unchanged(self):
        """An admin adjusting channel ids must not get this email each save."""
        assert not self._send(555, 555).called

    def test_it_does_not_send_when_the_guild_id_is_cleared(self):
        assert not self._send(555, None).called

    def test_a_replacement_server_does_send_again(self):
        """A new guild is a new transition — the bot is not in that one either."""
        assert self._send(555, 777).called

    def test_it_does_not_send_when_the_bot_is_already_in_the_guild(self):
        """The step is done. Telling someone to do it anyway is how a sender
        becomes noise."""
        assert not self._send(None, 555, in_guild=True).called

    def test_it_does_not_send_without_a_usable_link(self):
        """Guessing a URL risks sending prod admins to the staging bot."""
        assert not self._send(None, 555, url=None).called

    def test_a_send_failure_does_not_raise(self):
        """A failed email must not roll back a SAVED configuration.

        The settings page shows the link too, so email is the reminder, not the
        only route.
        """
        from app.routers import companies as C
        st = S.BotGuildStatus(invite_url="https://x", in_guild=False, ready=True)
        with patch.object(S, "get_status", return_value=st), \
             patch("app.services.email.send_bot_setup_email",
                   side_effect=RuntimeError("SES down")):
            C._maybe_send_bot_setup_email(
                db=MagicMock(), caller=self._caller(),
                old_guild_id=None, new_guild_id=555,
            )   # must not raise


class TestTheSettingsPageLeadsWithTheInvite:
    def test_the_connect_panel_renders_before_the_id_fields(self):
        """Screen order is operation order (D1)."""
        src = SETTINGS_TSX.read_text()
        panel = src.index("Connect the AsheFlow bot")
        channels = src.index('title="Discord — Channels"')
        assert panel < channels, (
            "the id fields render above the connect action — an admin fills in "
            "fifteen ids before learning the bot is not in the server (ADR-448 D1)"
        )

    def test_the_three_states_are_rendered_distinctly(self):
        """null must not render as 'not connected'."""
        src = SETTINGS_TSX.read_text()
        assert "bot_in_guild === true" in src
        assert "bot_in_guild === false" in src
        assert "bot_in_guild == null" in src, (
            "no branch for 'could not ask' — a restarting bot would show as "
            "not connected (ADR-448 D3)"
        )

    def test_the_link_is_hidden_once_the_bot_is_in(self):
        src = SETTINGS_TSX.read_text()
        assert "bot_in_guild !== true" in src, \
            "the authorise link shows even when the bot is already connected"


class TestTheBotExposesItsMembership:
    def test_the_endpoint_is_secret_gated(self):
        """Unlike /internal/health, this names a specific guild."""
        src = BOT_MAIN.read_text()
        start = src.index("async def handle_guild_status")
        body = src[start:start + 900]
        assert "_check_secret" in body, \
            "guild-status is unauthenticated — whether we are in someone's server is not public"

    def test_it_is_registered(self):
        assert '"/internal/guild-status"' in BOT_MAIN.read_text()

    def test_a_malformed_guild_id_is_a_client_error(self):
        """400, not 'the bot is missing' — a typo must not read as a missing bot.

        AST rather than a character window: a fixed-width slice silently missed
        this branch once already, which is the same failure mode as reading a
        grep hit's line number without checking what encloses it.
        """
        fn = next(n for n in ast.walk(ast.parse(BOT_MAIN.read_text()))
                  if isinstance(n, ast.AsyncFunctionDef)
                  and n.name == "handle_guild_status")
        body = ast.dump(fn)
        assert "ValueError" in body, \
            "a non-numeric guild_id is unhandled and would 500"
        assert "400" in body, \
            "a malformed guild_id does not return 400 (ADR-448 D3)"

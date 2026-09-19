"""The Discord invite gets a second chance (ADR-443).

It fires once, inside the block that flips an employee to `active` on first
login — so the status change that triggers it is what closes the guard. It runs
on a daemon thread where every failure is swallowed, and nothing records the
outcome. An employee whose invite failed is `active`, looks normal, and is
simply absent from Discord.
"""
import inspect

import pytest


class TestOneImplementationForBothCallers:
    def test_first_login_and_the_endpoint_share_the_send(self):
        """Two implementations would drift, and the one nobody exercises by
        hand is the login path."""
        from app.api import deps
        from app.routers import employees
        from app.services import discord_invite

        assert "send_on_first_login" in inspect.getsource(deps)
        assert "discord_invite.fetch_and_send" in inspect.getsource(
            employees.resend_discord_invite)
        assert "fetch_and_send" in inspect.getsource(discord_invite.send_on_first_login)

    def test_the_login_path_still_swallows_failures(self):
        """Correct there: nobody is waiting on that thread, and an exception
        raised in it cannot reach the request that started it. This is what the
        resend endpoint exists to compensate for, not something to 'fix'."""
        from app.services.discord_invite import send_on_first_login

        src = inspect.getsource(send_on_first_login)
        assert "except DiscordInviteError" in src
        assert "threading.Thread" in src
        assert "daemon=True" in src


class TestTheFailureNamesItsStage:
    """A bot failure sends an operator to Discord settings; an email failure to
    the address or the SES sandbox. One opaque error sends them to both."""

    def test_a_bot_failure_is_distinguishable_from_an_email_one(self):
        from app.services.discord_invite import DiscordInviteError, fetch_and_send

        # Parsed, not string-matched: the stage argument sits on a
        # continuation line for the multi-line raises, so a single-line match
        # finds only the short one and passes for the wrong reason.
        import ast

        stages = {
            node.args[0].value
            for node in ast.walk(ast.parse(inspect.getsource(fetch_and_send).lstrip()))
            if isinstance(node, ast.Call)
            and getattr(node.func, "id", "") == "DiscordInviteError"
            and node.args and isinstance(node.args[0], ast.Constant)
        }
        assert stages == {"bot", "email"}, f"stages raised: {stages}"

        err = DiscordInviteError("bot", "nope")
        assert err.stage == "bot" and err.detail == "nope"

    def test_no_email_is_refused_before_calling_the_bot(self):
        """Asking the bot for an invite we cannot deliver wastes a call and
        reports the wrong stage."""
        from app.services.discord_invite import DiscordInviteError, fetch_and_send

        class _E:
            email = None
            name = "No Email"
            company_id = "c"

        with pytest.raises(DiscordInviteError) as exc:
            fetch_and_send(_E())
        assert exc.value.stage == "email"
        assert "No email" in exc.value.detail


class TestTheEndpointIsScopedAndAudited:
    def test_it_is_company_scoped(self):
        """Dim 1. A management caller must not resend for another tenant."""
        src = inspect.getsource(
            __import__("app.routers.employees", fromlist=["x"]).resend_discord_invite)
        assert "Employee.company_id == caller.company_id" in src

    def test_it_is_gated_to_management_and_admin(self):
        import app.routers.employees as E

        params = inspect.signature(E.resend_discord_invite).parameters
        gates = [p.default for p in params.values()]
        assert any("RoleChecker" in repr(g) for g in gates)

    def test_the_audit_does_not_record_the_address(self):
        """Dim 7. ADR-336 D1 made the same call for the delivery alert: the
        address is the payload of the thing that was sent, not something the
        audit needs to identify the action."""
        import app.routers.employees as E

        src = inspect.getsource(E.resend_discord_invite)
        detail = src[src.index("detail={"):src.index("}", src.index("detail={")) + 1]
        assert "email" not in detail

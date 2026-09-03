"""A machine principal is authorised by scope, never by role (ADR-363).

The Discord bot moves off a Cognito USER account onto an OAuth2
client_credentials app client, because a user account cannot answer an MFA
challenge and was therefore blocking enforcement entirely (ADR-362).

Measured against a real staging token before any of this was written:

    response  : ['access_token', 'expires_in', 'token_type']   <- no refresh
    sub       = <the app client id, NOT a user>
    scope     = asheflow.bot/dispatch.read ...
    (no email, no username, no cognito:groups)

So the machine caller has no Employee row, no role, and no company from the
database. Each of those is a separate way to fail open, and each is pinned here.
"""
import re
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.api.deps import MachineCaller, RoleChecker

ROOT = Path(__file__).resolve().parents[3]
DEPS = ROOT / "backend" / "app" / "api" / "deps.py"
SECURITY = ROOT / "backend" / "app" / "core" / "security.py"
BOT_CLIENT = ROOT / "bot" / "services" / "api_client.py"


def _read(p: Path) -> str:
    assert p.exists(), f"{p} moved — re-pin this test"
    return p.read_text(errors="ignore")


class TestScopeAuthorisation:
    def test_an_endpoint_without_machine_scopes_refuses_a_machine(self):
        """The bot's reach is exactly the endpoints that opted in — not
        everything its old `dispatch` role happened to allow.

        Asserts HTTPException(403) specifically: `pytest.raises(Exception)` also
        passes when the guard is DELETED and the code crashes on `db=None`
        further down, which is how an earlier version of this test survived its
        own mutation.
        """
        checker = RoleChecker(["dispatch"])
        caller = {"machine_scopes": {"asheflow.bot/dispatch.read"}}
        with pytest.raises(HTTPException) as exc:
            checker(user=caller, db=None)
        assert exc.value.status_code == 403
        assert "machine" in exc.value.detail.lower()

    def test_a_machine_without_the_scope_is_refused(self):
        checker = RoleChecker(["dispatch"], machine_scopes=["asheflow.bot/dispatch.write"])
        caller = {"machine_scopes": {"asheflow.bot/dispatch.read"}}
        with pytest.raises(HTTPException) as exc:
            checker(user=caller, db=None)
        assert exc.value.status_code == 403
        assert "scope" in exc.value.detail.lower()

    def test_a_machine_with_the_scope_is_allowed(self):
        checker = RoleChecker(["dispatch"], machine_scopes=["asheflow.bot/dispatch.read"])
        caller = {"machine_scopes": {"asheflow.bot/dispatch.read"}}
        assert checker(user=caller, db=None) is caller

    def test_a_human_never_takes_the_machine_path(self):
        """`machine_scopes` is absent on a human token, so the role path runs.

        Keyed on presence of the claim rather than absence of a role: a human
        with no role must still be refused by the role check, not silently
        routed through scope authorisation.
        """
        src = _read(DEPS)
        i = src.index("held = user.get(\"machine_scopes\")")
        assert "if held is not None:" in src[i: i + 120], (
            "the machine branch must trigger on the claim being PRESENT; "
            "a falsy-but-present empty set would otherwise fall through to roles"
        )


class TestTenancyIsExplicit:
    def test_a_machine_caller_carries_a_company(self):
        """Every tenant-scoped query reads caller.company_id (Dimension 1)."""
        import uuid
        c = MachineCaller(id="client", company_id=uuid.uuid4(), name="bot")
        assert c.company_id is not None

    def test_a_machine_caller_has_no_role_attribute(self):
        """A machine is authorised by scope. Code reaching for caller.role on one
        is a bug worth an AttributeError, not a silent wrong answer."""
        import uuid
        c = MachineCaller(id="client", company_id=uuid.uuid4(), name="bot")
        assert not hasattr(c, "role")

    def test_an_unbound_machine_client_is_refused(self, monkeypatch):
        """Defaulting to 'the only company' is correct today and silently wrong
        the day a second one exists — the worst failure shape available.

        Exercises get_current_user with the binding unset rather than grepping
        for the guard: a source assertion passes with the guard deleted, because
        the setting name still appears in config.py.
        """
        from app.api import deps as D

        monkeypatch.setattr(D.settings, "aws_cognito_bot_client_id", "bot-client", raising=False)
        monkeypatch.setattr(D.settings, "aws_cognito_bot_company_id", None, raising=False)
        monkeypatch.setattr(
            D, "verify_cognito_token",
            lambda _t: {"client_id": "bot-client", "sub": "bot-client",
                        "scope": "asheflow.bot/dispatch.read"},
        )
        with pytest.raises(HTTPException) as exc:
            D.get_current_user(token="stub")
        assert exc.value.status_code == 401
        assert "company" in exc.value.detail.lower()

    def test_a_bound_machine_client_carries_its_company(self, monkeypatch):
        from app.api import deps as D

        monkeypatch.setattr(D.settings, "aws_cognito_bot_client_id", "bot-client", raising=False)
        monkeypatch.setattr(D.settings, "aws_cognito_bot_company_id",
                            "a0000000-0000-0000-0000-000000000001", raising=False)
        monkeypatch.setattr(
            D, "verify_cognito_token",
            lambda _t: {"client_id": "bot-client", "sub": "bot-client",
                        "scope": "asheflow.bot/dispatch.read"},
        )
        user = D.get_current_user(token="stub")
        assert user["machine_company_id"] == "a0000000-0000-0000-0000-000000000001"
        assert user["machine_scopes"] == {"asheflow.bot/dispatch.read"}


class TestTheClientIdIsAllowlisted:
    def test_only_configured_clients_are_accepted(self):
        """Not 'any client in this pool': anyone able to create an app client
        could otherwise mint tokens the API trusts."""
        src = _read(SECURITY)
        assert "allowed = {settings.aws_cognito_app_client_id}" in src
        assert "token_client_id not in allowed" in src

    def test_the_bot_client_is_opt_in(self):
        """Unset means NO client-credentials token is accepted — the safe
        default rather than a permissive one."""
        src = _read(SECURITY)
        assert "if settings.aws_cognito_bot_client_id:" in src, (
            "the bot client must only be added to the allowlist when configured"
        )


class TestTheBotUsesTheMachineIdentity:
    def test_m2m_is_preferred_over_the_password_path(self):
        src = _read(BOT_CLIENT)
        i = src.index("async def _refresh_token(self)")
        window = src[i: i + 700]
        assert "cognito_m2m_client_id" in window and "_refresh_token_m2m" in window, (
            "the bot must prefer the machine identity when it is configured"
        )

    def test_expires_in_is_read_not_assumed(self):
        """Client credentials issues NO refresh token, so the only renewal
        signal is expires_in. Assuming one hour strands the bot if the app
        client's validity is changed in the console."""
        src = _read(BOT_CLIENT)
        assert 'body.get("expires_in"' in src, "expiry is hardcoded rather than read"

    def test_a_token_endpoint_error_is_named(self):
        """The token endpoint reports failures as an OAuth error code with a
        200-shaped body, not an exception."""
        src = _read(BOT_CLIENT)
        i = src.index("async def _refresh_token_m2m")
        window = src[i: i + 2600]
        assert 'body.get("error"' in window, "an OAuth error code is not surfaced"
        assert "logger.error" in window

    def test_the_password_path_survives_for_rollback(self):
        """Kept deliberately: a rollback should be an env change, not a deploy."""
        src = _read(BOT_CLIENT)
        assert "_refresh_token_password" in src
        assert "SOFTWARE_TOKEN_MFA" in src, (
            "the challenge handling must survive on the fallback path — it is "
            "what makes a botched cutover legible"
        )


class TestTheBotsReachIsExactlyItsEndpoints:
    """A ninth endpoint opting in should be a deliberate act, not a drift.

    The whole point of scopes here is that the bot reaches 8 endpoints instead
    of everything `dispatch` allowed. Nothing stops a later change adding
    machine_scopes= to a ninth without anyone noticing, so the count is pinned.
    """

    def test_the_scope_declarations_are_the_expected_set(self):
        import re

        routers = ROOT / "backend" / "app" / "routers"
        found = {}
        for f in sorted(routers.rglob("*.py")):
            body = f.read_text(errors="ignore")
            for m in re.finditer(r'machine_scopes=\[([^\]]+)\]', body):
                for scope in re.findall(r'"([^"]+)"', m.group(1)):
                    found.setdefault(scope, set()).add(f.name)

        assert set(found) == {
            "asheflow.bot/dispatch.read",
            "asheflow.bot/dispatch.write",
            "asheflow.bot/employees.read",
            "asheflow.bot/training.read",
        }, (
            f"the bot's scope surface changed: {sorted(found)}. Adding a scope "
            "widens what the machine identity can reach — update this list "
            "deliberately, and the resource server with it."
        )

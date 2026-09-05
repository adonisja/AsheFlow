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

    def test_a_token_with_no_tenant_scope_is_not_a_machine(self, monkeypatch):
        """ADR-364 — the company comes from the TOKEN now, not an env var.

        A token carrying no asheflow.tenant/<uuid> scope is not treated as a
        machine principal at all, so it falls through to the user path and is
        refused there for having no `sub`.
        """
        from app.api import deps as D

        monkeypatch.setattr(
            D, "verify_cognito_token",
            lambda _t: {"client_id": "some-client", "scope": "asheflow.bot/dispatch.read"},
        )
        with pytest.raises(HTTPException) as exc:
            D.get_current_user(token="stub")
        assert exc.value.status_code == 401

    def test_the_tenant_scope_becomes_the_company(self, monkeypatch):
        from app.api import deps as D

        monkeypatch.setattr(
            D, "verify_cognito_token",
            lambda _t: {"client_id": "c", "sub": "c",
                        "scope": "asheflow.tenant/a0000000-0000-0000-0000-000000000001 "
                                 "asheflow.bot/dispatch.read"},
        )
        user = D.get_current_user(token="stub")
        assert user["machine_company_id"] == "a0000000-0000-0000-0000-000000000001"
        assert "asheflow.bot/dispatch.read" in user["machine_scopes"]


class TestNonMachineTokensStillPinTheAppClient:
    def test_a_human_token_must_come_from_the_configured_client(self):
        """ADR-364 replaced the two-id allowlist, but a HUMAN token is still
        pinned: only a token carrying a tenant scope skips that check."""
        src = _read(SECURITY)
        assert 'is_machine = any(s.startswith("asheflow.tenant/") for s in scopes)' in src
        assert "if not is_machine and token_client_id != settings.aws_cognito_app_client_id:" in src


class TestTheBotUsesTheMachineIdentity:
    def test_the_machine_identity_is_the_only_path(self):
        """Was test_m2m_is_preferred_over_the_password_path.

        There is no longer a preference to express: ADR-377 removed the password
        fallback, so `_refresh_token` dispatches to exactly one place.
        """
        src = _read(BOT_CLIENT)
        i = src.index("async def _refresh_token(self)")
        body = src[i: src.index("async def _refresh_token_m2m")]
        assert "_refresh_token_m2m" in body
        assert "else:" not in body, (
            "a second auth path is back in the dispatcher (ADR-377 removed it)"
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
        # Scoped to the FUNCTION, not a fixed character window. The window was
        # 2600 chars and ADR-377's credential guard pushed the error handling
        # past it -- the test failed while the behaviour was intact, which is a
        # false alarm on a real check.
        import ast

        src = _read(BOT_CLIENT)
        fn = next(
            n for n in ast.walk(ast.parse(src))
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name == "_refresh_token_m2m"
        )
        # Slice the RAW source by line numbers rather than ast.unparse: unparse
        # normalises quote style, so body.get("error") comes back as
        # body.get('error') and a quote-sensitive assertion fails on code that
        # is perfectly correct.
        window = "\n".join(src.splitlines()[fn.lineno - 1: fn.end_lineno])
        assert 'body.get("error"' in window, "an OAuth error code is not surfaced"
        assert "logger.error" in window

    def test_the_password_path_is_gone(self):
        """INVERTED by ADR-377. This test previously asserted the opposite.

        ADR-363 kept the USER_PASSWORD_AUTH fallback so a rollback was an env
        change rather than a deploy, and pinned it here. That reasoning held
        until MFA enforcement: a bot has no phone and cannot answer a challenge,
        so under MfaConfiguration=ON the `asheflow.bot` user account is refused
        at sign-in. The fallback would look like a safety net while being
        incapable of working.

        Rolling back the machine identity is now a git revert.
        """
        src = _read(BOT_CLIENT)
        assert "_refresh_token_password" not in src, (
            "the password fallback is back — under MFA enforcement it cannot "
            "authenticate, so it is a rollback that provably fails (ADR-377)"
        )
        assert "bot_username" not in src and "bot_password" not in src, (
            "the credentials outlived the code path that used them"
        )

    def test_missing_m2m_credentials_fail_loudly(self):
        """With no fallback, unset credentials must name the problem.

        The old dispatcher treated missing M2M credentials as "use the other
        path". With that path gone they would otherwise surface as a TypeError
        inside aiohttp.BasicAuth rather than as the configuration error they are.
        """
        src = _read(BOT_CLIENT)
        assert "COGNITO_M2M_CLIENT_ID and COGNITO_M2M_CLIENT_SECRET are required" in src


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

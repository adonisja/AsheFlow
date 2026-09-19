"""The bot fetches one credential per tenant (ADR-441).

ADR-364 put tenancy in the token and automated per-tenant client creation. The
BOT was never updated to hold more than one credential: it read a single
COGNITO_M2M_CLIENT_ID from env and used that token for every company, while
already resolving company_id per Discord guild.

With two tenants that is either a refusal (the token carries the other
company's scope) or a cross-tenant write. These pin the backend half of the fix.
"""
import inspect

from app.routers import internal as I


class TestTheEndpointIsOnTheInternalChannel:
    def test_it_is_gated_by_the_internal_secret(self):
        """Not get_super_admin.

        ADR-441 D1: the super-admin reveal endpoint returns a live credential,
        so giving the bot a token for it would hand it EVERY tenant's secret
        plus everything else a super admin can do. The internal channel is the
        narrower instrument and the bot already authenticates to it.
        """
        route = [r for r in I.router.routes
                 if getattr(r, "path", "") == "/internal/machine-credentials/{company_id}"]
        assert route, "endpoint is not mounted"

        # The decorator block: from the path literal to the function it wraps.
        mod = inspect.getsource(I)
        start = mod.index('"/machine-credentials/{company_id}"')
        block = mod[start:mod.index("def get_machine_credentials", start)]
        assert "_verify_secret" in block, (
            "the credential endpoint must be gated by X-Internal-Secret"
        )
        # Checks the SIGNATURE, not the source: the docstring names
        # get_super_admin to explain why it is not used, and matching on text
        # would fail on the explanation rather than on the code.
        params = inspect.signature(I.get_machine_credentials).parameters
        gates = [getattr(p.default, "dependency", None) for p in params.values()]
        assert not any(getattr(g, "__name__", "") == "get_super_admin" for g in gates), (
            "the bot must not need a super-admin token to fetch a credential"
        )

    def test_it_is_rate_limited(self):
        """ADR-441 D4. A leaked INTERNAL_SECRET enumerating every tenant's
        secret should be slow and loud, not a single loop."""
        mod = inspect.getsource(I)
        start = mod.index('"/machine-credentials/{company_id}"')
        block = mod[start:mod.index("def get_machine_credentials", start)]
        assert "@limiter.limit(" in block, "credential reads must be rate limited"


class TestItLeavesATrace:
    def test_every_read_is_audited(self):
        """A credential read that leaves no trace is indistinguishable from an
        exfiltration (ADR-441 D4)."""
        src = inspect.getsource(I.get_machine_credentials)
        assert "write_audit" in src
        assert "machine_client_secret_read" in src
        assert src.index("write_audit") < src.index("return MachineCredentialResponse"), (
            "the audit must be written before the secret is returned"
        )

    def test_the_audit_does_not_record_the_secret(self):
        """Auditing WHO read WHICH company's credential is the point. Writing
        the secret into the audit log would put a live credential in a second
        place, which defeats the reason for auditing it."""
        src = inspect.getsource(I.get_machine_credentials)
        detail = src[src.index("detail={"):src.index("}", src.index("detail={")) + 1]
        assert "client_id" in detail
        assert "secret" not in detail.replace("client_secret=secret", "")


class TestAnUnprovisionedCompanyIsNotAnError:
    def test_missing_client_is_404_not_500(self):
        """ADR-364 provisions AFTER the company commit, so a company can exist
        with no client. That is a normal state the bot's fallback handles, not
        a server fault."""
        src = inspect.getsource(I.get_machine_credentials)
        i = src.index("machine_client_id")
        window = src[i:i + 400]
        assert "HTTP_404_NOT_FOUND" in window, (
            "a company without a provisioned client must answer 404"
        )


class TestTheBotCannotForgetTheTenant:
    """The bot-side half (ADR-441 D2).

    Parsed from source rather than imported: the bot needs discord.py, which the
    backend test env does not install. The AST is the contract that matters here
    anyway — whether a call can omit the company, not what it returns.
    """

    @staticmethod
    def _bot_files():
        from pathlib import Path
        root = Path(__file__).resolve().parents[3] / "bot"
        return [root / "main.py", root / "cogs" / "setup.py",
                root / "cogs" / "dispatch.py"]

    def test_every_api_call_names_a_company(self):
        """A call that omits it would authenticate as whichever tenant the env
        credential belongs to — the cross-tenant write this ADR removes."""
        import ast

        missing = []
        for f in self._bot_files():
            for node in ast.walk(ast.parse(f.read_text())):
                if (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and isinstance(node.func.value, ast.Name)
                        and node.func.value.id == "api"
                        and node.func.attr not in ("start", "close")
                        and not any(k.arg == "company_id" for k in node.keywords)):
                    missing.append(f"{f.name}:{node.lineno} api.{node.func.attr}")
        assert not missing, (
            "these api calls do not name a company, so they would use whichever "
            f"tenant the env credential belongs to: {missing}"
        )

    def test_company_id_is_keyword_only_and_required(self):
        """A positional default would let a call site forget it silently.
        Keyword-only and required makes a missed call a TypeError."""
        import ast
        from pathlib import Path

        src = (Path(__file__).resolve().parents[3]
               / "bot" / "services" / "api_client.py").read_text()
        bad = []
        for node in ast.walk(ast.parse(src)):
            if not isinstance(node, ast.AsyncFunctionDef) or node.name.startswith("_"):
                continue
            if node.name in ("start", "close"):
                continue
            kw = {a.arg for a in node.args.kwonlyargs}
            if "company_id" not in kw:
                bad.append(node.name)
            else:
                i = [a.arg for a in node.args.kwonlyargs].index("company_id")
                if node.args.kw_defaults[i] is not None:
                    bad.append(f"{node.name} (has a default)")
        assert not bad, f"these API methods do not require a company: {bad}"

    def test_the_env_credential_is_only_a_404_fallback(self):
        """ADR-441 D3. Falling back on a FAILED fetch is how a request ends up
        authorised against the wrong tenant; falling back when the company has
        no client is correct."""
        from pathlib import Path

        src = (Path(__file__).resolve().parents[3]
               / "bot" / "services" / "api_client.py").read_text()
        block = src[src.index("async def _credentials_for"):]
        block = block[:block.index("@staticmethod")]
        assert "resp.status == 404" in block
        assert "_env_credentials()" in block
        # A non-404 failure must raise, not fall back.
        assert "raise RuntimeError" in block

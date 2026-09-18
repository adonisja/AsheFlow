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

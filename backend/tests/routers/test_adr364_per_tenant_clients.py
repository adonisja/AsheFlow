"""One machine client per tenant, provisioned from the UI (ADR-364).

ADR-363 D4 bound the machine caller's company with an env var and argued that
defaulting to "the only company" would be correct today and wrong later. It was
wrong immediately: two companies already exist, and the bot is already
multi-tenant (`get_company_id_for_guild`), so one deployment serves many guilds.
The env var would have authorised tenant B's traffic against tenant A's data.

Tenancy now rides in the token as `asheflow.tenant/<company-uuid>`.
"""
import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.services.tenant_machine_client import (
    BOT_SCOPES,
    TENANT_RESOURCE_SERVER,
    tenant_scope,
)

ROOT = Path(__file__).resolve().parents[3]
DEPS = ROOT / "backend" / "app" / "api" / "deps.py"
SERVICE = ROOT / "backend" / "app" / "services" / "tenant_machine_client.py"
COMPANIES = ROOT / "backend" / "app" / "routers" / "companies.py"


def _read(p: Path) -> str:
    assert p.exists(), f"{p} moved — re-pin this test"
    return p.read_text(errors="ignore")


class TestTheTenantScopeNamesTheCompany:
    def test_the_scope_is_the_uuid_not_a_name(self):
        """A name can be edited in the UI. A tenant identifier that can be
        renamed is one that can be pointed at another tenant's data."""
        cid = uuid.uuid4()
        assert tenant_scope(cid) == f"{TENANT_RESOURCE_SERVER}/{cid}"

    def test_a_client_gets_its_tenant_scope_plus_the_bot_scopes(self):
        src = _read(SERVICE)
        assert "scopes = [tenant_scope(company_id), *BOT_SCOPES]" in src
        assert len(BOT_SCOPES) == 4, "the bot's permission surface changed"


class TestCrossTenantIsolation:
    """The Dimension 1 guarantee: tenant A's client cannot act for tenant B."""

    def _caller(self, monkeypatch, company_uuid, client_id, db_company):
        from app.api import deps as D

        monkeypatch.setattr(
            D, "verify_cognito_token",
            lambda _t: {"client_id": client_id, "sub": client_id,
                        "scope": f"{tenant_scope(company_uuid)} asheflow.bot/dispatch.read"},
        )

        class _Q:
            def __init__(self, result): self._r = result
            def filter(self, *a, **k): return self
            def first(self): return self._r

        class _DB:
            def query(self, *a, **k): return _Q(db_company)

        return D.get_caller_employee(
            current_user=D.get_current_user(token="stub"), db=_DB()
        )

    def test_a_client_acts_only_for_its_own_company(self, monkeypatch):
        cid = uuid.uuid4()

        class C:
            id = cid
            machine_client_id = "client-a"

        caller = self._caller(monkeypatch, cid, "client-a", C())
        assert caller.company_id == cid

    def test_a_client_holding_another_tenants_scope_is_refused(self, monkeypatch):
        """The scope alone is not enough: the presenting client must be THE
        client registered for that company."""
        cid = uuid.uuid4()

        class C:
            id = cid
            machine_client_id = "client-a"      # registered for this company

        with pytest.raises(HTTPException) as exc:
            self._caller(monkeypatch, cid, "client-b", C())   # different client
        assert exc.value.status_code == 401
        assert "not the one registered" in exc.value.detail

    def test_a_scope_naming_a_deleted_company_is_refused(self, monkeypatch):
        with pytest.raises(HTTPException) as exc:
            self._caller(monkeypatch, uuid.uuid4(), "client-a", None)
        assert exc.value.status_code == 401
        assert "does not exist" in exc.value.detail

    def test_two_tenant_scopes_are_refused(self, monkeypatch):
        """A client provisioned for two companies makes the lookup a coin flip
        over whose data gets touched. Lives here with the other isolation
        guarantees rather than in the ADR-363 suite."""
        from app.api import deps as D

        monkeypatch.setattr(
            D, "verify_cognito_token",
            lambda _t: {"client_id": "c", "sub": "c",
                        "scope": f"{tenant_scope(uuid.uuid4())} {tenant_scope(uuid.uuid4())}"},
        )
        with pytest.raises(HTTPException) as exc:
            D.get_current_user(token="stub")
        assert exc.value.status_code == 401
        assert "more than one tenant" in exc.value.detail

    def test_a_malformed_tenant_is_refused(self, monkeypatch):
        from app.api import deps as D

        monkeypatch.setattr(
            D, "verify_cognito_token",
            lambda _t: {"client_id": "c", "sub": "c",
                        "scope": f"{TENANT_RESOURCE_SERVER}/not-a-uuid"},
        )
        with pytest.raises(HTTPException) as exc:
            D.get_caller_employee(current_user=D.get_current_user(token="stub"), db=None)
        assert exc.value.status_code == 401
        assert "malformed" in exc.value.detail


class TestProvisioningDoesNotStrandTenants:
    def test_the_scope_list_is_read_modify_write(self):
        """UpdateResourceServer REPLACES the scope list. Sending only the new
        scope deletes every other tenant's, silently stripping authorisation
        from every other bot."""
        src = _read(SERVICE)
        i = src.index("def _ensure_tenant_scope")
        window = src[i: i + 1800]
        assert "describe_resource_server" in window, (
            "the existing scopes must be read before the list is replaced"
        )
        assert "scopes = list(existing.get" in window

    def test_the_hard_scope_ceiling_is_named(self):
        """100 scopes per resource server is not adjustable. The failure should
        say so rather than surface as a Cognito validation error."""
        src = _read(SERVICE)
        assert "len(scopes) >= 100" in src
        assert "asheflow.tenant2" in src, "the remedy is not named"

    def test_provisioning_failure_does_not_roll_back_the_company(self):
        """Cognito is not transactional. Rolling back would leave an orphaned
        app client holding a scope for a company that no longer exists — a
        company without a bot is recoverable, the reverse is not."""
        src = _read(COMPANIES)
        # Scope to create_company: provision_machine_client is also called by the
        # re-provision endpoint, where raising IS correct (no company is created
        # there, so there is nothing to strand).
        i = src.index("def create_company(")
        window = src[i: src.index("@router.get(", i)]
        assert "except Exception" in window
        assert "machine_client_error" in window, (
            "a failed provisioning must be reported, not raised over a company "
            "that was created successfully"
        )


class TestTheSecretIsNotStored:
    def test_no_secret_column_exists(self):
        from app.models.company import Company

        cols = {c.name for c in Company.__table__.columns}
        assert "machine_client_id" in cols
        assert not any("secret" in c for c in cols), (
            "a live credential must not live in a table three services join "
            "against; Cognito returns it on demand"
        )

    def test_revealing_a_secret_is_audited(self):
        """This returns a live credential. Who read it, and when, is the only
        thing that makes that acceptable."""
        src = _read(COMPANIES)
        i = src.index("def reveal_machine_client")
        window = src[i: i + 2000]
        assert "machine_client_secret_revealed" in window
        assert "write_audit" in window


class TestTheUICanTellProvisionedFromNot:
    """The create-company flow shows credentials once, which covers a NEW tenant
    and nothing else. Every company predating ADR-364 needs a way to get one,
    and a lost secret needs a way back — both live on the company detail page.
    """

    def test_the_detail_response_exposes_whether_a_client_exists(self):
        """Without this the page always offers to PROVISION, and doing so
        rotates a working secret and breaks that tenant's bot."""
        src = _read(COMPANIES)
        i = src.index("class CompanyDetailResponse")
        window = src[i: i + 700]
        assert "machine_client_id" in window, (
            "the detail page cannot distinguish provisioned from not, so it "
            "would offer to re-provision a working client"
        )

    def test_the_secret_is_not_in_the_detail_response(self):
        """The id is not a credential; the secret is, and it stays behind its
        own audited endpoint."""
        src = _read(COMPANIES)
        i = src.index("class CompanyDetailResponse")
        window = src[i: i + 700]
        assert "machine_client_secret" not in window, (
            "a live credential must not ride along on an ordinary page load"
        )

    def test_the_detail_page_calls_both_endpoints(self):
        page = (
            ROOT / "frontend" / "src" / "pages" / "superadmin" / "CompanyDetail.tsx"
        ).read_text(errors="ignore")
        assert "machine-client" in page, "the page never calls the endpoints"
        assert "Reveal secret" in page, "no recovery path for a lost secret"
        assert "Provision credentials" in page, (
            "a company created before ADR-364 has no way to get a client"
        )

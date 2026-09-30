"""The tenant never sees the platform's numbers (ADR-483).

GET /companies/my-config is gated to `allow_admin` -- any COMPANY admin -- and
returned 21 proprietary tuning parameters WITH THEIR VALUES: ADR-273's pairing
weights, ADR-356's target probabilities, and the sort weights whose ordering
ADR-186 D3 depends on. PATCH accepted writes to 12 of them.

`dispatch_weight_captain` was already absent from that response. The distinction
was recognised once and never made systematic -- which is exactly how the other
21 drifted in, and why the central test here ENUMERATES THE MODEL'S COLUMNS
rather than trusting a list someone maintains (ADR-464's lesson: a
registry-walking test passes forever while the registry goes stale).
"""
import inspect
import re

import pytest

from app.models.company import CompanyConfig
from app.routers.companies import (
    CompanyConfigResponse, PlatformConfigResponse, _SUPER_ADMIN_ONLY_FIELDS,
)
from app.services.company_config import (
    PLATFORM_ONLY_FIELDS, platform_settings_missing, platform_settings_ok,
)

_TENANT = set(CompanyConfigResponse.model_fields)
_PLATFORM = set(PlatformConfigResponse.model_fields)


# ── D1/D2: the partition holds ──────────────────────────────────────────────

@pytest.mark.parametrize("field", sorted(PLATFORM_ONLY_FIELDS))
def test_no_platform_field_reaches_the_tenant_schema(field):
    """THE property. Parametrised so a failure NAMES the field that leaked."""
    assert field not in _TENANT, (
        f"{field} is on the tenant-facing response. GET /companies/my-config is "
        "gated to any company admin, so this hands a tenant one of the "
        "algorithm's coefficients."
    )


def test_every_platform_field_is_a_real_column():
    """A typo here silently protects nothing -- the misspelled name is absent
    from the response either way, and the REAL column keeps leaking."""
    cols = {c.key for c in CompanyConfig.__table__.columns}
    assert PLATFORM_ONLY_FIELDS <= cols, PLATFORM_ONLY_FIELDS - cols


def test_the_partition_is_exhaustive_over_the_model():
    """ENUMERATE THE WORLD, don't walk the list (ADR-464).

    Every column must be on the tenant schema or declared platform-only. A new
    column belonging to neither is the exact shape of this bug: it lands on the
    response because adding it required no decision."""
    cols = {c.key for c in CompanyConfig.__table__.columns}
    # Columns intentionally on no response at all (Discord wiring, ADP windows,
    # internal knobs) -- each is server-side only and reaches clients through
    # its own endpoint, not this schema.
    internal = {c for c in cols if c.startswith(("discord_", "adp_"))} | {
        "captain_truck_rotation_days", "driver_training_days",
        "early_confirmation_deadline", "geoclient_borough",
    }
    unclassified = cols - _TENANT - PLATFORM_ONLY_FIELDS - internal
    assert not unclassified, (
        f"columns classified as neither tenant nor platform: {sorted(unclassified)}. "
        "Add each to the tenant schema, to PLATFORM_ONLY_FIELDS, or to the "
        "internal set above with a reason."
    )


def test_the_platform_schema_carries_them_all():
    """The split must not lose data for the people entitled to it."""
    assert PLATFORM_ONLY_FIELDS <= _PLATFORM, PLATFORM_ONLY_FIELDS - _PLATFORM


def test_the_platform_schema_is_a_superset_of_the_tenant_one():
    """Inheritance, not duplication -- two hand-maintained lists drift, which is
    how 21 fields ended up on the wrong one."""
    assert _TENANT <= _PLATFORM


# ── D3: the write path refuses them ─────────────────────────────────────────

@pytest.mark.parametrize("field", sorted(PLATFORM_ONLY_FIELDS))
def test_a_tenant_cannot_write_a_platform_field(field):
    """Read protection without write protection leaves a tenant able to retune
    the algorithm blind."""
    assert field in _SUPER_ADMIN_ONLY_FIELDS


def test_the_refusal_is_wired_into_the_apply_path():
    from app.routers import companies
    src = inspect.getsource(companies._apply_config_update)
    assert "_SUPER_ADMIN_ONLY_FIELDS" in src and "403" in src


# ── endpoints return the right schema ───────────────────────────────────────

def test_the_tenant_endpoints_return_the_tenant_schema():
    """If a company_admin_router route ever returns PlatformConfigResponse, the
    leak is back -- with a green build, since the schema is valid either way."""
    src = inspect.getsource(__import__("app.routers.companies", fromlist=["x"]))
    for m in re.finditer(r'@company_admin_router\.\w+\([^)]*response_model=(\w+)', src):
        assert m.group(1) != "PlatformConfigResponse", (
            "a tenant-facing route returns the platform schema"
        )


def test_the_super_admin_patch_returns_the_platform_schema():
    src = inspect.getsource(__import__("app.routers.companies", fromlist=["x"]))
    assert '@router.patch("/{company_id}/config", response_model=PlatformConfigResponse)' in src


# ── D4: the health signal ───────────────────────────────────────────────────

def test_the_tenant_signal_is_a_boolean_not_the_names():
    """Naming the absent fields leaks the parameter names the split withholds."""
    assert "platform_settings_ok" in _TENANT
    assert "platform_settings_missing" not in _TENANT


def test_the_platform_signal_names_them():
    """The person who can seed a missing weight gets to know which one."""
    assert "platform_settings_missing" in _PLATFORM


def test_the_two_signals_agree():
    cfg = CompanyConfig(company_id="x")
    assert platform_settings_ok(cfg) is False and platform_settings_missing(cfg)


def test_the_frontend_reads_the_boolean_and_names_nothing():
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[3]
           / "frontend/src/pages/CompanySettings.tsx").read_text()
    assert "platform_settings_ok" in src
    assert "platform_settings_missing" not in src, (
        "the setup form still reads the named list"
    )

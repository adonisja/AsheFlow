"""Platform settings are seeded by the platform (ADR-482).

Submitting Company Setup in prod did NOTHING -- no error, no redirect. The PATCH
returned 200 OK five times. is_configured stayed false because eight of the
fifteen _REQUIRED_FIELDS were NULL and the form has no way to set any of them:

    missing= ['invite_expiry_days', 'dispatch_weight_driver', ...]

The columns document their defaults in COMMENTS and declare none in code, and
create_company did `CompanyConfig(company_id=...)` bare -- so every company ever
created was born with all fifteen required fields NULL.
"""
import pathlib
import re

from app.models.company import CompanyConfig
from app.services.company_config import (
    PLATFORM_SEEDED_DEFAULTS, _REQUIRED_FIELDS, platform_settings_missing,
)

ROOT = pathlib.Path(__file__).resolve().parents[3]


# ── D2: the gate covers only what the company controls ──────────────────────

def test_the_gate_matches_the_form_exactly():
    """THE bug, and the check that would have caught it.

    The gate held 15 fields; the setup form collects 7. A gate containing
    fields the gated party cannot set is a deadlock, not a gate."""
    src = (ROOT / "frontend/src/pages/CompanySettings.tsx").read_text()
    block = re.search(r"const REQUIRED_KEYS = new Set\(\[(.*?)\]\)", src, re.S)
    assert block, "REQUIRED_KEYS not found in CompanySettings.tsx"
    form_keys = set(re.findall(r"'([a-z0-9_]+)'", block.group(1)))
    assert form_keys == set(_REQUIRED_FIELDS), (
        "the setup gate and the setup form disagree.\n"
        f"  gate only: {sorted(set(_REQUIRED_FIELDS) - form_keys)}\n"
        f"  form only: {sorted(form_keys - set(_REQUIRED_FIELDS))}\n"
        "A field in the gate that the form cannot set means a 200 OK, "
        "is_configured=False, and a form that silently does nothing."
    )


def test_no_platform_setting_is_in_the_tenant_gate():
    """The two sets are disjoint by construction -- one is the platform's
    responsibility, the other the tenant's."""
    assert not (set(_REQUIRED_FIELDS) & set(PLATFORM_SEEDED_DEFAULTS))


def test_invite_expiry_days_is_not_gated_on_the_tenant():
    """It is in _SUPER_ADMIN_ONLY_FIELDS -- a company admin is FORBIDDEN from
    setting it, so requiring it for their own setup was unsatisfiable."""
    assert "invite_expiry_days" not in _REQUIRED_FIELDS
    src = (ROOT / "backend/app/routers/companies.py").read_text()
    blk = re.search(r"_SUPER_ADMIN_ONLY_FIELDS\s*=\s*[({](.*?)[)}]", src, re.S)
    assert blk and "invite_expiry_days" in blk.group(1)


# ── D1: creation seeds them ─────────────────────────────────────────────────

def test_creation_passes_the_defaults_rather_than_relying_on_columns():
    """`CompanyConfig(company_id=...)` bare is what wrote eight NULLs."""
    src = (ROOT / "backend/app/routers/companies.py").read_text()
    assert "CompanyConfig(company_id=company.id, **PLATFORM_SEEDED_DEFAULTS)" in src


def test_a_seeded_config_needs_no_platform_repair():
    cfg = CompanyConfig(company_id="x", **PLATFORM_SEEDED_DEFAULTS)
    assert platform_settings_missing(cfg) == []


def test_a_bare_config_is_reported_as_missing_all_of_them():
    """The state every existing company is in, which D4's migration repairs."""
    assert set(platform_settings_missing(CompanyConfig(company_id="x"))) == \
        set(PLATFORM_SEEDED_DEFAULTS)


def test_the_weights_satisfy_the_adr186_ordering():
    """W_TIME and W_DIFF >= W_DENSE, or _apply_config_update 422s on the first
    PATCH that touches a weight -- seeding a set the validator rejects would
    trade a silent deadlock for a loud one."""
    d = PLATFORM_SEEDED_DEFAULTS
    assert d["dispatch_weight_driver"] >= d["dispatch_weight_walker"]
    assert 0 < d["dispatch_weight_cap"] <= 1


# ── D3: a missing platform setting is visible ───────────────────────────────

def test_the_response_reports_platform_health():
    """D2 removed these from the gate, and that gate -- by deadlocking the
    tenant -- was the only thing checking them at all."""
    src = (ROOT / "backend/app/routers/companies.py").read_text()
    assert "platform_settings_missing:        list[str]" in src
    assert "platform_settings_missing=platform_settings_missing(obj)" in src


def test_the_frontend_type_carries_it():
    """types.ts / the local interface are hand-maintained -- no codegen."""
    src = (ROOT / "frontend/src/pages/CompanySettings.tsx").read_text()
    assert "platform_settings_missing?: string[]" in src


# ── D4: the backfill ────────────────────────────────────────────────────────

def _migration() -> str:
    hits = list((ROOT / "backend/alembic/versions").glob("*adr482*.py"))
    assert len(hits) == 1, f"expected one ADR-482 migration, found {hits}"
    return hits[0].read_text()


def test_the_backfill_only_fills_nulls():
    """A tenant whose weights were tuned by hand must keep them -- this fills a
    gap, it does not reset a configuration."""
    src = _migration()
    assert "IS NULL" in src
    assert src.count("IS NULL") >= 1


def test_the_backfill_covers_every_platform_setting():
    src = _migration()
    for field in PLATFORM_SEEDED_DEFAULTS:
        assert field in src, f"{field} is not backfilled"


def test_the_backfill_does_not_reset_a_tuned_value():
    """The downgrade must NOT null these columns: it cannot distinguish a value
    the upgrade wrote from one a platform admin set afterwards, so reversing
    would destroy real configuration to undo a gap-fill."""
    src = _migration()
    body = src[src.index("def downgrade"):]
    assert "UPDATE" not in body.upper() and "DROP" not in body.upper(), (
        "the downgrade modifies data; it must be a no-op"
    )

# Self-containment is covered for EVERY migration by
# tests/test_migrations_are_self_contained.py, with an anchored regex. A
# substring check here matched the phrase "no import from app.*" in this
# migration's own docstring -- prose, not code.


# ── D5: the third state has a branch ────────────────────────────────────────

def test_the_form_explains_a_save_that_did_not_complete_setup():
    """200 + is_configured=False fell through to setSaved(true): a tick, no
    redirect, no error. That silence is the reported bug."""
    src = (ROOT / "frontend/src/pages/CompanySettings.tsx").read_text()
    assert "if (isOnboarding && !res.data.is_configured)" in src
    assert "platform administrator" in src

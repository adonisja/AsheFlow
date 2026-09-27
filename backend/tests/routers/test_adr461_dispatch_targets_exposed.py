"""The settings pages show the knobs that turn (ADR-461).

ADR-356 replaced dispatch weight multipliers with per-tier target
probabilities. The columns shipped and calculate_weights.py reads them, but no
UI ever exposed them -- while twenty-one inputs for the superseded weights
stayed on screen, writable, and read by nothing.
"""
import pathlib
import re

from app.routers.companies import (
    _DISPATCH_TARGET_FIELDS,
    _SUPER_ADMIN_ONLY_FIELDS,
    CompanyConfigUpdate,
)
from app.services.preference_tiers import DEFAULT_TARGETS

ROOT = pathlib.Path(__file__).resolve().parents[3]
SUPER_ADMIN_PAGE = ROOT / "frontend/src/pages/superadmin/CompanyDetail.tsx"
TENANT_PAGE = ROOT / "frontend/src/pages/CompanySettings.tsx"

LEGACY = (
    "dispatch_weight_driver", "dispatch_weight_trainer", "dispatch_weight_walker",
    "dispatch_mutual_bonus", "dispatch_tridirectional_bonus",
    "dispatch_consecutive_penalty", "dispatch_weight_cap",
)


# ── the field set matches the algorithm ─────────────────────────────────────

def test_one_target_field_per_tier():
    """A tier with no column falls back to the default and cannot be tuned;
    a column with no tier is a control wired to nothing."""
    columns = {f.removeprefix("dispatch_target_") for f in _DISPATCH_TARGET_FIELDS}
    assert columns == set(DEFAULT_TARGETS), (
        f"only in config: {columns - set(DEFAULT_TARGETS)}; "
        f"only in the algorithm: {set(DEFAULT_TARGETS) - columns}"
    )


def test_the_update_schema_accepts_every_target():
    for field in _DISPATCH_TARGET_FIELDS:
        assert field in CompanyConfigUpdate.model_fields, (
            f"{field} has a UI input but the API would reject it"
        )


def test_a_target_of_one_is_rejected_by_the_schema():
    """ADR-356 D5: 1.0 divides by zero in weight_for_target. It is a pin."""
    for field in sorted(_DISPATCH_TARGET_FIELDS):
        meta = CompanyConfigUpdate.model_fields[field].metadata
        uppers = [m for m in meta if type(m).__name__ == "Lt"]
        assert uppers and uppers[0].lt == 1.0, (
            f"{field} allows 1.0, which weight_for_target raises on"
        )


# ── D3: tenant admins cannot set them ───────────────────────────────────────

def test_targets_are_super_admin_only():
    assert _DISPATCH_TARGET_FIELDS <= _SUPER_ADMIN_ONLY_FIELDS


def test_the_tenant_page_offers_no_dispatch_tuning():
    src = TENANT_PAGE.read_text()
    for field in sorted(_DISPATCH_TARGET_FIELDS):
        assert field not in src, f"{field} is on the tenant page (ADR-461 D3)"


# ── D1: the dead controls are gone ──────────────────────────────────────────

def test_the_legacy_weight_inputs_are_off_both_pages():
    """They were writable, persisted, and read by nothing -- a control that
    accepts input, confirms success and does nothing is worse than none."""
    for page in (SUPER_ADMIN_PAGE, TENANT_PAGE):
        src = page.read_text()
        for field in LEGACY:
            assert field not in src, f"{field} still has an input on {page.name}"


def test_the_legacy_columns_are_still_accepted_by_the_api():
    """ADR-461: the UI stops offering them; the contract does not change.

    ADR-356 kept the columns so a migration can read a tenant's old
    multipliers. Removing them from the schema is a breaking change for any
    client still sending them, and belongs with the column drop.
    """
    for field in LEGACY:
        assert field in CompanyConfigUpdate.model_fields


# ── D2: the super-admin page exposes them correctly ─────────────────────────

def test_every_target_has_an_input_on_the_super_admin_page():
    src = SUPER_ADMIN_PAGE.read_text()
    for field in sorted(_DISPATCH_TARGET_FIELDS):
        assert f"key: '{field}'" in src, f"{field} has no input"


def test_target_inputs_are_optional_and_capped_below_one():
    """Blank means 'platform default'. Required would force a save to pin the
    tenant to today's numbers; max 1 would offer a value the API rejects."""
    src = SUPER_ADMIN_PAGE.read_text()
    for field in sorted(_DISPATCH_TARGET_FIELDS):
        line = next(l for l in src.splitlines() if f"key: '{field}'" in l)
        assert "required: false" in line, f"{field} is marked required"
        assert "max: 0.99" in line, f"{field} allows 1.0 in the UI"
        assert "placeholder:" in line, f"{field} does not show its default"

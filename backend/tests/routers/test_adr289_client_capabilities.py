"""Client nav gates agree with the server's capability list (ADR-289).

WHY A PYTHON TEST FOR TYPESCRIPT FILES
Same reasoning as test_web_role_gates.py: the web and mobile apps have no test
runner wired into CI, and the backend suite is what runs on every push. Parsing
files for string literals needs no DOM and no bundler.

THE PROPERTY
`_FULL_MODE_FEATURES` in routers/companies.py is what the server puts in the
capabilities response. Both clients gate tabs on `feature:` keys. If a client
gates on a key the server never emits, that tab vanishes for EVERY company
including full-mode ones — a silent feature removal that no server test catches,
because the server is behaving correctly.

The reverse (a server key no client uses) is fine and deliberately not asserted:
a feature may exist before any tab needs it.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
NAV_WEB = ROOT / "frontend" / "src" / "config" / "navConfig.ts"
NAV_MOBILE = ROOT / "mobile" / "src" / "navigation" / "index.tsx"
AUTH_WEB = ROOT / "frontend" / "src" / "contexts" / "AuthContext.tsx"
AUTH_MOBILE = ROOT / "mobile" / "src" / "contexts" / "AuthContext.tsx"

_FEATURE_RE = re.compile(r"feature:\s*'([a-z_]+)'")


def _server_features() -> set[str]:
    """Every key the server can emit, across ALL modes.

    Includes _WORKFORCE_MODE_FEATURES (ADR-291): a workforce-only tab is gated on
    a key a full-mode tenant never receives, which is the whole point — but it is
    still a key the server emits, so it must not read as a typo here.
    """
    from app.routers.companies import (
        _BASE_FEATURES, _FULL_MODE_FEATURES, _WORKFORCE_MODE_FEATURES,
    )
    return set(_BASE_FEATURES) | set(_FULL_MODE_FEATURES) | set(_WORKFORCE_MODE_FEATURES)


def _client_features(path: Path) -> set[str]:
    """Feature keys a client gates tabs on.

    ADR-317 D3 moved mobile's gates out of `navigation/index.tsx` into
    `navigation/roles.ts` (TAB_GATES), so ONE list feeds both the tab registry
    and anything linking to a tab. The keys are the same; they live next door.
    Read the sibling too, or this guard silently sees zero gated tabs and
    reports a client that gates nothing — which is what it did on the first run
    after the move.
    """
    text = path.read_text()
    sibling = path.parent / "roles.ts"
    if sibling.exists():
        text += sibling.read_text()
    return set(_FEATURE_RE.findall(text))


@pytest.mark.parametrize("path", [NAV_WEB, NAV_MOBILE], ids=["web", "mobile"])
def test_client_gates_only_on_features_the_server_emits(path):
    """A tab gated on an unknown key disappears for every company, full mode
    included — and no server-side test would notice, because the server is right."""
    unknown = _client_features(path) - _server_features()
    assert not unknown, (
        f"{path.name} gates tabs on feature keys the server never emits: "
        f"{sorted(unknown)}. Add them to _FULL_MODE_FEATURES/_BASE_FEATURES in "
        f"routers/companies.py, or fix the typo."
    )


@pytest.mark.parametrize("path", [NAV_WEB, NAV_MOBILE], ids=["web", "mobile"])
def test_package_surfaces_are_actually_gated(path):
    """The point of the work: the package tabs must carry a feature key.

    Without this, adding a new package screen and forgetting the key silently
    reintroduces the regression this ADR exists to fix — a workforce tenant
    tapping into an endpoint that 404s.
    """
    used = _client_features(path)
    assert "route_sort" in used, f"{path.name} does not gate any route/sort tab"


def test_gated_keys_are_mode_specific_not_base_keys():
    """Gating a tab on a BASE feature is a no-op that reads like protection —
    base features are present in every mode, so the tab never hides. A
    mode-specific key (full OR workforce) is the only kind that gates anything."""
    from app.routers.companies import _BASE_FEATURES

    for path in (NAV_WEB, NAV_MOBILE):
        pointless = _client_features(path) & set(_BASE_FEATURES)
        assert not pointless, (
            f"{path.name} gates on always-present features {sorted(pointless)} — "
            f"the tab can never hide, so the gate is misleading."
        )


@pytest.mark.parametrize(
    "path", [AUTH_WEB, AUTH_MOBILE], ids=["web", "mobile"]
)
def test_both_clients_fetch_capabilities(path):
    src = path.read_text()
    assert "/companies/my-capabilities" in src, (
        f"{path.name} never calls the capabilities endpoint"
    )


@pytest.mark.parametrize(
    "path", [AUTH_WEB, AUTH_MOBILE], ids=["web", "mobile"]
)
def test_has_feature_fails_open(path):
    """Unknown capabilities must show everything, not nothing.

    A walker on a flaky van connection losing every tab is far worse than a dead
    tab: the server enforces each gated route with a 404 regardless, so failing
    open costs nothing real. Pinned because the "safe" instinct is to fail closed,
    and here that instinct is wrong.
    """
    src = path.read_text()
    # Both implementations return true when `capabilities` is null.
    assert re.search(r"capabilities\s*\?", src) or "if (!capabilities) return true" in src, (
        f"{path.name}: hasFeature does not visibly fail open on null capabilities"
    )


# ── superadmin flip dialog (ADR-289 D1c/D1d) ─────────────────────────────────

COMPANY_DETAIL = ROOT / "frontend" / "src" / "pages" / "superadmin" / "CompanyDetail.tsx"


def _mode_card() -> str:
    src = COMPANY_DETAIL.read_text()
    return src[src.index("function OperatingModeCard"):src.index("// 1. Company identity card")]


def test_flip_requires_typed_slug_confirmation():
    """Not a checkbox. A super admin has several tenants open at once and the
    realistic mistake is flipping the wrong one, so the control demands the
    company's own slug rather than a generic yes."""
    card = _mode_card()
    assert "typed.trim() === detail.slug" in card
    assert "if (!confirmed) return" in card, "submit must refuse without confirmation"
    assert "disabled={!confirmed || busy}" in card, "button must be disabled too"


def test_flip_targets_the_opposite_mode():
    """A one-button toggle that computed the wrong target would silently no-op
    against the server's 400 guard, which reads as a broken button."""
    assert "current === 'full' ? 'workforce' : 'full'" in _mode_card()


def test_only_the_dangerous_direction_carries_the_warning():
    """ADR-289 D1d: the directions are NOT mirror images.

    full -> workforce removes automated routing but leaves a working manual path.
    workforce -> full removes that manual path and replaces it with a pipeline
    that produces nothing until a manifest lands — so it is the direction that
    can leave a tenant with no routes on a shift morning, and the only one that
    warns. A symmetric "are you sure?" would hide exactly that asymmetry.
    """
    src = COMPANY_DETAIL.read_text()
    block = src[src.index("const MODE_COPY"):src.index("} as const;")]
    to_workforce = block[block.index("workforce:"):block.index("full:")]
    to_full = block[block.index("full:"):]

    assert "warn: null" in to_workforce, "full->workforce should not warn"
    assert "no routes until a manifest" in to_full, "workforce->full MUST warn"


def test_dialog_states_that_nothing_is_deleted():
    """The one genuinely reassuring thing the dialog can say, and it is true —
    records from the other mode are retained, which is what makes the change
    recoverable. Worth pinning so a copy edit cannot quietly drop it."""
    assert "Nothing is deleted" in _mode_card()


def test_flip_posts_to_the_guarded_endpoint_only():
    """The dedicated endpoint carries the no-op/in-flight/audit guards. Posting
    the mode to the generic config PATCH would bypass every one of them (and be
    refused by _GUARDED_FIELDS), so the URL is worth pinning."""
    card = _mode_card()
    assert "/operating-mode`" in card
    assert "confirm_slug: typed.trim()" in card


# ── workforce-only features (ADR-291) ─────────────────────────────────────────

def test_full_and_workforce_feature_sets_are_disjoint():
    """A key in both would gate nothing — the tab would show in every mode, and
    the gate would read like protection while providing none."""
    from app.routers.companies import _FULL_MODE_FEATURES, _WORKFORCE_MODE_FEATURES

    overlap = set(_FULL_MODE_FEATURES) & set(_WORKFORCE_MODE_FEATURES)
    assert not overlap, f"keys claimed by both modes: {sorted(overlap)}"


def test_neither_mode_set_overlaps_the_base_set():
    """A mode key that is also a base key is always present, so it cannot gate."""
    from app.routers.companies import (
        _BASE_FEATURES, _FULL_MODE_FEATURES, _WORKFORCE_MODE_FEATURES,
    )
    base = set(_BASE_FEATURES)
    assert not base & set(_FULL_MODE_FEATURES)
    assert not base & set(_WORKFORCE_MODE_FEATURES)


def test_a_full_mode_tenant_does_not_receive_workforce_keys():
    """The mirror of the original gate. A tenant with a manifest must not be
    offered captain-entered tote addresses — that would be duplicate,
    contradictory work feeding a sort that ignores it."""
    from app.routers.companies import (
        _BASE_FEATURES, _FULL_MODE_FEATURES, _WORKFORCE_MODE_FEATURES,
    )
    full_payload = set(_BASE_FEATURES) | set(_FULL_MODE_FEATURES)
    assert "workforce_sort" not in full_payload
    assert not full_payload & set(_WORKFORCE_MODE_FEATURES)

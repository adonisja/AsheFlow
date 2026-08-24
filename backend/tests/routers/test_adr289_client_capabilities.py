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
    from app.routers.companies import _BASE_FEATURES, _FULL_MODE_FEATURES
    return set(_BASE_FEATURES) | set(_FULL_MODE_FEATURES)


def _client_features(path: Path) -> set[str]:
    return set(_FEATURE_RE.findall(path.read_text()))


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


def test_gated_keys_are_full_mode_keys_not_base_keys():
    """Gating a tab on a BASE feature is a no-op that reads like protection —
    base features are present in every mode, so the tab never hides."""
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

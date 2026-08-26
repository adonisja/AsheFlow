"""The mode-gated-tab check must not silently narrow its own scope.

`scripts/check_mode_gated_tabs.py` reads each `_full_mode` router's prefix from
its source. Two of those routers (`walker_routes`, `rts`) are PROPRIETARY and
gitignored from the public repo, so in public CI their files are absent and their
prefixes cannot be read.

Without a fallback the script drops `/rts` and `/walker-routes` — the two
prefixes behind most of the known findings — finds fewer hits than it should, and
then reports its own baseline as stale. A check that quietly covers less while
still exiting 0 is worse than no check.

`PRIVATE_ROUTER_PREFIXES` is that fallback, and this file is what keeps it
truthful: a hardcoded map drifts the moment someone changes an APIRouter prefix.
"""
import importlib.util
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "check_mode_gated_tabs.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_mode_gated_tabs", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def check():
    if not SCRIPT.exists():
        pytest.skip("check script not present")
    return _load()


def test_every_private_prefix_matches_its_router(check):
    """The hardcoded fallback equals what the router actually declares.

    This is the drift guard. If someone renames `rts.router`'s prefix, the check
    would keep looking for the OLD urls and pass while covering nothing.
    """
    for name, expected in check.PRIVATE_ROUTER_PREFIXES.items():
        src = REPO / "backend" / "app" / "routers" / f"{name}.py"
        if not src.exists():
            pytest.skip(f"{name}.py not synced locally — CI with the private sync covers this")
        m = re.search(r"""APIRouter\([^)]*prefix\s*=\s*["']([^"']+)""", src.read_text())
        assert m, f"{name}.py has no APIRouter prefix to compare against"
        assert m.group(1) == expected, (
            f"PRIVATE_ROUTER_PREFIXES[{name!r}] is {expected!r} but the router "
            f"declares {m.group(1)!r} — the check is looking at the wrong URLs"
        )


def test_every_private_full_mode_router_has_a_fallback(check):
    """A `_full_mode` router whose source is gitignored MUST have an entry.

    Otherwise the check silently stops covering it the moment it runs anywhere
    the file is absent.
    """
    main_py = (REPO / "backend" / "app" / "main.py").read_text()
    registered = set(
        re.findall(r"include_router\(\s*(\w+)\.router,\s*dependencies=_full_mode", main_py)
    )
    gitignore = (REPO / ".gitignore").read_text()
    for name in registered:
        is_private = f"backend/app/routers/{name}.py" in gitignore
        if is_private:
            assert name in check.PRIVATE_ROUTER_PREFIXES, (
                f"{name} is _full_mode AND gitignored, so public CI cannot read its "
                f"prefix. Add it to PRIVATE_ROUTER_PREFIXES or the check stops "
                f"covering it without saying so."
            )


def test_prefix_discovery_survives_missing_private_sources(check, tmp_path, monkeypatch):
    """The public-CI case: the same prefixes with the private files absent."""
    with_sources = set(check.full_mode_prefixes())

    real_exists = check.os.path.exists

    def fake_exists(path):
        if any(f"routers/{n}.py" in str(path) for n in check.PRIVATE_ROUTER_PREFIXES):
            return False
        return real_exists(path)

    monkeypatch.setattr(check.os.path, "exists", fake_exists)
    without_sources = set(check.full_mode_prefixes())

    assert without_sources == with_sources, (
        "coverage changed when the proprietary routers were absent — this is the "
        "silent-narrowing failure the fallback exists to prevent"
    )


def test_the_navigation_barrel_is_skipped(check):
    """`navigation/index.tsx` re-exports every screen.

    Following it makes EVERY tab appear to reach everything — the first run of
    this logic reported Notifications as touching /rts for exactly that reason.
    """
    assert "navigation/index.tsx" in check.SKIP_FILES


def test_baseline_entries_name_the_adr_that_retires_them(check):
    """A baseline without an owner becomes permanent.

    Each entry carries the ADR that removes it, so a line still present in a
    month is evidence the fix was never scheduled — not evidence it is fine.
    """
    src = SCRIPT.read_text()
    block = src[src.index("BASELINE: set"):src.index("def full_mode_prefixes")]
    for key, url in check.BASELINE:
        line = next((l for l in block.splitlines() if f'"{url}"' in l), None)
        assert line, f"baseline entry {url} not found in the literal"
        assert "ADR-" in line, (
            f"baseline entry ({key}, {url}) has no ADR reference — an exemption "
            f"nobody owns is permanent"
        )

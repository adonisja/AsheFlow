"""Every error banner brings itself into view (ADR-339).

ADR-333 fixed DispatchDashboard, where a correct 409 rendered ~540 lines above
the button that caused it and read as a silent failure. Its Open item said the
shape was not unique to that page.

The sweep found something better than expected: `ErrorBanner` already existed
and was used by 32 pages. Putting the scroll inside it gives every page the
behaviour with no per-page edit — and means the 33rd page cannot be built
without it.
"""
import os
import re

import pytest

FE = os.path.join(os.path.dirname(__file__), "..", "..", "..", "frontend", "src")


def _read(rel: str) -> str:
    p = os.path.abspath(os.path.join(FE, rel))
    if not os.path.exists(p):
        pytest.fail(f"{rel} not found at {p}")
    return open(p).read()


def _strip_comments(src: str) -> str:
    """Comments describe their own subject and match greps aimed at code."""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"^\s*//.*$", "", src, flags=re.M)


# ── The behaviour lives in the shared component ──────────────────────────────

def test_the_shared_banner_scrolls_itself_into_view():
    """THE fix. 32 pages get it without being edited."""
    code = _strip_comments(_read("components/ui/ErrorBanner.tsx"))
    assert "useErrorBanner" in code
    assert "ref={ref}" in code, "the ref is never attached to the rendered element"


def test_the_hook_is_called_before_the_early_return():
    """`if (!message) return null` sits in this component. A hook called after
    it would break the rules of hooks and crash on the render where an error
    first appears."""
    code = _strip_comments(_read("components/ui/ErrorBanner.tsx"))
    hook_at = code.index("useErrorBanner(")
    ret_at = code.index("return null")
    assert hook_at < ret_at, "the hook runs conditionally — rules-of-hooks violation"


def test_the_scroll_is_keyed_on_the_message():
    """Otherwise a polling page scroll-jacks the user on every render."""
    code = _strip_comments(_read("hooks/useErrorBanner.ts"))
    assert "}, [error]);" in code


def test_clearing_the_error_does_not_scroll():
    """setError(null) must not yank the viewport."""
    code = _strip_comments(_read("hooks/useErrorBanner.ts"))
    assert "if (!error) return;" in code


def test_reduced_motion_is_respected():
    """CLAUDE.md — an animation that ignores prefers-reduced-motion is a bug."""
    code = _strip_comments(_read("hooks/useErrorBanner.ts"))
    assert "prefers-reduced-motion" in code
    assert "reduced ? 'auto' : 'smooth'" in code


def test_the_hook_holds_no_state_beyond_the_ref():
    code = _strip_comments(_read("hooks/useErrorBanner.ts"))
    assert "useState" not in code


# ── Reach ────────────────────────────────────────────────────────────────────

def test_the_component_is_used_broadly_enough_to_matter():
    """If this drops sharply, the scroll fix has quietly stopped covering the
    app and the pages have gone back to inline banners."""
    pages = os.path.abspath(os.path.join(FE, "pages"))
    users = [
        f for f in os.listdir(pages)
        if f.endswith(".tsx") and "ErrorBanner" in open(os.path.join(pages, f)).read()
    ]
    # 22 in pages/ directly (an earlier count of 32 walked subdirectories too).
    # The floor is a drift alarm, not a target: it fails if pages start going
    # back to inline banners, which is how the scroll fix would quietly stop
    # covering the app.
    assert len(users) >= 20, (
        f"only {len(users)} pages use the shared ErrorBanner — the scroll fix "
        "no longer covers the app"
    )


def test_dispatch_dashboard_uses_the_shared_hook_not_a_private_copy():
    """ADR-339 D4 — two implementations means the one that diverges is the one
    nobody notices."""
    code = _strip_comments(_read("pages/DispatchDashboard.tsx"))
    assert "useErrorBanner(error)" in code
    assert "scrollIntoView" not in code, "the ADR-333 prototype is still inline"

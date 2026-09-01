"""A reader for the alerts nobody could see (ADR-340).

ADR-335 built the table and endpoints; ADR-337 built the heartbeat that detects
a revoked credential within ten minutes. Neither had a reader — `grep -rn
"platform/alerts" frontend/src mobile/src` returned nothing — so a super admin's
only route to a platform alert was curl. The detection improved and the noticing
did not.
"""
import ast
import inspect
import os
import re

import pytest

from app.routers import platform_alerts as P

FE = os.path.join(os.path.dirname(__file__), "..", "..", "..", "frontend", "src")


def _read(rel: str) -> str:
    p = os.path.abspath(os.path.join(FE, rel))
    if not os.path.exists(p):
        pytest.fail(f"{rel} not found at {p}")
    return open(p).read()


def _strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"^\s*//.*$", "", src, flags=re.M)


PAGE = "pages/superadmin/PlatformAlerts.tsx"


# ── It exists and is reachable ───────────────────────────────────────────────

def test_the_page_calls_the_platform_endpoint():
    """THE gap: nothing referenced /platform/alerts at all."""
    code = _strip_comments(_read(PAGE))
    assert "'/platform/alerts'" in code or '"/platform/alerts"' in code


def test_the_route_is_registered():
    code = _strip_comments(_read("App.tsx"))
    assert "/superadmin/alerts" in code
    assert "PlatformAlerts" in code


def test_it_is_in_the_super_admin_navigation():
    """An unlinked route is only marginally better than no page."""
    code = _strip_comments(_read("components/layout/SuperAdminLayout.tsx"))
    assert "/superadmin/alerts" in code


def test_resolve_is_wired():
    code = _strip_comments(_read(PAGE))
    assert "/resolve" in code


# ── D2: scope before detail ──────────────────────────────────────────────────

def test_a_platform_wide_alert_says_so():
    """company_id null means EVERY tenant. "Discord is down for everyone" and
    "one tenant's mail is failing" are different incidents (ADR-335 D4), and the
    UI must not flatten what the model separates."""
    code = _strip_comments(_read(PAGE))
    assert "All companies" in code


def test_a_company_scoped_alert_resolves_to_a_name():
    """A raw UUID tells a reader nothing."""
    code = _strip_comments(_read(PAGE))
    assert "/admin/companies/" in code
    assert "companies[a.company_id]" in code


def test_the_company_lookup_is_best_effort():
    """A failed name lookup must degrade to an id, not break the alert board —
    the board matters more than the label."""
    code = _strip_comments(_read(PAGE))
    assert "allSettled" in code
    assert "?? `Company" in code or "?? 'Company" in code


# ── D3/D4: the fields that carry the meaning ─────────────────────────────────

def test_occurrence_and_recency_are_shown():
    """ADR-335 D2 records these precisely because "47 occurrences, still
    failing" is a different picture from "an alert exists"."""
    code = _strip_comments(_read(PAGE))
    assert "occurrence_count" in code
    assert "last_seen_at" in code
    assert "sinceLabel" in code, "last-seen is not rendered as relative time"


def test_a_self_resolved_alert_is_distinguishable_from_a_dismissed_one():
    """resolved_by_email is null on a self-resolve (ADR-335 D3) and that null
    carries meaning — the two imply opposite follow-ups."""
    code = _strip_comments(_read(PAGE))
    assert "resolved_by_email" in code
    assert "automatically" in code, "a self-resolve renders identically to a human one"


# ── D5: polls at the producer's interval ─────────────────────────────────────

def test_it_polls_at_the_heartbeat_interval():
    """Faster re-fetches data that cannot have changed; slower shows superseded
    state. ADR-337 runs every 10 minutes."""
    code = _strip_comments(_read(PAGE))
    assert "10 * 60 * 1000" in code


def test_the_poll_is_cleaned_up():
    code = _strip_comments(_read(PAGE))
    assert "clearInterval" in code


# ── D6 / Dim 4 ───────────────────────────────────────────────────────────────

def test_there_is_no_mobile_surface():
    """A cross-tenant infrastructure board has an audience of one and does not
    belong in every crew member's phone build."""
    mobile = os.path.abspath(os.path.join(FE, "..", "..", "mobile", "src"))
    if not os.path.isdir(mobile):
        pytest.skip("mobile/ not present in this checkout")
    hits = []
    for root, _dirs, files in os.walk(mobile):
        for f in files:
            if f.endswith((".ts", ".tsx")) and "platform/alerts" in open(
                os.path.join(root, f), errors="ignore"
            ).read():
                hits.append(f)
    assert not hits, f"mobile references the platform alert board: {hits}"


def test_the_type_matches_the_api_response():
    """Dim 4 — types.ts is hand-maintained, so it can drift from the schema."""
    ts = _read("api/types.ts")
    block = ts[ts.index("export interface PlatformAlert {"):]
    block = block[:block.index("}")]
    for field in P.PlatformAlertOut.model_fields:
        assert field in block, f"types.ts is missing {field}"

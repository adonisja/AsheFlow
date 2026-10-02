"""D9's endpoint has a client that calls it (ADR-485 D9, ADR-381).

ADR-381 recorded three features shipped as "done" whose endpoints no client ever
called -- one of them an invite revoke with no caller at all. `check_adr_coverage`
cannot catch that: it knows an ADR needs a journal and a lesson, not whether a
decision implied a user-visible change.

So the surface is pinned here. These tests read the FRONTEND from a backend test
on purpose -- the claim being defended is "the endpoint is reachable from the
app", and that claim spans both halves. A test living only in the frontend suite
would pass while the endpoint it calls was renamed.
"""
from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[3]
PAGE = ROOT / "frontend/src/pages/WalkerLog.tsx"
CLIENT = ROOT / "frontend/src/utils/myCampaigns.ts"
ROUTER = ROOT / "backend/app/routers/collection.py"


def test_the_discovery_module_exists_and_calls_the_real_path():
    """The path in the client matches the path the router mounts.

    Spelled out rather than compared to a constant: a shared constant would make
    a rename agree with itself on both sides while breaking the deployed client,
    which is the failure this test exists to catch.
    """
    src = CLIENT.read_text()
    assert "'/collection/my-campaigns'" in src
    assert '"/my-campaigns"' in ROUTER.read_text()


def test_the_page_imports_and_invokes_the_client():
    page = PAGE.read_text()
    assert "fetchMyCampaigns" in page, "WalkerLog does not import the D9 client"
    # Called, not merely imported. An unused import type-checks and ships.
    assert "void fetchMyCampaigns()" in page


def test_the_picker_sets_the_token_the_submit_path_already_uses():
    """Choosing a campaign writes the SAME state the paste field writes.

    If the picker set its own state, the submit button's `disabled` check and the
    localStorage persistence would both ignore it -- a campaign could be selected
    and the page would still refuse to send.
    """
    page = PAGE.read_text()
    assert "setCollectToken(c.token)" in page


def test_the_paste_field_survives():
    """Discovery is additive (ADR-415 D5).

    A collector outside the tenant, or signed out, has only the pasted link. If
    the picker ever replaces the field, those people lose the page entirely.
    """
    page = PAGE.read_text()
    assert 'placeholder="Paste the code you were given"' in page


def test_the_list_is_filtered_to_this_pages_dataset():
    """ADR-439 D8: an address page offering a route campaign's link is the bug
    that made the token key per-dataset. The filter must be on the fetch, not
    only in the render."""
    page = PAGE.read_text()
    assert "c.dataset === dataset" in page


def test_discovery_failure_degrades_instead_of_throwing():
    """A 401 on the public page is an expected state, not an error.

    Without the catch, a signed-out visitor's rejected discovery call becomes an
    unhandled rejection on a page whose entire premise is that it works with no
    backend at all.
    """
    src = CLIENT.read_text()
    assert "catch" in src and "return [];" in src


def test_discovery_does_not_live_in_the_public_submit_module():
    """`collectionSubmit.ts` documents at length why it avoids `axiosClient`.

    Putting a session-attaching call in it would contradict that file's stated
    contract, so the authed call gets its own module.
    """
    public = (ROOT / "frontend/src/utils/collectionSubmit.ts").read_text()
    assert "axiosClient" not in public.replace("Deliberately NOT using `axiosClient`", "")


CAMPAIGNS = ROOT / "frontend/src/pages/Campaigns.tsx"
APP = ROOT / "frontend/src/App.tsx"


def test_the_campaigns_page_lists_platform_campaigns():
    """ADR-485 D9 meeting point 1: "Campaigns" lists BOTH kinds.

    Re-read against the diff rather than against a summary of it (CLAUDE.md):
    the first version of D9 shipped the picker inside WalkerLog only, which
    satisfies "an authenticated user never needs the link" while missing the
    nav-section half of the same decision.
    """
    src = CAMPAIGNS.read_text()
    assert "fetchMyCampaigns" in src
    assert "void fetchMyCampaigns()" in src
    assert "Platform campaigns" in src


def test_the_empty_state_accounts_for_platform_campaigns():
    """"Nothing to answer right now." must not render above a listed campaign.

    The run list and the platform list are separate fetches, so an empty `runs`
    with a non-empty `platform` is a real state -- and the original empty-state
    condition only looked at `runs`.
    """
    src = CAMPAIGNS.read_text()
    assert "runs.length === 0 && platform.length === 0" in src


def test_the_platform_links_point_at_routes_that_exist():
    """The two datasets have two ROUTES, not one route with a tab param.

    `dataset` is a prop passed in App.tsx, so an invented `?tab=routes` would be
    silently ignored and both links would land on the routes page. This test
    reads App.tsx so a future route rename cannot leave the links dangling.
    """
    app = APP.read_text()
    assert 'path="/walker-log"' in app and 'dataset="routes"' in app
    assert 'path="/address-log"' in app and 'dataset="addresses"' in app

    src = CAMPAIGNS.read_text()
    assert "'/walker-log' : '/address-log'" in src, (
        "the platform links do not distinguish the two dataset routes")

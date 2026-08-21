"""A hub upload can be polled, and says something true (ADR-274 D15).

THE GAP
-------
`GET /sort/manifest/{date}/status` was keyed on the date alone, so it could only
ever answer for the COMPANY manifest. The Sort page worked around that by
skipping polling entirely after a hub upload and setting the phase to 'ready'
immediately — which rendered:

    "N packages ready — run sort below."

Three things wrong at once: the packages were NOT ready (enrichment was still
running), a hub never runs the station sort, and a failed enrichment would sit
under a green "ready" banner forever.

The workaround's own comment said hub packages "never feed a sort, so there is
no sort-readiness to wait for". That was true when written and D9 made it false:
a hub's manifest is exactly what its crew commits into routes.

THE FIX
-------
An optional `hub_truck_id` selects the scope. Every Redis read in the handler
derives from one `scope` variable, so the hub path is the same code with a
different key — `{date}` or `{date}#hub:{truck}`, the same namespace the upload
and commit-sort already use.
"""
from pathlib import Path

import pytest


BACKEND = Path(__file__).resolve().parents[2]
SORT_ROUTER = BACKEND / "app" / "routers" / "sort.py"
SORT_PAGE = BACKEND.parent / "frontend" / "src" / "pages" / "Sort.tsx"


def _handler() -> str:
    text = SORT_ROUTER.read_text(encoding="utf-8")
    start = text.index("def get_manifest_status(")
    end = text.index("\n@router.", start)
    body = text[start:end]
    # Drop the docstring too: it explains the hub scope at length and contains
    # every token these assertions look for, so matching it would pass against
    # a handler that had lost the code entirely.
    if '"""' in body:
        first = body.index('"""')
        second = body.index('"""', first + 3) + 3
        body = body[:first] + body[second:]
    out = []
    for raw in body.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        out.append(stripped)
    return "\n".join(out)


@pytest.fixture(scope="module")
def src() -> str:
    return _handler()


class TestStrippingWorks:
    def test_comments_gone_code_kept(self, src: str):
        assert "def get_manifest_status(" in src
        assert "ADR-274 D15" not in src, (
            "comments survived stripping — assertions could match prose"
        )


class TestScopeSelection:
    def test_endpoint_accepts_a_hub_truck_id(self, src: str):
        assert "hub_truck_id: Optional[UUID] = None" in src, (
            "the status endpoint cannot describe a hub's manifest, so the UI "
            "has to guess — which is what produced the false 'ready'"
        )

    def test_hub_scope_matches_the_upload_namespace(self, src: str):
        # Must be byte-identical to what /sort/upload and commit_sort write,
        # or the poll reports not_found forever on a healthy upload.
        assert 'scope = f"{date_str}#hub:{hub_truck_id}"' in src, (
            "hub scope does not match the upload's namespace"
        )

    def test_company_path_is_unchanged(self, src: str):
        assert "scope = date_str" in src, (
            "the company manifest must still be the default scope"
        )

    def test_every_redis_read_uses_the_scope(self, src: str):
        # The bug this prevents: fixing one key and leaving the others on
        # date_str, so a hub poll reads a mix of both manifests.
        for key in ("_enriching_key(cid_str, scope)",
                    'f"manifest_failed:{cid_str}:{scope}"',
                    "_manifest_key(cid_str, scope)",
                    'f"manifest_progress:{cid_str}:{scope}"'):
            assert key in src, f"{key} not scoped"
        for stale in ("_enriching_key(cid_str, date_str)",
                      "_manifest_key(cid_str, date_str)",
                      'f"manifest_progress:{cid_str}:{date_str}"'):
            assert stale not in src, (
                f"{stale} still reads the company key — a hub poll would mix "
                "the two manifests' states"
            )


class TestHubIdIsValidated:
    def test_unknown_or_non_hub_truck_is_rejected(self, src: str):
        # An arbitrary UUID would otherwise return not_found forever, which
        # reads as "nothing uploaded" rather than "that is not a hub".
        assert "Truck.id == hub_truck_id" in src
        assert "not truck.is_hub" in src, (
            "a regular truck id would be accepted and silently report not_found"
        )

    def test_validation_is_company_scoped(self, src: str):
        assert "Truck.company_id == caller.company_id" in src, (
            "cross-tenant: another company's hub id would be accepted"
        )


class TestFrontendPollsForHubs:
    @pytest.fixture(scope="class")
    def page(self) -> str:
        return SORT_PAGE.read_text(encoding="utf-8")

    def test_the_no_poll_workaround_is_gone(self, page: str):
        assert "A HUB UPLOAD DOES NOT POLL" not in page, (
            "the stale rationale is still in place — a hub upload jumps to "
            "'ready' while enrichment is still running"
        )
        assert "if (hubTruckId) {\n        setPhase('ready');" not in page

    def test_upload_starts_polling_with_the_hub_id(self, page: str):
        assert "startPolling(uploadDate, hubTruckId)" in page

    def test_poll_passes_the_hub_id_as_a_query_param(self, page: str):
        assert "hub_truck_id: hubId" in page, (
            "the poll would read the company manifest for a hub upload"
        )

    def test_hub_readiness_does_not_unlock_the_company_sort(self, page: str):
        # onReady sets manifestReady, which gates Run Sort. A hub's manifest
        # never feeds that sort (D2), so firing it would enable a control the
        # hub's packages are not part of.
        assert "if (!hubId) onReady(sortDate);" in page, (
            "a hub upload would unlock the company's Run Sort controls"
        )

    def test_ready_copy_does_not_tell_a_hub_to_run_the_sort(self, page: str):
        assert "the hub crew can commit their route sort now" in page, (
            "the ready banner still says 'run sort below', which does nothing "
            "for a hub manifest"
        )

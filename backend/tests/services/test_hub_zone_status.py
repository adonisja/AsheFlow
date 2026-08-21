"""A hub's commit gate opens on its own manifest, not on a TruckZone (ADR-274 D9).

RECOGNITION CUE
---------------
A readiness flag computed from ONE source, consumed by a feature that has two.

`/sort/{date}/zone-status` is the gate both UIs use to decide whether the
route-sort commit button is live. It derived `zoned` purely from `TruckZone`.
A hub is excluded from `run_sort` by design (ADR-274 D2), so it never has a
zone — which meant `zoned` was permanently false and the hub commit path in
`walker_routes.commit_sort` was correct, tested, and *unreachable from any UI*.
The backend work looked done because nothing in it was wrong.

Source-reading rather than behavioural. The handler needs Redis, a caller and a
scoped session; the property under test is which SOURCE feeds the flag, and that
is visible in the code. Every assertion below was proven by planting the
regression it names and watching it fail — a source test that matches a comment
instead of a code line passes against a bug, which has already happened here
once ("#hub:" matched the explanatory comment above the line).
"""
from pathlib import Path

import pytest


BACKEND = Path(__file__).resolve().parents[2]
SORT_ROUTER = BACKEND / "app" / "routers" / "sort.py"


def _handler_source() -> str:
    """`get_zone_status`'s body, CODE ONLY — comments stripped.

    Comments in this handler explain the hub rule at length and contain every
    token the assertions look for. Matching one would be a test that passes
    because the explanation exists, not because the behaviour does.
    """
    text = SORT_ROUTER.read_text(encoding="utf-8")
    start = text.index("def get_zone_status(")
    end = text.index("\n@router.", start)
    lines = []
    for raw in text[start:end].splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # Trailing comments only — a bare `.split("#")` would truncate the
        # f-string hub scope, which is the line most of this file tests.
        if "#" in stripped and '"' not in stripped and "'" not in stripped:
            stripped = stripped.split("#")[0].strip()
        if stripped:
            lines.append(stripped)
    return "\n".join(lines)


@pytest.fixture(scope="module")
def src() -> str:
    return _handler_source()


class TestSourceStrippingWorks:
    """Guards the guard — every other test is vacuous if this is broken."""

    def test_comments_are_gone_but_code_remains(self, src: str):
        assert "def get_zone_status(" in src, "handler not captured"
        assert "HUB READINESS COMES FROM ITS OWN MANIFEST" not in src, (
            "comments survived stripping — assertions below could match prose "
            "instead of code, the exact failure that let a planted bug pass"
        )

    def test_the_hub_scope_line_survived_stripping(self, src: str):
        # The scope is an f-string containing '#'. An over-eager comment strip
        # truncates it and silently removes the line under test.
        assert '#hub:' in src, (
            "the hub manifest scope line was truncated by comment-stripping"
        )


class TestHubReadinessSource:
    def test_hub_count_comes_from_the_manifest_key(self, src: str):
        # The whole point: a hub's packages live in its own Redis manifest,
        # namespaced per truck so two hubs never share one.
        assert "_manifest_key(" in src, (
            "zone-status never reads a manifest — a hub can only be 'zoned' "
            "via TruckZone, which it will never have (ADR-274 D2)"
        )
        assert 'f"{sort_date.isoformat()}#hub:{tid}"' in src, (
            "the hub manifest scope must be namespaced per truck and per date; "
            "an unscoped key reads the MAIN manifest and marks the hub ready "
            "off packages it does not carry"
        )

    def test_zoned_is_not_read_off_zones_alone(self, src: str):
        # The regression this file exists for.
        assert "zoned=by_truck.get(tid, 0) > 0" not in src.replace(" ", "").replace(
            "zoned=by_truck.get(tid,0)>0", "zoned=by_truck.get(tid, 0) > 0"
        ), "zoned still derives from TruckZone only — hubs stay un-committable"
        assert "hub_counts.get(tid, 0) if is_hub else by_truck.get(tid, 0)" in src, (
            "readiness must select its source by truck kind"
        )

    def test_hub_manifest_only_read_for_assigned_hubs(self, src: str):
        # A hub truck with no assignment today is not "ready", it is not
        # running. Reading manifests for every hub row would also mean a Redis
        # GET per hub on every poll from every driver.
        assert "if hub_assigned:" in src, (
            "manifest reads must be gated on there being an assigned hub"
        )
        assert "TruckAssignment.date == sort_date" in src, (
            "hub assignment lookup must be scoped to the requested date"
        )

    def test_corrupt_manifest_does_not_500(self, src: str):
        # Redis holds JSON written by another path. A malformed value must make
        # the hub 'not ready', never take down the gate for every truck.
        assert "except (json.JSONDecodeError, TypeError)" in src, (
            "a corrupt hub manifest would raise out of the readiness endpoint"
        )


class TestTenancyAndScope:
    """ADR-115 D1 — every query in the handler is company-scoped."""

    def test_hub_assignment_query_is_company_scoped(self, src: str):
        assert "TruckAssignment.company_id == caller.company_id" in src, (
            "the hub assignment lookup is a cross-tenant read without this"
        )

    def test_manifest_key_is_company_namespaced(self, src: str):
        # Redis has no row-level tenancy; the key IS the boundary. Reading
        # another tenant's hub manifest would leak their package count.
        assert "cid_str = str(caller.company_id)" in src
        assert "_manifest_key(cid_str," in src, (
            "the manifest key must carry the caller's company_id"
        )

    def test_truck_lookup_is_company_scoped(self, src: str):
        assert "Truck.company_id == caller.company_id" in src

    def test_scoped_caller_still_sees_only_their_truck(self, src: str):
        # A hub driver is TRUCK_SCOPED. Adding hubs to the oversight list must
        # not widen what a scoped caller sees.
        assert "if scope is not None:" in src
        assert "truck_ids = [scope]" in src, (
            "a driver/captain must still see exactly their own truck"
        )

    def test_unassigned_hub_visible_to_oversight(self, src: str):
        # Dispatch needs to see that a hub is waiting on its manifest; that is
        # the state they have to act on.
        assert "list(by_truck.keys()) + list(hub_assigned)" in src, (
            "an assigned hub with no manifest yet must still appear for "
            "oversight, otherwise 'waiting on manifest' is invisible"
        )
        assert "dict.fromkeys(" in src, (
            "the merged list must de-duplicate — a hub that somehow has a zone "
            "would otherwise be returned twice"
        )


class TestResponseContract:
    """`is_hub` exists so the UIs can say something true (ADR-274 D9)."""

    def test_is_hub_is_on_the_schema(self):
        text = SORT_ROUTER.read_text(encoding="utf-8")
        block = text[text.index("class ZoneStatusOut"):text.index("class ZoneStatusOut") + 700]
        assert "is_hub: bool = False" in block, (
            "without is_hub both UIs tell a hub driver to 'wait for station "
            "sort', which will never happen for a hub"
        )

    def test_is_hub_is_populated(self, src: str):
        assert "is_hub=is_hub" in src, "schema field exists but is never set"

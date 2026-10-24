"""The enriched-manifest CSV export must not silently drop enriched fields.

`download_enriched_manifest` writes with DictWriter(extrasaction="ignore"), so any
key produced by enrichment but absent from its `fields` list vanishes from the CSV
with no error. That bit us for real: an exported manifest was missing
first/second_cross_street (the route graph's cost-1 edges) and package_type (OV
half-slot cost), so re-running the sort from the CSV silently produced a degraded,
more-fragmented result.

This is a drift guard: it reads the field list from the router and the enriched-dict
keys from the enrichment task, and asserts the export covers everything.
"""
import re
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[2]
_ROUTER = _BACKEND / "app" / "routers" / "sort.py"
_TASK = _BACKEND / "app" / "tasks" / "enrich_manifest.py"


def _exported_fields() -> set[str]:
    """The `fields = [...]` list inside download_enriched_manifest."""
    src = _ROUTER.read_text()
    start = src.index("def download_enriched_manifest")
    block = src[start:start + 4000]
    m = re.search(r"fields\s*=\s*\[(.*?)\]", block, re.S)
    assert m, "could not locate the `fields = [...]` list in download_enriched_manifest"
    return set(re.findall(r'"([a-z_]+)"', m.group(1)))


def _enriched_keys() -> set[str]:
    """The keys `_enrich_one` actually returns, for both a door and a miss.

    Called, not regex-read: since ADR-584 the dict spreads the shared
    door/miss field builders (`**fields`), so its source literal no longer
    lists them and a source match saw only the base keys.
    """
    from unittest.mock import patch
    from app.services import door_resolver as DR
    from app.tasks import enrich_manifest as E

    door = DR.Door(borough="1", address="350 5 AVE", block_key="5_Ave_300", lat=40.7, lng=-73.9)

    class _S:
        def close(self):
            pass
    keys: set[str] = set()
    pkg = {"tba": "TBA1", "address": "350 5th Ave", "lat": 40.7, "lng": -73.9, "tag_number": None}
    with patch("app.database.PlaceTypeSession", _S):
        for result in (door, DR.Miss("not_in_placetype", address="350 5 AVE", borough="1")):
            with patch.object(DR, "resolve_door", lambda *a, **k: result):
                keys |= set(E._enrich_one(pkg, None)["enriched_pkg"])
    return keys


def test_export_covers_every_enriched_field():
    exported, enriched = _exported_fields(), _enriched_keys()
    missing = enriched - exported
    assert not missing, (
        "these enriched fields would be SILENTLY dropped from the CSV "
        f"(extrasaction='ignore'): {sorted(missing)} — add them to `fields` in "
        "download_enriched_manifest"
    )


@pytest.mark.parametrize("field", [
    # Routing-critical: the CSV must be usable to re-run a sort faithfully.
    "first_cross_street",   # cost-1 adjacency edges
    "second_cross_street",
    "package_type",         # OV size -> half-slot capacity cost
    "block_key",            # display identity
    "segment_id",           # LION routing identity (ADR-196)
    "lat", "lng",
    "bag_id",
    "bag_color",            # ADR-230
])
def test_routing_critical_field_is_exported(field):
    assert field in _exported_fields(), f"{field} missing from the CSV export"


def test_no_phantom_fields_exported():
    """Every exported column should actually exist in the enriched dict, or the CSV
    carries permanently-empty columns that look like real (but missing) data."""
    exported, enriched = _exported_fields(), _enriched_keys()
    phantom = exported - enriched
    assert not phantom, (
        f"exported columns not produced by enrichment: {sorted(phantom)} — they "
        "would always be blank"
    )

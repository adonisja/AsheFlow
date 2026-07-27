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
    """The keys of the `enriched_pkg = {...}` dict built by _enrich_one."""
    src = _TASK.read_text()
    m = re.search(r"enriched_pkg\s*=\s*\{(.*?)\n    \}", src, re.S)
    assert m, "could not locate the `enriched_pkg = {...}` dict in enrich_manifest"
    return set(re.findall(r'"([a-z_]+)":', m.group(1)))


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

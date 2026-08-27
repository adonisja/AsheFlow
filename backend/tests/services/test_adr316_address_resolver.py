"""PlaceType before GeoClient (ADR-316).

ADR-303 enumerates a zone, ADR-314 gives PlaceType a geometry tier, ADR-315
fills it nightly — and every caller then resolved a package address by calling
GeoClient anyway. Six call sites, not one checking a local table: no lru_cache,
no per-run dict. The data was preloaded and nothing read it.
"""
import ast
import inspect

from app.services import address_resolver as AR
from app.services import place_geometry as PG


def _code_only(obj) -> str:
    tree = ast.parse(inspect.getsource(obj))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef, ast.Module)):
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                node.body.pop(0)
    return ast.unparse(tree)


# ── D1: PlaceType is consulted first ─────────────────────────────────────────

def test_placetype_is_read_before_geoclient():
    src = _code_only(AR.resolve_address)
    assert src.index("_from_placetype") < src.index("_geoclient_normalise"), (
        "the whole point: read the cache before the network"
    )


def test_the_signature_is_drop_in_for_the_existing_callers():
    """Six call sites share `(address, borough=...)`. Converging them on one
    function is what stops a future strategy change being six edits — which is
    how the missing cache went unnoticed."""
    p = inspect.signature(AR.resolve_address).parameters
    assert list(p)[:3] == ["db", "address", "borough"]
    assert p["borough"].default == "manhattan"


# ── THE bug: two address vocabularies ────────────────────────────────────────

def test_the_lookup_survives_both_address_vocabularies():
    """AddressPoint and GeoClient name the same door differently:

        AddressPoint (stored)   GeoClient normalised
        350 5 AVE               350 5 AVENUE
        2 W 33 ST               2 WEST 33 STREET

    Measured: 0 of 4 matched. A cache keyed on the raw string could never hit —
    the first version of this resolver wrote 'AVENUE' rows and looked up 'AVE'
    ones, so it missed 100% of the time while appearing to work.

    `derive_block_key` collapses both forms to one key, so (house number,
    block_key) is a join that survives whichever source wrote the row.
    """
    from app.services.derive_block_key import derive_block_key
    for a, b in [("350 5 AVE", "350 5 AVENUE"),
                 ("2 W 33 ST", "2 WEST 33 STREET"),
                 ("410 W 45 ST", "410 WEST 45 STREET")]:
        ka = getattr(derive_block_key(a, tba=""), "block_key", None)
        kb = getattr(derive_block_key(b, tba=""), "block_key", None)
        assert ka == kb and ka is not None, f"{a} / {b}"

    src = _code_only(PG.enriched_building_with_segment)
    assert "derive_block_key" in src, (
        "the lookup must fall back to a vocabulary-independent key"
    )
    assert "block_key ==" in src


# ── D2: a partial row is a miss ──────────────────────────────────────────────

def test_a_bootstrap_only_row_is_a_miss():
    """It carries bin/lat/lng from AddressPoint and no topology — enough to
    place a pin, not enough to route. Serving it produces blank CSV columns
    nobody can explain."""
    src = _code_only(PG.enriched_building_with_segment)
    assert src.count("geo_enriched_at.isnot(None)") == 2, (
        "both the direct lookup and the block_key fallback must require it"
    )


def test_a_missing_segment_is_a_miss_not_a_partial_answer():
    """Topology lives on the segment; an enriched building whose segment was
    never persisted cannot answer a routing caller."""
    src = _code_only(AR._from_placetype)
    assert "if segment is None" in src
    assert "return None" in src


def test_geo_message_is_never_served_from_cache():
    """It describes ONE lookup's outcome ("ADDRESS NUMBER OUT OF RANGE").
    Replaying a stored message against a different request would misreport what
    just happened."""
    src = _code_only(AR._from_placetype)
    assert "geo_message=None" in src.replace(" ", "")


# ── D3: write-through ────────────────────────────────────────────────────────

def test_a_miss_warms_the_cache():
    """A cache that only fills from a batch job is stale for exactly the
    addresses that are new."""
    src = _code_only(AR.resolve_address)
    assert "_write_back" in src


def test_the_write_back_cannot_fail_the_caller():
    src = _code_only(AR.resolve_address)
    i = src.index("_write_back")
    assert "try:" in src[:i]
    assert "except" in src[i:]


def test_the_write_back_composes_the_owning_writers():
    """ADR-314 D1c's COALESCE and ADR-237 D2's ownership already hold in those
    modules; re-issuing SQL here would duplicate the invariants and drift."""
    src = _code_only(AR._write_back)
    assert "upsert_building_geometry" in src
    assert "upsert_segments" in src
    for forbidden in ("pg_insert", "db.add(", "on_conflict"):
        assert forbidden not in src


def test_a_row_without_a_block_key_is_not_written():
    """block_key is NOT NULL on the library and is the routing key; a row
    without one would be inert."""
    src = _code_only(AR._write_back)
    assert "if not block_key" in src


# ── D4: telemetry ────────────────────────────────────────────────────────────

def test_the_resolver_reports_its_own_hit_rate():
    """A cache with no hit-rate telemetry is one nobody will notice has stopped
    working — a normalisation drift or a non-NYC tenant sends it to zero while
    every call still succeeds."""
    s = AR.ResolverStats()
    assert s.as_dict()["hit_rate"] is None, "no calls yet — not 0.0"
    s.hits, s.misses = 3, 1
    assert s.as_dict()["hit_rate"] == 0.75


def test_stats_are_optional_so_callers_need_not_opt_in():
    assert inspect.signature(AR.resolve_address).parameters["stats"].default is None


# ── Boundary ─────────────────────────────────────────────────────────────────

def test_the_resolver_names_no_platform_model():
    """ADR-237: place_geometry owns the library tier and segment_map owns
    street_segments. The boundary test caught this module reaching for
    StreetSegment directly during development."""
    src = inspect.getsource(AR)
    assert "BuildingProfileLibrary" not in src
    assert "from app.models.street_segment" not in src

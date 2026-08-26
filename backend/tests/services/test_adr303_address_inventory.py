"""Zone-bootstrapped address inventory (ADR-303, ADR-313).

The segment map self-seeds from packages (`enrich_manifest`), which is
full-mode. A workforce tenant has no manifest, so nothing ever populates its
address inventory: verified on staging, 4 company_zones with bounds and ZERO
building_profiles.

This enumerates from NYC AddressPoint filtered server-side by the zone polygon.
Pass one builds the inventory only and makes zero GeoClient calls (D9) — segment
resolution costs ~1 call per address, measured at 4,786 for one real zone, five
times the ADR's original estimate.
"""
import ast
import inspect

from app.services import address_inventory as AI


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


# ── D7: server-side polygon filtering ────────────────────────────────────────

def test_the_polygon_filter_is_pushed_to_the_source():
    """967k records exist; a zone needs ~5k. Downloading the city to throw most
    of it away is the thing within_polygon() avoids."""
    src = _code_only(AI._fetch_page)
    assert "within_polygon" in src
    assert "$where" in src


def test_pagination_is_ordered_by_a_stable_key():
    """Paging without a stable $order silently repeats and drops rows."""
    assert "addresspointid" in _code_only(AI._fetch_page)


def test_polygon_from_bounds_renders_closed_wkt():
    poly = {"type": "Polygon", "coordinates": [[
        [-73.99, 40.75], [-73.98, 40.75], [-73.98, 40.76], [-73.99, 40.76], [-73.99, 40.75]]]}
    wkt = AI.polygon_from_bounds(poly)
    assert wkt.startswith("POLYGON((") and wkt.endswith("))")
    assert wkt.count(",") == 4          # 5 points, 4 separators


def test_an_unusable_polygon_yields_nothing_rather_than_raising():
    """A zone with no bounds is a zone we cannot enumerate, not an error."""
    for bad in ({}, {"type": "Point", "coordinates": [0, 0]},
                {"type": "Polygon", "coordinates": [[[0, 0], [1, 1]]]},
                {"type": "Polygon", "coordinates": []}):
        assert AI.polygon_from_bounds(bad) is None


# ── D7: the parser needs no mapping table ────────────────────────────────────

def test_addresspoint_street_format_feeds_the_real_parser():
    """`full_street_name` arrives padded ('W  55 ST'). After collapsing spaces it
    is exactly what derive_block_key expects — verified against the real
    function, not a copy of its rules."""
    from app.services.derive_block_key import derive_block_key
    cases = {
        ("400", "W  37 ST"): "W_37_St_400",
        ("493", "9 AVE"):    "9_Ave_400",
        ("230", "W  55 ST"): "W_55_St_200",
    }
    for (house, street), expected in cases.items():
        addr = f"{house} {AI._normalise_street(street)}"
        parsed = derive_block_key(addr, tba="")
        assert getattr(parsed, "block_key", None) == expected, addr


def test_the_tba_argument_carries_no_package_meaning():
    """derive_block_key requires a tba, which workforce mode does not have. It
    is used only to label an UnparseableAddress for reporting, so "" is correct
    — but a reader must not infer that packages are involved."""
    src = _code_only(AI.enumerate_zone_addresses)
    assert 'tba=' in src
    assert "PackageManifest" not in src and "TBA" not in src


# ── D9: no GeoClient in this pass ────────────────────────────────────────────

def test_the_bootstrap_makes_no_geoclient_calls():
    """THE scope boundary. Segment resolution costs ~1 call per address —
    measured at 4,786 for one real zone — and is deferred until that cost has a
    throughput design."""
    src = inspect.getsource(AI)
    assert "geoclient" not in src.lower() or "GeoClient being down" in src, (
        "pass one must not call GeoClient (ADR-303 D9)"
    )
    assert "upsert_segments" not in src
    assert "walk_connectors" not in src


# ── D2: bootstrap rows are distinguishable ───────────────────────────────────

def test_a_bootstrap_row_is_marked_as_not_human_submitted():
    """A machine-enriched address and a walker's observation carry different
    authority. Later work — verification, promotion to the library — must not
    treat a bootstrap row as though a human vouched for it."""
    src = _code_only(AI.persist_zone_inventory)
    assert "submitted_by_name" in src
    # submitted_by must NOT be set — its absence IS the marker
    assert "submitted_by " not in src.replace("submitted_by_name", "")
    assert AI.BOOTSTRAP_SUBMITTED_BY_NAME


def test_the_unknown_building_type_is_explicit_not_a_plausible_guess():
    """building_type is NOT NULL and AddressPoint does not carry it. Defaulting
    to 'walkup' would make the row assert an observation nobody made — the
    ADR-301 failure, a label claiming knowledge the code does not have."""
    assert AI.BOOTSTRAP_BUILDING_TYPE == "unknown"
    # 'standard' is _WORKLOAD_WEIGHTS' (1.0, 1.0) baseline: neutral effect on
    # the effort score, which is what an unobserved building should have.
    assert AI.BOOTSTRAP_WORKLOAD_CLASS == "standard"
    from app.services.route_sort import _WORKLOAD_WEIGHTS
    assert _WORKLOAD_WEIGHTS[AI.BOOTSTRAP_WORKLOAD_CLASS] == (1.0, 1.0)


def test_an_unseen_workload_class_falls_back_to_neutral():
    """Why 'unknown' is safe to introduce: route_sort reads workload_class, not
    building_type, and already tolerates an unseen value."""
    from app.services.route_sort import _WORKLOAD_WEIGHTS
    assert _WORKLOAD_WEIGHTS.get("unknown", (1.0, 1.0)) == (1.0, 1.0)


def test_an_existing_human_submission_is_never_overwritten():
    """The bootstrap supplies what is missing; it never overwrites an
    observation."""
    src = _code_only(AI.persist_zone_inventory)
    assert "skipped_existing" in src
    assert "in existing" in src


def test_an_unparseable_address_is_counted_not_silently_dropped():
    """block_key is NOT NULL and is the routing key; a row without one would be
    inert. Dimension 5: no silent drops."""
    # Assert on the AST: the counter must be INCREMENTED inside the block that
    # skips the row, not merely mentioned in the return dict. Checking for the
    # name alone let a mutation that deleted the increment pass.
    tree = ast.parse(_code_only(AI.persist_zone_inventory))
    incremented = any(
        isinstance(n, ast.AugAssign)
        and getattr(n.target, "id", None) == "skipped_unparseable"
        for n in ast.walk(tree)
    )
    assert incremented, (
        "an address with no block_key must be COUNTED, not silently dropped — "
        "block_key is NOT NULL and is the routing key, so the row would be inert"
    )


# ── Dimension 1 / 6 / 7 ──────────────────────────────────────────────────────

def test_persistence_is_company_scoped():
    src = _code_only(AI.persist_zone_inventory)
    assert "BuildingProfile.company_id == company_id" in src
    assert "company_id=company_id" in src.replace(" ", "")


def test_upstream_failure_does_not_leak_the_url_or_token():
    """The URL carries the zone polygon and the header carries the app token;
    neither belongs in a response body (Dimension 6)."""
    src = _code_only(AI._fetch_page)
    assert "str(exc)" not in src and "str(e)" not in src


def test_the_token_is_optional():
    """D8 — anonymous works, the token only raises the rate ceiling. Requiring
    it would make the feature untestable until one is registered."""
    src = _code_only(AI._fetch_page)
    assert "if settings.socrata_app_token" in src


def test_the_record_ceiling_is_bounded():
    """A polygon covering the city is a configuration mistake, not a big zone."""
    assert AI._MAX_RECORDS <= 100_000
    assert "_MAX_RECORDS" in _code_only(AI.enumerate_zone_addresses)

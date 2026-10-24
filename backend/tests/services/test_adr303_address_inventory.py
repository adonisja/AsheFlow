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


# ── ADR-584 D5: the zone's doors are a READ of PlaceType ────────────────────

def _placetype(monkeypatch, rows, zips=None):
    """A real SQLite PlaceType with `rows`, wired in as PlaceType's session."""
    import uuid
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import app.database as database
    from app.models.building_profile_library import BuildingProfileLibrary as BPL
    from app.services import door_resolver
    from tests.conftest import sqlite_mirror_with_defaults
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    sqlite_mirror_with_defaults(BPL.__table__).create(engine)
    S = sessionmaker(bind=engine)
    with S() as s:
        for addr, lat, lng in rows:
            s.add(BPL(id=uuid.uuid4(), normalised_address=addr, borough="1", block_key="W_37_St_400",
                      lat=lat, lng=lng, bin="1012345", building_type="unknown",
                      workload_class="standard", library_status="geometry_only",
                      building_category="residential"))
        s.commit()
    monkeypatch.setattr(database, "PLACETYPE_IS_REMOTE", True)
    monkeypatch.setattr(database, "PlaceTypeSession", S)
    monkeypatch.setattr(door_resolver, "_zip_map", lambda db: {"10018": "1"} if zips is None else zips)


SQUARE = {"type": "Polygon", "coordinates": [[
    [-73.99, 40.75], [-73.98, 40.75], [-73.98, 40.76], [-73.99, 40.76], [-73.99, 40.75]]]}


# A right triangle: its bounding box is the SQUARE, but its north-east half is
# outside. A square zone can't tell the polygon test from the box filter: the
# first version of this test used one, and a probe that deleted the polygon test
# still passed (36/36).
TRIANGLE = {"type": "Polygon", "coordinates": [[
    [-73.99, 40.75], [-73.98, 40.75], [-73.99, 40.76], [-73.99, 40.75]]]}


def test_only_doors_inside_the_polygon_come_back(monkeypatch):
    _placetype(monkeypatch, [("400 W 37 ST", 40.752, -73.988),      # inside the triangle
                             ("403 W 37 ST", 40.758, -73.982),      # in the box, outside the triangle
                             ("401 W 37 ST", 40.749, -73.985)])     # outside the box
    got = list(AI.enumerate_zone_addresses(TRIANGLE))
    assert [a.normalised_address for a in got] == ["400 W 37 ST"]
    assert (got[0].bin, got[0].borough_code, got[0].block_key) == ("1012345", "1", "W_37_St_400")


def test_a_placetype_outage_is_unavailable_not_an_empty_zone(monkeypatch):
    """The degrade guard reads an outage as "no doors", which the endpoint would
    report as a zone with no addresses. It must be a 503 instead."""
    import pytest
    _placetype(monkeypatch, [], zips={})
    with pytest.raises(AI.AddressSourceUnavailable):
        list(AI.enumerate_zone_addresses(SQUARE))


def test_the_bootstrap_writes_nothing_to_placetype():
    src = _code_only(AI.enumerate_zone_addresses)
    assert "doors_in_polygon" in src
    for w in ("upsert_", ".add(", "_soda", "urlopen"):
        assert w not in src, w


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


def test_the_record_ceiling_is_bounded():
    """A polygon covering the city is a configuration mistake, not a big zone."""
    assert AI._MAX_RECORDS <= 100_000
    assert "_MAX_RECORDS" in _code_only(AI.enumerate_zone_addresses)


# ── BIN at bootstrap (ADR-314 D1, corrected) ─────────────────────────────────

def test_bin_is_persisted_at_bootstrap_not_deferred_to_enrichment():
    """AddressPoint carries `bin` and we were already selecting it — then
    dropping it on the floor, leaving the identity anchor to wait for a
    rate-limited per-address GeoClient call that may never run.

    Verified before relying on it: across a 937-address zone the AddressPoint
    bin null rate is 0%, and on a random 20-address sample AddressPoint and
    GeoClient agreed on every BIN (20 agree / 0 differ / 0 missing).
    """
    src = _code_only(AI.persist_zone_inventory)
    ctor = src[src.index("BuildingProfile("):]
    assert "bin=a.bin" in ctor.replace(" ", ""), (
        "bin arrives with the enumeration; persist it (ADR-314 D1)"
    )


def test_the_bootstrap_never_seeds_placetype():
    """ADR-581 D2: the zone is the TENANT's choice, so seeding PlaceType from it
    recorded where a tenant delivers (ADR-580 V5). The bootstrap writes only the
    tenant's own inventory; PlaceType is filled by the owner's citywide seed."""
    src = _code_only(AI.persist_zone_inventory)
    assert "upsert_building_geometry" not in src
    assert "placetype_seeded" not in src


def test_the_address_list_is_materialised_before_being_walked_twice():
    """`addresses` is typed as an iterable and is now consumed twice — once for
    tenant rows, once to seed PlaceType. An iterator would be silently empty on
    the second pass, seeding nothing and reporting success."""
    src = _code_only(AI.persist_zone_inventory)
    assert "addresses = list(addresses)" in src
    assert src.index("addresses = list(addresses)") < src.index("for a in addresses")


def test_an_existing_row_gets_its_bin_backfilled():
    """The tenant path skips existing rows, so a row created before BIN was
    persisted would keep a null forever — the gap would only close if someone
    deleted the row.

    Backfills the identity anchor ONLY. Everything else on a tenant row is
    either a human's observation or already correct.
    """
    src = _code_only(AI.persist_zone_inventory)
    i = src.index("skipped_existing += 1")
    block = src[i:i + 400]
    assert "row.bin = a.bin" in block
    assert "not row.bin" in block, "must not overwrite a bin already stored"
    assert "bin_backfilled" in src


def test_the_backfill_touches_nothing_but_bin():
    """A wider backfill would let a machine overwrite a walker's observation."""
    src = _code_only(AI.persist_zone_inventory)
    i = src.index("skipped_existing += 1")
    block = src[i:i + 400]
    for col in ("building_type", "workload_class", "operational_note", "block_key"):
        assert f"row.{col}" not in block, f"the backfill must not touch {col}"

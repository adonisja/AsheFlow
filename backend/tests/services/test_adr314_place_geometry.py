"""PlaceType's geometry tier (ADR-314).

`building_profile_library` held 33 columns of building INTELLIGENCE and no
geometry at all — it could say a building was a walk-up with a tricky mailroom
and not say where it was.

Ground truth is identical for every tenant standing on it (ADR-237's test:
"independent of who is delivering"), so it belongs to PlaceType rather than to
the company-scoped BuildingProfile. Storing it per tenant would mean N
enrichments returning N identical answers, and would break the case where a
second tenant in the same city pays nothing for ground already mapped.
"""
import ast
import inspect

from app.library import client as LC
from app.models.building_profile import BuildingProfile
from app.models.building_profile_library import BuildingProfileLibrary
from app.models.street_segment import StreetSegment
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


# ── D0: ground truth lives on PlaceType, not the tenant table ────────────────

def test_ground_truth_columns_are_on_placetype():
    cols = {c.name for c in BuildingProfileLibrary.__table__.columns}
    for c in ("bin", "bbl", "zip_code", "lat", "lng", "segment_id",
              "corner_code", "structures_on_lot", "street_frontages",
              "geo_grc", "geo_enriched_at"):
        assert c in cols, f"{c} must live on PlaceType (ADR-314 D0a)"


def test_the_tenant_table_gains_only_the_join_key():
    """Anything more would mean N enrichments returning N identical answers,
    and would break the compounding effect a shared library exists for."""
    cols = {c.name for c in BuildingProfile.__table__.columns}
    assert "bin" in cols
    for c in ("bbl", "zip_code", "corner_code",
              "structures_on_lot", "street_frontages", "geo_enriched_at"):
        assert c not in cols, f"{c} is ground truth — it belongs to PlaceType (D0)"


def test_the_span_is_on_the_segment_not_the_address():
    """Verified live: three addresses on segment 0297696 all return the same
    000002000AA..000098000AA, so per-address storage would duplicate one fact
    ~18 times (the measured mean addresses per block_key)."""
    cols = {c.name for c in StreetSegment.__table__.columns}
    for c in ("low_house_number", "high_house_number",
              "first_cross_street", "second_cross_street"):
        assert c in cols
    bp = {c.name for c in BuildingProfile.__table__.columns}
    assert "low_house_number" not in bp and "first_cross_street" not in bp


# ── D0b: two write doors, disjoint columns ───────────────────────────────────

def test_enrichment_never_writes_an_intelligence_column():
    """THE invariant that makes two write doors safe. A machine-enriched row has
    city data and still knows nothing about what a building is like to deliver
    to (ADR-301's lesson as a schema rule)."""
    src = _code_only(PG)

    # Never mentioned at all: these are the promotion gate's alone.
    for col in ("operational_note", "opens_at", "closes_at", "note_verified",
                "building_type_status", "nomination_status",
                "agreement_source_count", "promoted_from_company_ids"):
        assert col not in src, (
            f"place_geometry must not write {col} — that is the promotion "
            f"gate's column (ADR-314 D0b)"
        )

    # building_type and workload_class ARE mentioned, because they are NOT NULL
    # and an insert cannot omit them. The invariant is narrower than "never
    # named": they must never be UPDATED. Asserted on the conflict set, which is
    # the only path that touches an existing row.
    upsert = _code_only(PG.upsert_building_geometry)
    after_conflict = upsert[upsert.index("on_conflict_do_update"):]
    for col in ("building_type", "workload_class"):
        assert col not in after_conflict, (
            f"{col} may be set on INSERT (NOT NULL) but must never be updated — "
            f"that would overwrite a human's observation (ADR-314 D0b)"
        )


def test_a_geometry_row_is_not_active_intelligence():
    """client.all_active() filters on nothing but library_status == 'active',
    and run_sort builds its workload dict straight from that result. A geometry
    row marked active would enter routing with a NULL workload_class read as
    verified-but-empty."""
    assert PG.GEOMETRY_ONLY == "geometry_only"
    assert PG.GEOMETRY_ONLY != "active"
    assert 'library_status == _ACTIVE' in inspect.getsource(LC.all_active) or \
           "_ACTIVE" in inspect.getsource(LC.all_active)


def test_a_promoted_row_is_never_demoted_by_a_later_enrichment():
    """library_status must be absent from the ON CONFLICT update set: an
    enrichment pass over an address a human already promoted must not reset it
    to geometry_only."""
    src = _code_only(PG.upsert_building_geometry)
    i = src.index("on_conflict_do_update")
    assert "library_status" not in src[i:], (
        "library_status must not appear in the conflict update set (D0b)"
    )


# ── D4 / ADR-237 D5: the boundary ────────────────────────────────────────────

def test_the_library_client_stays_read_only():
    """ADR-237 D5 is settled: "only ever nominate — AsheFlow pushes, the Library
    never reads tenant tables." client.py says so itself: WRITES ARE NOT HERE.

    Geometry follows segment_map.upsert_segments' precedent instead — a public
    fact from the City is not a nomination — so the nomination rule reads the
    same after this change as before.
    """
    src = inspect.getsource(LC)
    for w in ("db.add(", "db.commit(", "on_conflict", "insert("):
        assert w not in src, f"client.py must stay read-only, found {w!r}"


def test_geometry_writes_are_idempotent_by_public_identifier():
    """Concurrent bootstraps from different companies upsert the same public
    building; a race must not raise and must not duplicate. Same solution
    upsert_segments already uses for topology."""
    src = _code_only(PG.upsert_building_geometry)
    assert "on_conflict_do_update" in src
    assert "normalised_address" in src
    # ON CONFLICT cannot fire twice for one key in a single statement
    assert "seen" in src


def test_the_span_is_written_through_segment_map_not_a_second_writer():
    """`segment_map` owns every read and write of `street_segments` (ADR-237 D2)
    and `upsert_segments` already accepts optional keys.

    A first draft added `upsert_segment_spans` here, and the ADR-237 boundary
    test caught it — correctly. A second writer for one table is how ownership
    erodes.
    """
    from app.services import segment_map as SM
    assert not hasattr(PG, "upsert_segment_spans"), (
        "the span belongs in segment_map, which owns StreetSegment"
    )
    src = _code_only(SM.upsert_segments)
    for col in ("low_house_number", "high_house_number",
                "first_cross_street", "second_cross_street"):
        assert col in src, f"{col} must be written by upsert_segments (ADR-314 D3)"


def test_a_later_package_upsert_never_blanks_the_span():
    """Enrichment supplies the span; a package-driven upsert does not. A plain
    `set_` assignment would blank it on the very next sort — the same failure
    the existing topology comment warns about one line above."""
    from app.services import segment_map as SM
    src = _code_only(SM.upsert_segments)
    after = src[src.index("on_conflict_do_update"):]
    for col in ("low_house_number", "high_house_number",
                "first_cross_street", "second_cross_street"):
        i = after.index(col)
        assert "coalesce" in after[i:i + 200].lower(), (
            f"{col} must COALESCE against the stored value, not overwrite it"
        )


# ── D2: the projection, against the real response shape ──────────────────────

def test_the_v2_cross_street_fields_are_read_first():
    """GeoClient v2 returns lowCrossStreetName1/highCrossStreetName1; the older
    firstCrossStreetName* fields are ABSENT from v2 responses.

    A draft had the fallback order reversed and would have written NULL cross
    streets forever — silently, because the field simply is not in the payload.
    enrich_manifest already learned this; both paths now agree.
    """
    src = _code_only(PG.span_from_geoclient)
    assert src.index("lowCrossStreetName1") < src.index("firstCrossStreetNameNormalized")
    assert src.index("highCrossStreetName1") < src.index("secondCrossStreetNameNormalized")


def test_zero_padded_integers_are_parsed():
    """GeoClient returns '0001' / '03'. A string here would break any
    comparison a PlaceType consumer makes."""
    got = PG.geometry_from_geoclient({
        "numberOfExistingStructuresOnLot": "0001",
        "numberOfStreetFrontagesOfLot": "03",
    })
    assert got["structures_on_lot"] == 1
    assert got["street_frontages"] == 3


def test_blank_and_missing_fields_become_none_not_empty_strings():
    got = PG.geometry_from_geoclient({"bbl": "   ", "zipCode": ""})
    assert got["bbl"] is None and got["zip_code"] is None
    assert got["bin"] is None


def test_the_projection_is_a_subset_not_the_whole_response():
    """Measured: the full payload is 7,532 bytes/address — 36 MB for one
    4,786-address zone — against 497 for the named subset."""
    got = PG.geometry_from_geoclient({"dcpZoningMap": "8d", "atomicPolygon": "123"})
    assert "dcpZoningMap" not in got and "atomicPolygon" not in got
    assert set(got) <= set(PG._GEOMETRY_COLUMNS)


def test_a_row_without_the_not_null_keys_is_skipped():
    """normalised_address and block_key are NOT NULL on the table; a row missing
    either would raise mid-batch."""
    src = _code_only(PG.upsert_building_geometry)
    assert "if not addr or not bk" in src


def test_the_not_null_intelligence_columns_are_satisfied_on_insert():
    """Found by inserting against real Postgres, not by inspection.

    `building_type` and `workload_class` are NOT NULL on this table, so a
    geometry-only row cannot omit them — the structural tests all passed while
    every real INSERT raised NotNullViolation.

    ADR-303's sentinels are reused rather than relaxing the constraints:
    NOT NULL is doing real work for PROMOTED rows, where a missing building type
    is a broken promotion.
    """
    required = [
        c.name for c in BuildingProfileLibrary.__table__.columns
        if not c.nullable and c.default is None and c.server_default is None
    ]
    assert set(required) == {"normalised_address", "block_key",
                             "building_type", "workload_class"}

    src = _code_only(PG.upsert_building_geometry)
    assert "UNOBSERVED_BUILDING_TYPE" in src and "UNOBSERVED_WORKLOAD_CLASS" in src
    assert PG.UNOBSERVED_BUILDING_TYPE == "unknown"
    assert PG.UNOBSERVED_WORKLOAD_CLASS == "standard"


def test_the_sentinels_are_insert_only_and_never_overwrite_a_promotion():
    """An enrichment pass over an address a human already promoted must not
    reset its building_type to 'unknown'. Verified live: a promoted row kept
    status=active and building_type=elevator through a re-enrichment that
    updated its geometry."""
    src = _code_only(PG.upsert_building_geometry)
    i = src.index("on_conflict_do_update")
    for col in ("building_type", "workload_class", "library_status"):
        assert col not in src[i:], (
            f"{col} must not be in the conflict update set — it would demote a "
            f"promoted row (ADR-314 D0b)"
        )

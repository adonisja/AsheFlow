"""The geometry enrichment pass (ADR-315).

ADR-303 D9 deferred this pending measurement, after the address-count estimate
came in 5x low. Measured against the live API before designing around it:

    workers=1   2.98/s -> 4,786 addresses = 26.8 min
    workers=4  12.10/s -> 4,786 addresses =  6.6 min
    workers=8  19.06/s -> 4,786 addresses =  4.2 min   (0 errors at any level)

Minutes, not hours. So the risk was never that the pass is slow — it is that a
rate-limited external dependency shared with the sort path gets hammered by
something with no ceiling.
"""
import ast
import inspect

from app.tasks import enrich_geometry as EG


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


# ── D1: bounded concurrency ──────────────────────────────────────────────────

def test_concurrency_leaves_headroom_for_the_sort_path():
    """8 workers buys 2.4 minutes over 4 on a job that blocks nobody. The scarce
    resource is the City's API quota, shared with enrich_manifest on every
    full-mode sort."""
    assert EG._WORKERS == 4, "fixed at 4 (ADR-315 D1)"
    assert EG._WORKERS < 8


def test_the_batch_is_bounded():
    """Worst-case duration must be bounded by the batch, not by whatever a
    tenant defined as its operating area."""
    assert EG._BATCH <= 5000
    assert "pending_enrichment(db, _BATCH)" in _code_only(EG.enrich_place_geometry)


# ── D2: resumability ─────────────────────────────────────────────────────────

def test_the_pass_resumes_on_the_enriched_timestamp():
    # The query lives in place_geometry, which OWNS PlaceType's geometry tier —
    # the ADR-237 boundary test flagged the task importing the model directly,
    # correctly: a second module naming it is how ownership erodes.
    from app.services.place_geometry import pending_enrichment
    src = _code_only(pending_enrichment)
    assert "geo_enriched_at.is_(None)" in src
    assert "order_by" in src and "created_at" in src, (
        "oldest first, so a large zone cannot starve a smaller one added later"
    )
    assert "pending_enrichment" in _code_only(EG.enrich_place_geometry)


def test_the_bootstrap_seed_does_not_mark_a_row_enriched():
    """THE bug this cost. `geo_enriched_at` means "GeoClient has run", not "this
    row was written". The bootstrap seeds bin/lat/lng from AddressPoint, and
    when that stamped the timestamp the enrichment pass saw ZERO pending rows
    and silently never ran — caught only by running it end to end."""
    from app.services.place_geometry import upsert_building_geometry
    sig = inspect.signature(upsert_building_geometry)
    assert "mark_enriched" in sig.parameters
    assert sig.parameters["mark_enriched"].default is False, (
        "writing a row must NOT mark it enriched by default"
    )
    # the seed path must not opt in
    from app.services import address_inventory as AI
    seed = _code_only(AI.persist_zone_inventory)
    assert "mark_enriched" not in seed
    # the enrichment pass must
    assert "mark_enriched=True" in _code_only(EG.enrich_place_geometry)


# ── D3: a failure does not abort the batch ───────────────────────────────────

def test_a_failed_address_is_stamped_and_the_batch_continues():
    """One unresolvable address must not abort a 4,786-row pass. And the
    timestamp is stamped on failure too, on purpose: without it a permanently
    unresolvable address is retried on every future run and the pass never
    converges."""
    src = _code_only(EG.enrich_place_geometry)
    assert "if res is None" in src
    assert "continue" in src
    assert '"geo_grc": "ERR"' in src or "'geo_grc': 'ERR'" in src


# ── D5: compose the existing writers, add no SQL ─────────────────────────────

def test_the_pass_writes_only_through_the_owning_modules():
    """ADR-314 D0b's disjoint-column invariant and ADR-237's ownership boundary
    already hold in place_geometry and segment_map. A task that wrote either
    table directly would duplicate the invariants and drift from them."""
    src = inspect.getsource(EG)
    assert "upsert_building_geometry" in src
    assert "upsert_segments" in src
    for forbidden in ("pg_insert", "db.add(", "on_conflict", "session.execute("):
        assert forbidden not in src, f"the pass must add no SQL of its own ({forbidden})"


def test_it_never_reads_tenant_data():
    """Dim 1 — the pass reads PlaceType (tenant-free) and writes PlaceType. A
    BuildingProfile read here would be a company-scoped query and a boundary
    question."""
    src = inspect.getsource(EG)
    assert "BuildingProfile" not in src.replace("BuildingProfileLibrary", "")
    assert "company_id" not in src


# ── The full response, not the lossy dataclass ───────────────────────────────

def test_the_call_returns_the_full_response_not_geoclientresult():
    """`_geoclient_normalise` returns a dataclass keeping 14 fields and dropping
    the ones ADR-314 needs — bbl, zipCode, numberOfExistingStructuresOnLot,
    numberOfStreetFrontagesOfLot, cornerCode.

    A first draft called it and read a `.raw` attribute that does not exist,
    which would have enriched NOTHING while stamping every row as a failure.
    """
    import dataclasses
    from app.tasks.enrich_manifest import GeoClientResult
    fields = {f.name for f in dataclasses.fields(GeoClientResult)}
    for missing in ("bbl", "zip_code", "structures_on_lot",
                    "street_frontages", "corner_code"):
        assert missing not in fields, (
            "if GeoClientResult ever carries this, reuse it instead"
        )
    src = _code_only(EG._enrich_one)
    assert "_geoclient_normalise" not in src
    # ast.unparse normalises quotes to single — match the normalised form.
    assert "resp.json().get('address')" in src


def test_the_address_stripper_is_reused_not_reimplemented():
    """`strip_address_noise` removes unit/suite/floor text GeoClient cannot
    match — omitting it "silently failed ~90% of geocodes" per its own comment —
    and `_parse_house_and_street` splits the same way block_key derivation does."""
    src = _code_only(EG._enrich_one)
    assert "strip_address_noise" in src
    assert "_parse_house_and_street" in src


def test_a_failure_leaks_neither_the_url_nor_the_key():
    """Dimension 6 — the URL carries the address and the header carries the API
    key."""
    src = _code_only(EG._enrich_one)
    assert "str(exc)" not in src and "str(e)" not in src
    assert "exc_info" not in src or "exc_info=False" in src


# ── D6: scheduled ────────────────────────────────────────────────────────────

def test_the_task_is_scheduled_and_included():
    from app.celery_app import celery_app
    assert "enrich-place-geometry" in celery_app.conf.beat_schedule
    entry = celery_app.conf.beat_schedule["enrich-place-geometry"]
    assert entry["task"] == "app.tasks.enrich_geometry.enrich_place_geometry"
    # a scheduled task the worker never imports fails at runtime, not at startup
    assert "app.tasks.enrich_geometry" in celery_app.conf.include

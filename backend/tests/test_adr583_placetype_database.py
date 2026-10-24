"""ADR-583 — PlaceType in its own database, seeded from the city by the owner.

D3  every reader runs on PlaceType's session when it is remote, never the
    caller's tenant session (driven here with two separate databases);
D4  the health check reports whether the API's role can write;
D5  door identity is (borough, address);
D6  the seed turns AddressPoint into the address standard, and runs only with
    the writer role, never from the API.
"""
import ast
import inspect
import pathlib
import uuid

import pytest
from sqlalchemy import MetaData, create_engine
from sqlalchemy.orm import sessionmaker

import app.database as database
from app.library import client
from app.models.building_profile_library import BuildingProfileLibrary
from app.models.street_segment import StreetSegment
from app.placetype import seed
from app.services import place_geometry, segment_map
from tests.conftest import sqlite_mirror_with_defaults

BACKEND = pathlib.Path(__file__).resolve().parents[1]


def _placetype_engine():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    for model in (BuildingProfileLibrary, StreetSegment):
        sqlite_mirror_with_defaults(model.__table__).create(engine, checkfirst=True)
    return engine


def _library_row(**kw):
    base = dict(id=uuid.uuid4(), normalised_address="100 BROADWAY", block_key="Broadway_100",
                borough="1", building_type="unknown", workload_class="standard",
                library_status="active", building_category="residential")
    base.update(kw)
    return BuildingProfileLibrary(**base)


@pytest.fixture
def two_databases(monkeypatch):
    """A tenant database with nothing in it, and a PlaceType database with rows."""
    tenant = sessionmaker(bind=_placetype_engine())()      # same tables, but EMPTY
    pt_engine = _placetype_engine()
    pt = sessionmaker(bind=pt_engine)()
    pt.add_all([_library_row(), _library_row(normalised_address="100 BROADWAY", borough="3",
                                             block_key="Broadway_100"),
                StreetSegment(id=uuid.uuid4(), segment_id="0012345", source="city_seed",
                              from_lion_node_id="A", to_lion_node_id="B")])
    pt.commit()
    pt.close()
    monkeypatch.setattr(database, "PLACETYPE_IS_REMOTE", True)
    monkeypatch.setattr(database, "PlaceTypeSession", sessionmaker(bind=pt_engine))
    yield tenant
    tenant.close()


# ── D3 ──────────────────────────────────────────────────────────────────────

class TestReadersUsePlaceTypesOwnDatabase:
    def test_the_building_readers_ignore_the_tenant_session(self, two_databases):
        rows = client.all_active(two_databases)
        assert {r.borough for r in rows} == {"1", "3"}, "read from PlaceType, not the empty tenant db"
        assert client.by_addresses(two_databases, ["100 BROADWAY"])

    def test_the_topology_readers_ignore_the_tenant_session(self, two_databases):
        assert segment_map.by_segment_id(two_databases, "0012345").from_lion_node_id == "A"
        assert segment_map.known_segment_ids(two_databases, ["0012345", "9"]) == {"0012345"}
        assert segment_map.load_adjacency(two_databases, ["0012345"]) == {"0012345": set()}

    def test_without_a_remote_placetype_the_callers_session_is_used(self, monkeypatch):
        monkeypatch.setattr(database, "PLACETYPE_IS_REMOTE", False)

        def boom():
            raise AssertionError("opened a PlaceType session while PlaceType is local")
        monkeypatch.setattr(database, "PlaceTypeSession", boom)
        local = sessionmaker(bind=_placetype_engine())()
        local.add(_library_row())
        local.commit()
        assert len(client.all_active(local)) == 1

    def test_an_unreachable_placetype_degrades_to_empty(self, monkeypatch):
        from sqlalchemy.exc import OperationalError
        monkeypatch.setattr(database, "PLACETYPE_IS_REMOTE", True)

        def unreachable():
            raise OperationalError("connect", {}, Exception("refused"))
        monkeypatch.setattr(database, "PlaceTypeSession", unreachable)
        assert client.all_active(object()) == []
        assert segment_map.load_adjacency(object(), ["1"]) == {}

    def test_every_boundary_reader_is_routed(self):
        """Walks the boundary modules: a function that queries a PlaceType
        model through `db` must be @reads_placetype, unless it is a writer or
        a seed-only helper (which receive the writer's session)."""
        seed_only = {"upsert_segments", "upsert_building_geometry", "pending_enrichment",
                     "pending_enrichment_count", "segments_without_nodes", "create_table", "door_count",
                     "walk_connectors", "fetch_blockface"}
        missing = []
        for module in (client, segment_map, place_geometry):
            src = inspect.getsource(module)
            for node in ast.parse(src).body:
                if not isinstance(node, ast.FunctionDef) or node.name in seed_only:
                    continue
                body = ast.get_source_segment(src, node)
                if ("db.query(" in body or "db.execute(" in body) and not getattr(
                        getattr(module, node.name), "__reads_placetype__", False):
                    missing.append(f"{module.__name__}.{node.name}")
        assert not missing, f"read through the caller's tenant session: {missing}"


# ── D5 ──────────────────────────────────────────────────────────────────────

class TestDoorIdentity:
    def test_the_same_address_in_two_boroughs_is_two_doors(self, two_databases):
        assert client.by_address(two_databases, "100 BROADWAY", borough="3").borough == "3"
        assert client.by_address(two_databases, "100 BROADWAY", borough="1").borough == "1"

    def test_an_ambiguous_lookup_answers_none_rather_than_guessing(self, two_databases):
        assert client.by_address(two_databases, "100 BROADWAY") is None

    def test_the_unique_key_is_the_pair(self):
        uniques = [c for c in BuildingProfileLibrary.__table__.constraints
                   if c.__class__.__name__ == "UniqueConstraint"]
        assert [sorted(col.name for col in c.columns) for c in uniques] == [["borough", "normalised_address"]]

    def test_the_migration_matches_the_model(self):
        (mig,) = list((BACKEND / "alembic/versions").glob("*_adr583_placetype_door_identity.py"))
        src = mig.read_text()
        assert '"uq_building_profile_library_door"' in src and '["borough", "normalised_address"]' in src
        assert 'sa.Column("borough", sa.String(1), nullable=True)' in src
        col = BuildingProfileLibrary.__table__.c.borough
        assert col.type.length == 1 and col.nullable

    def test_a_row_without_a_borough_is_not_written(self):
        class Capture:
            def __init__(self):
                self.stmt = None

            def execute(self, stmt):
                self.stmt = stmt
        db = Capture()
        n = place_geometry.upsert_building_geometry(db, [
            {"normalised_address": "1 MAIN ST", "block_key": "Main_St_0"},
            {"normalised_address": "1 MAIN ST", "block_key": "Main_St_0", "borough": "3"},
            {"normalised_address": "1 MAIN ST", "block_key": "Main_St_0", "borough": "4"},
        ])
        assert n == 2, "the borough-less row is skipped; the other two are different doors"


# ── D6: the seed ────────────────────────────────────────────────────────────

class TestTheSeed:
    def test_addresspoint_rows_come_out_in_the_standard(self):
        raw = [
            {"house_number": "455A", "full_street_name": "W  32 ST", "boroughcode": "1",
             "bin": "1012345", "zipcode": "10001", "the_geom": {"coordinates": [-73.99, 40.75]}},
            {"house_number": "123-45", "full_street_name": "QUEENS BLVD", "boroughcode": "4"},
            {"house_number": "1", "full_street_name": "WEST ST", "boroughcode": "1"},
            {"house_number": "", "full_street_name": "NOWHERE ST", "boroughcode": "1"},
            {"house_number": "5", "full_street_name": "MAIN ST", "boroughcode": "9"},
        ]
        rows = list(seed.addresspoint_rows(raw))
        assert [(r["normalised_address"], r["borough"]) for r in rows] == [
            ("455A W 32 ST", "1"), ("123-45 QUEENS BLVD", "4"), ("1 WEST ST", "1")]
        assert rows[0]["lat"] == 40.75 and rows[0]["lng"] == -73.99 and rows[0]["bin"] == "1012345"
        assert rows[0]["block_key"] and rows[2]["block_key"], "lettered and direction-named both get a block"

    def test_the_seed_refuses_without_the_writer_role(self, monkeypatch):
        monkeypatch.delenv("PLACETYPE_WRITER_URL", raising=False)
        with pytest.raises(SystemExit, match="writer role"):
            seed.writer_session()

    def test_the_seed_refuses_the_app_database(self, monkeypatch):
        monkeypatch.setenv("PLACETYPE_WRITER_URL", seed.settings.database_url)
        with pytest.raises(SystemExit, match="app database"):
            seed.writer_session()

    def test_a_door_splits_into_house_and_street(self):
        assert seed._split("123-45 QUEENS BLVD") == ("123-45", "QUEENS BLVD")

    def test_nothing_in_the_api_imports_the_seed(self):
        offenders = []
        for p in (BACKEND / "app").rglob("*.py"):
            if "placetype" in p.parts:
                continue
            for n in ast.walk(ast.parse(p.read_text())):
                mod = getattr(n, "module", None) or ""
                names = [a.name for a in getattr(n, "names", [])] if isinstance(n, ast.Import) else []
                if "app.placetype" in mod or any(x.startswith("app.placetype") for x in names):
                    offenders.append(str(p.relative_to(BACKEND)))
        assert not offenders, f"the seed runs as the owner's own process only: {offenders}"


def test_a_span_without_nodes_keeps_the_nodes_already_known():
    """upsert_segments COALESCEs the LION nodes: a geoclient re-run (spans,
    no nodes) must not erase what the nodes stage found."""
    from sqlalchemy.dialects import postgresql

    class Capture:
        def execute(self, stmt):
            self.sql = str(stmt.compile(dialect=postgresql.dialect()))
    db = Capture()
    segment_map.upsert_segments(db, [{"segment_id": "1"}])
    assert "from_lion_node_id = coalesce(excluded.from_lion_node_id" in db.sql
    assert "to_lion_node_id = coalesce(excluded.to_lion_node_id" in db.sql


def test_the_health_probe_rolls_back_and_reports():
    from sqlalchemy.exc import ProgrammingError
    from app.services import placetype_health

    class Session:
        def __init__(self, refuse):
            self.refuse, self.rolled_back, self.committed = refuse, False, False

        def execute(self, stmt):
            if self.refuse:
                raise ProgrammingError("INSERT", {}, Exception("permission denied"))

        def rollback(self):
            self.rolled_back = True

        def commit(self):
            self.committed = True
    reader, writer = Session(refuse=True), Session(refuse=False)
    assert placetype_health._can_write(reader) is False
    assert placetype_health._can_write(writer) is True
    assert reader.rolled_back and writer.rolled_back and not writer.committed


def test_the_geoclient_limit_is_honoured(monkeypatch):
    """A --limit 50 trial processed 500 on real Postgres: the limit was checked
    only after a full batch. Each fetch is now capped at what remains."""
    asked = []

    def pending(db, size, after_id=None):
        asked.append(size)
        return [(i, f"{i} MAIN ST", "Main_St_0", "1") for i in range(size)]
    monkeypatch.setattr(place_geometry, "pending_enrichment", pending)
    monkeypatch.setattr(place_geometry, "upsert_building_geometry", lambda *a, **k: 0)
    monkeypatch.setattr(seed, "geoclient_address", lambda *a: None)
    monkeypatch.setattr(seed.settings, "geoclient_app_key", "k")

    class DB:
        def commit(self):
            pass
    out = seed.stage_geoclient(DB(), rate=1000, limit=50)
    assert asked == [50] and out["looked_up"] == 50

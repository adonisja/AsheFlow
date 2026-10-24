"""ADR-584 step 1 — a customer's address resolves to a PlaceType door, or a
Miss the tenant picks from. No GeoClient, no write.
"""
import inspect
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.database as database
from app.models.building_profile_library import BuildingProfileLibrary as BPL
from app.models.street_segment import StreetSegment
from app.services import door_resolver as R
from app.services import place_geometry
from tests.conftest import sqlite_mirror_with_defaults


def _door(address, borough, block_key, lat, lng, zip_code=None, segment_id=None):
    return BPL(id=uuid.uuid4(), normalised_address=address, borough=borough, block_key=block_key,
               lat=lat, lng=lng, zip_code=zip_code, segment_id=segment_id,
               building_type="unknown", workload_class="standard", library_status="geometry_only",
               building_category="residential")


@pytest.fixture(autouse=True)
def _fresh_zip_cache():
    R._zip_cache.update(map=None, at=0.0)
    yield
    R._zip_cache.update(map=None, at=0.0)


@pytest.fixture
def pt(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    for m in (BPL, StreetSegment):
        sqlite_mirror_with_defaults(m.__table__).create(engine, checkfirst=True)
    s = sessionmaker(bind=engine)()
    s.add_all([
        _door("350 5 AVE", "1", "5_Ave_300", 40.7484, -73.9857, "10118", "0034567"),
        _door("2 WEST 33 STREET", "1", "W_33_St_0", 40.7480, -73.9870, "10001"),
        _door("100 BROADWAY", "1", "Broadway_100", 40.7081, -74.0113, "10005"),
        _door("100 BROADWAY", "3", "Broadway_100", 40.7090, -73.9590, "11249"),
        _door("1 SHARED ZIP RD", "4", "Shared_Zip_Rd_0", 40.75, -73.86, "11370"),
        _door("2 SHARED ZIP RD", "2", "Shared_Zip_Rd_0", 40.80, -73.88, "11370"),
        StreetSegment(id=uuid.uuid4(), segment_id="0034567", source="city_seed",
                      first_cross_street="W 33 ST", second_cross_street="W 34 ST",
                      from_lion_node_id="A", to_lion_node_id="B"),
    ])
    s.commit()
    monkeypatch.setattr(database, "PLACETYPE_IS_REMOTE", False)
    yield s
    s.close()


class TestResolveDoor:
    def test_a_zip_in_the_text_picks_the_borough_and_the_door(self, pt):
        d = R.resolve_door(pt, "Jane Sample 350 Fifth Avenue Apt 4B, New York NY 10118")
        assert isinstance(d, R.Door)
        assert (d.borough, d.address, d.segment_id, d.first_cross_street) == ("1", "350 5 AVE", "0034567", "W 33 ST")

    def test_the_nearest_door_picks_the_borough_when_there_is_no_zip(self, pt):
        d = R.resolve_door(pt, "100 Broadway", lat=40.7091, lng=-73.9591)
        assert d.borough == "3"

    def test_without_a_borough_only_a_unique_address_matches(self, pt):
        assert isinstance(R.resolve_door(pt, "350 5th Ave"), R.Door)
        miss = R.resolve_door(pt, "100 Broadway")
        assert isinstance(miss, R.Miss) and miss.reason == "no_borough_match"

    def test_the_same_house_on_the_same_block_matches_another_spelling(self, pt):
        d = R.resolve_door(pt, "2 W 33 St, New York NY 10001")
        assert d.address == "2 WEST 33 STREET", "house 2 on W_33_St_0, spelled the GeoClient way"

    def test_a_door_without_topology_is_still_a_door(self, pt):
        d = R.resolve_door(pt, "100 Broadway NY 10005")
        assert isinstance(d, R.Door) and d.segment_id is None and d.lat == 40.7081

    def test_a_miss_carries_the_canonical_form_and_nearby_doors_never_the_raw_text(self, pt):
        miss = R.resolve_door(pt, "Jane Sample 352 Fifth Avenue Apt 9, NY 10118", lat=40.7484, lng=-73.9857)
        assert isinstance(miss, R.Miss) and miss.reason == "not_in_placetype"
        assert miss.address == "352 5 AVE" and "JANE" not in repr(miss).upper() and "APT" not in repr(miss)
        assert miss.near and miss.near[0]["address"] == "350 5 AVE"

    def test_an_empty_address_is_a_miss(self, pt):
        assert R.resolve_door(pt, "  ").reason == "no_address"


class TestReads:
    def test_a_zip_spanning_two_boroughs_decides_nothing(self, pt):
        z = place_geometry.zip_boroughs(pt)
        assert z["10118"] == "1" and "11370" not in z

    def test_nearby_is_bounded_by_radius_and_count(self, pt):
        near = place_geometry.doors_near(pt, 40.7484, -73.9857, radius_m=150)
        assert [d["address"] for d in near] == ["350 5 AVE", "2 WEST 33 STREET"]
        assert place_geometry.doors_near(pt, 40.7484, -73.9857, radius_m=20) == [
            {"address": "350 5 AVE", "borough": "1", "distance_m": 0.0, "lat": 40.7484, "lng": -73.9857}]
        assert len(place_geometry.doors_near(pt, 40.7484, -73.9857, radius_m=150, limit=1)) == 1

    def test_a_picked_door_must_exist(self, pt):
        assert R.door_from_pick(pt, "1", "350 5 AVE").address == "350 5 AVE"
        assert R.door_from_pick(pt, "3", "350 5 AVE") is None

    def test_an_unreachable_placetype_is_a_miss_not_a_crash(self, monkeypatch):
        from sqlalchemy.exc import OperationalError
        monkeypatch.setattr(database, "PLACETYPE_IS_REMOTE", True)

        def down():
            raise OperationalError("connect", {}, Exception("refused"))
        monkeypatch.setattr(database, "PlaceTypeSession", down)

        class Tenant:
            def query(self, *a):
                raise AssertionError("the resolver read a tenant table")
        assert R.resolve_door(Tenant(), "350 5th Ave", lat=40.7, lng=-73.9).reason == "no_borough_match"


class TestTheResolverNeverLeaves:
    def test_no_geoclient_and_no_write_in_the_resolver(self):
        src = inspect.getsource(R) + inspect.getsource(place_geometry.door_with_segment) \
            + inspect.getsource(place_geometry.doors_near) + inspect.getsource(place_geometry.zip_boroughs)
        # Session writes, not any ".add(": the first version matched set().add() in zip_boroughs.
        for forbidden in ("_geoclient", "api.nyc.gov", "requests.", "upsert_", "db.add(", "db.commit(", "db.execute(insert"):
            assert forbidden not in src, forbidden


class TestTheEndpoint:
    def test_it_is_bounded_gated_and_rate_limited(self):
        from app.main import app
        from app.routers import placetype_doors as P
        params = {p["name"]: p for p in app.openapi()["paths"]["/api/v1/placetype/doors/nearby"]["get"]["parameters"]}
        assert params["lat"]["schema"]["minimum"] == 40.47 and params["lng"]["schema"]["maximum"] == -73.68
        assert params["street"]["schema"]["anyOf"][0]["maxLength"] == 60
        src = inspect.getsource(P.nearby_doors)
        assert "_allow_pick" in src
        assert "@limiter.limit" in inspect.getsource(P)
        assert set(P.NearbyDoor.model_fields) == {"address", "borough", "distance_m", "lat", "lng"}


def test_the_zip_map_is_built_once_and_a_blank_is_never_cached(pt, monkeypatch):
    calls = []
    real = place_geometry.zip_boroughs
    monkeypatch.setattr(place_geometry, "zip_boroughs", lambda db: calls.append(1) or real(db))
    R.resolve_door(pt, "350 5 Ave NY 10118")
    R.resolve_door(pt, "350 5 Ave NY 10118")
    assert len(calls) == 1
    R._zip_cache.update(map=None, at=0.0)
    monkeypatch.setattr(place_geometry, "zip_boroughs", lambda db: {})
    R.resolve_door(pt, "350 5 Ave NY 10118")
    assert R._zip_cache["map"] is None, "an unreachable PlaceType must not pin an empty map"


def test_the_default_borough_decides_when_nothing_else_does(pt):
    assert R.resolve_door(pt, "100 Broadway").reason == "no_borough_match"
    assert R.resolve_door(pt, "100 Broadway", default_borough="3").borough == "3"


def test_the_company_borough_comes_from_company_config(db):
    from app.models.company import CompanyConfig
    from tests.conftest import SEED_COMPANY_ID
    cfg = db.query(CompanyConfig).filter(CompanyConfig.company_id == SEED_COMPANY_ID).one()
    assert R.company_borough(db, SEED_COMPANY_ID) is None
    cfg.geoclient_borough = "brooklyn"
    db.commit()
    assert R.company_borough(db, SEED_COMPANY_ID) == "3"

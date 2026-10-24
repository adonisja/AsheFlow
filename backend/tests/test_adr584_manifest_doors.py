"""ADR-584 step 2 — a manifest package resolves to a PlaceType door, or is held
until dispatch picks a door or drops a pin. No GeoClient on this path.
"""
import ast
import json
import pathlib
import uuid
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.routers import sort as S
from app.services import door_resolver as DR
from app.tasks import enrich_manifest as E

BACKEND = pathlib.Path(__file__).resolve().parents[1]
DOOR = DR.Door(borough="1", address="350 5 AVE", block_key="5_Ave_300", lat=40.7484, lng=-73.9857,
               segment_id="0034567", first_cross_street="W 33 ST", second_cross_street="W 34 ST")


class _Session:
    def close(self):
        pass


@pytest.fixture
def placetype(monkeypatch):
    monkeypatch.setattr("app.database.PlaceTypeSession", _Session)


def _enrich(monkeypatch, result, **pkg):
    monkeypatch.setattr(DR, "resolve_door", lambda *a, **k: result)
    base = {"tba": "TBA1", "address": "350 5th Ave", "lat": 40.7, "lng": -73.9}
    return E._enrich_one({**base, **pkg}, None)


class TestEnrichment:
    def test_a_door_fills_the_package(self, monkeypatch, placetype):
        out = _enrich(monkeypatch, DOOR)
        p = out["enriched_pkg"]
        assert p["door_status"] == "resolved" and p["normalised_address"] == "350 5 AVE"
        assert (p["segment_id"], p["first_cross_street"], p["lat"]) == ("0034567", "W 33 ST", 40.7484)
        assert out["failed_entry"] is None

    def test_a_miss_is_held_with_amazons_position_and_a_parser_block(self, monkeypatch, placetype):
        out = _enrich(monkeypatch, DR.Miss("not_in_placetype", address="352 5 AVE", borough="1"))
        p = out["enriched_pkg"]
        assert DR.is_held(p) and p["geocode_reason"] == "not_in_placetype"
        assert (p["lat"], p["lng"]) == (40.7, -73.9), "Amazon's coordinates start the picker"
        assert p["block_key"] == "5_Ave_300" and p["normalised_address"] is None
        assert out["failed_entry"]["reason"] == "not_in_placetype"

    def test_no_address_is_held(self, monkeypatch, placetype):
        p = _enrich(monkeypatch, DOOR, address="")["enriched_pkg"]
        assert DR.is_held(p) and p["geocode_reason"] == "missing_address"

    def test_a_door_the_seed_has_not_reached_is_placed_but_warned(self, monkeypatch, placetype):
        bare = DR.Door(borough="1", address="1 WEST ST", block_key="West_St_0", lat=40.70, lng=-74.01)
        p = _enrich(monkeypatch, bare)["enriched_pkg"]
        assert p["door_status"] == "resolved" and p["geo_warning"] == "no_segment_topology"

    def test_a_manifest_written_before_adr584_holds_nothing(self):
        assert not DR.is_held({"tba": "T", "geocode_reason": "geoclient_no_match"})


class TestThePatchRequest:
    def test_exactly_one_of_address_door_or_pin(self):
        S.ManifestPackagePatchRequest(corrected_address="350 5th Ave")
        S.ManifestPackagePatchRequest(door={"borough": "1", "address": "350 5 AVE"})
        S.ManifestPackagePatchRequest(pin={"lat": 40.75, "lng": -73.98})
        for bad in ({}, {"corrected_address": "350 5th Ave", "pin": {"lat": 40.75, "lng": -73.98}}):
            with pytest.raises(ValidationError):
                S.ManifestPackagePatchRequest(**bad)

    def test_it_is_bounded(self):
        for bad in ({"corrected_address": "x" * 301},
                    {"door": {"borough": "6", "address": "350 5 AVE"}},
                    {"door": {"borough": "1", "address": "350 5 AVE", "extra": 1}},
                    {"pin": {"lat": 51.5, "lng": -0.12}}):
            with pytest.raises(ValidationError):
                S.ManifestPackagePatchRequest(**bad)


class _Redis:
    def __init__(self, packages):
        self.store = {}
        self.packages = packages

    def get(self, key):
        return self.store.get(key, json.dumps(self.packages) if key.startswith("manifest:") else None)

    def setex(self, key, ttl, value):
        self.store[key] = value

    def ttl(self, key):
        return 3600


def _patch(monkeypatch, body, pkg):
    r = _Redis([pkg])
    monkeypatch.setattr(S, "_redis", lambda: r)
    caller = SimpleNamespace(company_id=uuid.uuid4())
    out = S.patch_manifest_package(date(2026, 10, 24), pkg["tba"], S.ManifestPackagePatchRequest(**body),
                                   caller=caller, _={})
    stored = json.loads(r.store[S._manifest_key(str(caller.company_id), "2026-10-24")])[0]
    return out, stored


HELD = {"tba": "TBA9", "raw_address": "352 Fifth Ave", "lat": 40.7484, "lng": -73.9857,
        "door_status": "unresolved", "geocode_reason": "not_in_placetype"}


class TestThePatchEndpoint:
    def test_a_picked_door_resolves_the_package(self, monkeypatch, placetype):
        monkeypatch.setattr(DR, "door_from_pick", lambda db, b, a: DOOR)
        out, stored = _patch(monkeypatch, {"door": {"borough": "1", "address": "350 5 AVE"}}, HELD)
        assert out.door_status == "resolved" and out.enriched and stored["segment_id"] == "0034567"
        assert stored["raw_address"] == "352 Fifth Ave", "the manifest text stays for the day"

    def test_a_door_not_in_placetype_is_refused(self, monkeypatch, placetype):
        monkeypatch.setattr(DR, "door_from_pick", lambda db, b, a: None)
        with pytest.raises(HTTPException) as e:
            _patch(monkeypatch, {"door": {"borough": "1", "address": "999 NOWHERE ST"}}, HELD)
        assert e.value.status_code == 422

    def test_a_pin_near_a_door_takes_it(self, monkeypatch, placetype):
        from app.services import place_geometry
        monkeypatch.setattr(place_geometry, "doors_near",
                            lambda db, lat, lng, **k: [{"borough": "1", "address": "350 5 AVE"}])
        monkeypatch.setattr(DR, "door_from_pick", lambda db, b, a: DOOR)
        out, stored = _patch(monkeypatch, {"pin": {"lat": 40.7484, "lng": -73.9857}}, HELD)
        assert out.door_status == "pinned" and stored["normalised_address"] == "350 5 AVE"
        assert not DR.is_held(stored)

    def test_a_pin_with_no_door_nearby_stands_alone_and_releases_the_package(self, monkeypatch, placetype):
        from app.services import place_geometry
        monkeypatch.setattr(place_geometry, "doors_near", lambda db, lat, lng, **k: [])
        out, stored = _patch(monkeypatch, {"pin": {"lat": 40.75, "lng": -73.98}}, HELD)
        assert out.door_status == "pinned" and (stored["lat"], stored["lng"]) == (40.75, -73.98)
        assert stored["normalised_address"] is None and stored["geo_warning"] == "pinned_without_door"
        assert not DR.is_held(stored)

    def test_a_corrected_address_that_still_misses_stays_held(self, monkeypatch, placetype):
        monkeypatch.setattr(DR, "company_borough", lambda db, cid: None)
        def _gen():
            yield None
        monkeypatch.setattr("app.database.get_db", _gen)
        monkeypatch.setattr(DR, "resolve_door", lambda *a, **k: DR.Miss("not_in_placetype", address="354 5 AVE"))
        out, stored = _patch(monkeypatch, {"corrected_address": "354 Fifth Avenue"}, HELD)
        assert out.door_status == "unresolved" and not out.enriched and DR.is_held(stored)


class TestTheGates:
    def test_the_sort_will_not_run_while_a_package_is_held(self, monkeypatch):
        r = _Redis([HELD, {"tba": "TBA2", "door_status": "resolved"}])
        monkeypatch.setattr(S, "_redis", lambda: r)
        caller = SimpleNamespace(company_id=uuid.uuid4(), id=uuid.uuid4(), legal_name="x")
        with pytest.raises(HTTPException) as e:
            S.run_sort_endpoint(SimpleNamespace(sort_date=date(2026, 10, 24)), caller=caller, _={}, db=None)
        assert e.value.status_code == 409 and e.value.detail["tbas"] == ["TBA9"]
        assert not any(k.startswith("sort_run") for k in r.store), "nothing queued, no sentinel written"

    def test_commit_sort_checks_the_trucks_packages(self):
        """walker_routes.commit_sort is proprietary and too wide to drive here;
        assert the gate sits after the manifest index and raises 409."""
        src = (BACKEND / "app/routers/walker_routes.py").read_text()
        fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == "commit_sort")
        body = ast.get_source_segment(src, fn)
        assert body.index("manifest_by_tba: dict[str, dict]") < body.index("is_held(manifest_by_tba.get(t)")
        assert "HTTP_409_CONFLICT" in body[body.index("is_held(manifest_by_tba"):][:600]


def test_the_export_escapes_a_formula_in_manifest_text():
    from app.services.free_text import escape_for_spreadsheet
    assert escape_for_spreadsheet('=HYPERLINK("http://x")') == "'=HYPERLINK(\"http://x\")"
    src = (BACKEND / "app/routers/sort.py").read_text()
    block = src[src.index("def download_enriched_manifest"):][:5000]
    assert "escape_for_spreadsheet(v) if isinstance(v, str) else v" in block


def test_no_customer_path_in_the_manifest_flow_calls_geoclient():
    for path, fn in (("app/tasks/enrich_manifest.py", "_enrich_one"),
                     ("app/routers/sort.py", "patch_manifest_package"),
                     ("app/routers/sort.py", "add_freight")):
        src = (BACKEND / path).read_text()
        node = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == fn)
        body = ast.get_source_segment(src, node)
        assert "_geoclient" not in body and "api.nyc.gov" not in body, f"{fn} still reaches GeoClient"

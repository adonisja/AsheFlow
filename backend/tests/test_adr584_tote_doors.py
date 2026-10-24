"""ADR-584 step 3 — a tote address resolves to a PlaceType door; a miss is
refused with the doors on that street until the captain picks one, pins it,
or keeps it without a door. Intake and route lookup use the same resolver.
"""
import uuid
from datetime import date

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.routers import workforce_routes as W
from app.services import door_resolver as DR
from app.services import package_intake as PI

DOOR = DR.Door(borough="1", address="505 W 37 ST", block_key="W_37_St_500",
               lat=40.7567, lng=-73.9982, segment_id="0034567")


def _payload(**kw):
    base = dict(truck_id=uuid.uuid4(), entry_date=date(2026, 10, 24), bag_id="6800",
                raw_address="505 West 37th St")
    return W.ToteAddressIn(**{**base, **kw})


class _S:
    def close(self):
        pass


@pytest.fixture(autouse=True)
def _placetype(monkeypatch):
    monkeypatch.setattr("app.database.PlaceTypeSession", _S)


def test_at_most_one_choice():
    _payload(door={"borough": "1", "address": "505 W 37 ST"})
    _payload(without_door=True)
    with pytest.raises(ValidationError):
        _payload(door={"borough": "1", "address": "505 W 37 ST"}, without_door=True)
    with pytest.raises(ValidationError):
        _payload(pin={"lat": 40.75, "lng": -73.99}, door={"borough": "1", "address": "505 W 37 ST"})


def test_a_miss_is_refused_with_the_doors_on_that_street(monkeypatch):
    monkeypatch.setattr(W, "resolve_address", lambda **k: PI.ResolvedAddress(
        block_key="W_37_St_500", door_status="unresolved",
        near=[{"address": "501 W 37 ST", "borough": "1"}]))
    with pytest.raises(HTTPException) as e:
        W._resolve_tote_door(None, uuid.uuid4(), _payload())
    assert e.value.status_code == 409
    assert e.value.detail["near"][0]["address"] == "501 W 37 ST"


def test_a_hit_is_stored_with_its_door(monkeypatch):
    monkeypatch.setattr(W, "resolve_address", lambda **k: PI.ResolvedAddress(
        lat=1.0, lng=2.0, normalised_address="505 W 37 ST", block_key="W_37_St_500",
        geocoded=True, door_status="resolved"))
    r = W._resolve_tote_door(None, uuid.uuid4(), _payload())
    assert r.normalised_address == "505 W 37 ST" and r.geocoded


def test_a_picked_door_must_exist(monkeypatch):
    monkeypatch.setattr(DR, "door_from_pick", lambda db, b, a: None)
    with pytest.raises(HTTPException) as e:
        W._resolve_tote_door(None, uuid.uuid4(), _payload(door={"borough": "1", "address": "9 NOWHERE ST"}))
    assert e.value.status_code == 422
    monkeypatch.setattr(DR, "door_from_pick", lambda db, b, a: DOOR)
    r = W._resolve_tote_door(None, uuid.uuid4(), _payload(door={"borough": "1", "address": "505 W 37 ST"}))
    assert (r.normalised_address, r.segment_id, r.door_status) == ("505 W 37 ST", "0034567", "resolved")


def test_without_a_door_keeps_the_parser_block_and_no_position(monkeypatch):
    def boom(**k):
        raise AssertionError("looked the address up after the captain chose no door")
    monkeypatch.setattr(W, "resolve_address", boom)
    r = W._resolve_tote_door(None, uuid.uuid4(), _payload(without_door=True))
    assert r.block_key == "W_37_St_500" and r.lat is None and r.normalised_address is None


def test_a_pin_takes_the_nearest_door_or_stands_alone(monkeypatch):
    from app.services import place_geometry
    monkeypatch.setattr(place_geometry, "doors_near", lambda db, lat, lng, **k: [])
    r = W._resolve_tote_door(None, uuid.uuid4(), _payload(pin={"lat": 40.75, "lng": -73.99}))
    assert (r.lat, r.lng, r.door_status) == (40.75, -73.99, "pinned") and r.block_key == "W_37_St_500"


def test_tote_entry_and_intake_never_reach_geoclient():
    import ast, inspect
    for fn in (W._resolve_tote_door, PI.resolve_address):
        src = inspect.getsource(fn)
        assert "_geoclient" not in src and "address_resolver" not in src, fn.__name__

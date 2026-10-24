"""ADR-584 step 3 — a tote address resolves to a PlaceType door; a miss is
refused with the doors on that street until the captain picks one, pins it,
or keeps it without a door. Intake and route lookup use the same resolver.
"""
import uuid
from datetime import date

from tests.services.test_adr291_workforce_adapter import wf_db  # noqa: F401 — real tote tables

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



class TestTheDoorIdentityIsStoredNotItsAttributes:
    """ADR-584 D9 / ADR-580 D5: a tenant table holds the door identity; the
    position, segment and cross streets are joined from PlaceType when sorting."""

    def test_the_tote_row_is_built_with_identity_and_no_placetype_attributes(self):
        import ast, inspect, textwrap
        src = textwrap.dedent(inspect.getsource(W.add_tote_address))
        call = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call)
                    and getattr(n.func, "id", None) == "ToteAddress")
        kw = {k.arg: ast.unparse(k.value) for k in call.keywords}
        assert kw["segment_id"] == "None"
        assert "pinned" in kw["lat"] and "pinned" in kw["lng"], "only a pin's own coordinates"
        assert "resolved.borough" in kw["borough"]

    def test_the_sort_joins_placetype_for_a_door_and_keeps_a_pins_own_position(self, wf_db, monkeypatch):
        """Calls the real build_packages on real tote rows."""
        import uuid as _uuid
        from datetime import date as _date
        from app.models.tote_address import ToteAddress
        from app.services import place_geometry
        from app.services.workforce_sort_adapter import build_packages
        facts = {("1", "505 W 37 ST"): {"lat": 40.7567, "lng": -73.9982, "segment_id": "0034567",
                                         "first_cross_street": "10 AVE", "second_cross_street": "11 AVE"}}
        seen = {}
        monkeypatch.setattr(place_geometry, "doors_by_identity",
                            lambda db, pairs: seen.setdefault("pairs", list(pairs)) and facts)
        cid, tid = _uuid.uuid4(), _uuid.uuid4()
        wf_db.add_all([
            ToteAddress(id=_uuid.uuid4(), company_id=cid, truck_id=tid, entry_date=_date.today(),
                        bag_id="5270", raw_address="505 West 37th St", normalised_address="505 W 37 ST",
                        borough="1", block_key="W_37_St_500", entry_sequence=1),
            ToteAddress(id=_uuid.uuid4(), company_id=cid, truck_id=tid, entry_date=_date.today(),
                        bag_id="5271", raw_address="corner of the plaza", normalised_address=None,
                        block_key="W_37_St_500", lat=40.75, lng=-73.99, entry_sequence=1),
        ])
        wf_db.commit()
        pk = {p.bag_id: p for p in build_packages(wf_db, cid, tid, _date.today()).packages}
        assert seen["pairs"] == [("1", "505 W 37 ST")], "one batch read, door identities only"
        assert (pk["5270"].segment_id, pk["5270"].lat, pk["5270"].first_cross_street) == ("0034567", 40.7567, "10 AVE")
        assert (pk["5271"].lat, pk["5271"].lng, pk["5271"].segment_id) == (40.75, -73.99, None)

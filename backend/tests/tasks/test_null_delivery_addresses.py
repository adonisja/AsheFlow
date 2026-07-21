"""null_expired_delivery_addresses (ADR-219).

Public cleanup task. Verifies the disable guard, the stops-JSONB address scrub
(keep block_key + tba_numbers, drop address), and that the Route ARRAY is cleared.
The bulk .update() calls are exercised via a mock session that records them.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def test_disabled_when_retention_hours_zero():
    from app.tasks import cleanup
    with patch.object(cleanup.settings, "delivery_address_retention_hours", 0):
        out = cleanup.null_expired_delivery_addresses()
    assert out == {"skipped": True}


def test_scrubs_route_array_and_stops_jsonb():
    from app.tasks import cleanup
    from app.models.walker_route import Route

    old_route = SimpleNamespace(
        id="r1",
        normalised_addresses=["433 W 32 ST", "12 Vernon Blvd"],
        stops=[
            {"block_key": "W_32_St_400", "address": "433 W 32 ST", "tba_numbers": ["A1", "A2"]},
            {"block_key": "Vernon_Blvd_1200", "address": "12 Vernon Blvd", "tba_numbers": ["B1"]},
        ],
    )

    db = MagicMock()

    # Route query returns old_route for the .all() (both the object scan and the id scan).
    def _query(model, *rest):
        q = MagicMock(); f = MagicMock(); f.filter.return_value = f
        if model is Route:
            f.all.return_value = [old_route]
        else:
            f.all.return_value = []
        f.update.return_value = 0
        q.filter.return_value = f
        return q
    db.query = _query

    with patch.object(cleanup, "SessionLocal", return_value=db), \
         patch.object(cleanup.settings, "delivery_address_retention_hours", 48):
        out = cleanup.null_expired_delivery_addresses()

    # Route ARRAY cleared; stops JSONB kept block_key + tba_numbers, dropped address.
    assert old_route.normalised_addresses == []
    assert all("address" not in s for s in old_route.stops)
    assert old_route.stops[0]["block_key"] == "W_32_St_400"
    assert old_route.stops[0]["tba_numbers"] == ["A1", "A2"]
    assert out["routes"] == 1

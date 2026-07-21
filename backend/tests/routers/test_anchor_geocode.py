"""_resolve_anchor_location — intersection geocode + code-62 fallback message.

trucks.py is public. GeoClient returns HTTP 200 with geosupportReturnCode 62
("DO NOT INTERSECT") for real-but-unregistered corners; the resolver must give
an actionable message pointing the user to a nearby address, not the generic
"check the names" text.
"""
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.routers.trucks import _resolve_anchor_location


def _fake_intersection_code62(one, two, borough="manhattan", reason_out=None):
    if reason_out is not None:
        reason_out["message"] = f"{two.upper()} & {one.upper()} DO NOT INTERSECT"
        reason_out["return_code"] = "62"
    return None


def _fake_intersection_ok(one, two, borough="manhattan", reason_out=None):
    return (40.7528, -73.9967)


def test_code62_gives_address_guidance():
    with patch("app.tasks.enrich_manifest._geoclient_intersection", side_effect=_fake_intersection_code62), \
         patch("app.tasks.enrich_manifest._geoclient_normalise"):
        with pytest.raises(HTTPException) as exc:
            _resolve_anchor_location("W 32 St & 9 Ave", "manhattan")
    assert exc.value.status_code == 422
    detail = exc.value.detail.lower()
    assert "registered corner" in detail or "isn't a registered" in detail
    assert "address" in detail          # guides the user to enter an address instead


def test_successful_intersection_returns_coords():
    with patch("app.tasks.enrich_manifest._geoclient_intersection", side_effect=_fake_intersection_ok):
        canonical, lat, lng = _resolve_anchor_location("W 32 St & 9 Ave", "manhattan")
    assert (lat, lng) == (40.7528, -73.9967)
    assert canonical == "W 32 ST & 9 AVE"

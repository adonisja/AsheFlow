"""Resolve a BTR sheet's anchor point to a truck — ADR-410.

Amazon prints a static per-truck anchor on every BTR sheet. The BTR label itself
rotates between trucks, so the anchor is the only stable identifier on the sheet.

This module is a pure lookup: it reads, never writes, and it only ever SUGGESTS.
`/btr-sheets/confirm` still takes an explicit truck_id (ADR-410 D5) — removing the
lookup is the point, not removing the human.
"""
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.truck import Truck

# The printed values carry 5 decimal places (~1 m). Both sides are rounded to
# this before comparison: the columns are double precision, and raw float
# equality is not something an identifier should rest on (ADR-410 D3).
ANCHOR_DP = 5


def anchor_key(lat: Optional[float], lng: Optional[float]) -> Optional[tuple[float, float]]:
    """The comparable form of an anchor, or None when either half is missing."""
    if lat is None or lng is None:
        return None
    return (round(float(lat), ANCHOR_DP), round(float(lng), ANCHOR_DP))


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in METRES.

    Local copy for the same reason anchor_points.py keeps one: route_sort's
    _haversine_km is proprietary and this module must import in public CI.

    Used ONLY to describe a drift in the audit detail (ADR-410 D7) — never to
    decide a match, which is exact on the rounded key (D3).
    """
    from math import radians, cos, sin, sqrt, atan2
    R = 6_371_000.0
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))


def resolve_truck_by_anchor(
    db: Session,
    company_id: UUID,
    lat: Optional[float],
    lng: Optional[float],
) -> Optional[Truck]:
    """The company's truck registered at this anchor, or None.

    Exact on the rounded key — never nearest-neighbour. The verified NYCD anchors
    put two trucks 34 m apart, so any distance tolerance wide enough to absorb
    noise is also wide enough to return the wrong truck (ADR-410 D3).

    Scoped to company_id: an anchor is unique within a company, not globally, and
    two DSPs at the same station can legitimately share one.
    """
    key = anchor_key(lat, lng)
    if key is None:
        return None

    candidates = (
        db.query(Truck)
        .filter(
            Truck.company_id == company_id,
            Truck.is_active.is_(True),
            Truck.amazon_anchor_lat.isnot(None),
            Truck.amazon_anchor_lng.isnot(None),
        )
        .all()
    )
    for truck in candidates:
        if anchor_key(truck.amazon_anchor_lat, truck.amazon_anchor_lng) == key:
            return truck
    return None

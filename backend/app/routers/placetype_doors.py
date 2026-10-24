"""PlaceType doors near a point, for a tenant picking where a package goes (ADR-584 D4).

A tenant READ of PlaceType (ADR-580 D6): public city doors (AddressPoint), never a
customer's address, bounded on every axis so it can't dump an area — a radius of at
most 150 m, at most 10 doors, New York coordinates only.

    GET /placetype/doors/nearby?lat=&lng=[&street=]
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from app.api.deps import RoleChecker
from app.api.ratelimit import limiter
from app.database import get_db

router = APIRouter(prefix="/placetype/doors", tags=["placetype"])

# Whoever resolves a door PlaceType couldn't place: dispatch on Sort, a captain
# entering tote addresses, a walker with a found package (ADR-584 D7).
_allow_pick = RoleChecker(["walker", "trainer", "trainee", "driver", "dispatch", "management",
                           "admin", "captain", "field_supervisor"])


class NearbyDoor(BaseModel):
    address: str
    borough: str
    distance_m: float
    lat: float
    lng: float


class NearbyDoorsOut(BaseModel):
    doors: List[NearbyDoor]


@router.get("/nearby", response_model=NearbyDoorsOut)
@limiter.limit("60/minute")
def nearby_doors(
    request: Request,
    lat: float = Query(..., ge=40.47, le=40.93),
    lng: float = Query(..., ge=-74.27, le=-73.68),
    street: Optional[str] = Query(None, min_length=2, max_length=60),
    db=Depends(get_db),
    _: dict = Depends(_allow_pick),
):
    from app.services.place_geometry import doors_near
    return NearbyDoorsOut(doors=[NearbyDoor(**d) for d in doors_near(db, lat, lng, street=street)])

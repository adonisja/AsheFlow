"""Company operating zone — the polygon a company delivers inside (ADR-312).

Moved out of `sort.py`, which `main.py` registers `_full_mode`. Nothing here is
package-coupled: the endpoints convert a description of an area (a bounding box,
two pairs of streets, a list of intersections, a list of corners) into a GeoJSON
polygon and upsert it. They were gated only because of where the file sat, so a
workforce tenant could not define or read its own operating area.

Defining and reading the area is company configuration. Using it to bound a day's
work is sorting, and that stays in `run_sort.py` / `package_intake.py`, which
query `CompanyZone` directly.

`_geoclient_intersection` is imported from `app.tasks.enrich_manifest` rather than
moved: it is public, package-free, and has full-mode callers. Its home is worth
revisiting (ADR-312 D2, Open) but not in this change.
"""
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.api.deps import RoleChecker, get_caller_employee
from app.models.company import CompanyZone
from app.models.employee import Employee
from app.services.audit import write_audit

router = APIRouter(prefix="/company-zones", tags=["company-zones"])

# Unchanged from sort.py (ADR-312 D5): defining the zone stays admin-only, and
# READING it stays open to anyone who may run or view a sort. Tightening either
# while moving the file would be a silent permissions change.
allow_admin = RoleChecker(["admin"])
allow_sort = RoleChecker(["dispatch", "management", "admin"])


class CornerPoint(BaseModel):
    lat: float
    lng: float


class OperatingZoneOut(BaseModel):
    id: UUID
    name: str
    sw_lat: float
    sw_lng: float
    ne_lat: float
    ne_lng: float
    corners: list[CornerPoint] = []

    model_config = ConfigDict(from_attributes=True)


class OperatingZoneIn(BaseModel):
    sw_lat: float
    sw_lng: float
    ne_lat: float
    ne_lng: float
    name: str = "Operating Zone"


class OperatingZoneFromStreetsIn(BaseModel):
    from_street: str = Field(..., max_length=100, description="Starting cross-street, e.g. 'W 23 St'")
    to_street:   str = Field(..., max_length=100, description="Ending cross-street, e.g. 'W 57 St'")
    from_avenue: str = Field(..., max_length=100, description="Starting avenue, e.g. '6 Ave'")
    to_avenue:   str = Field(..., max_length=100, description="Ending avenue, e.g. '12 Ave'")
    borough:     str = Field("manhattan", max_length=30)
    name:        str = Field("Operating Zone", max_length=100)


class IntersectionIn(BaseModel):
    street: str = Field(..., max_length=100)
    avenue: str = Field(..., max_length=100)


class OperatingZoneFromIntersectionsIn(BaseModel):
    intersections: list[IntersectionIn] = Field(..., min_length=3, max_length=50)
    borough: str = Field("manhattan", max_length=30)
    name:    str = Field("Operating Zone", max_length=100)


class OperatingZoneFromCornersIn(BaseModel):
    corners: list[CornerPoint] = Field(..., min_length=3, max_length=50)
    name:    str = Field("Operating Zone", max_length=100)


def _corners_to_geojson(corners: list[tuple[float, float]]) -> dict:
    """Convert an ordered list of (lat, lng) corner points to a closed GeoJSON Polygon ring."""
    ring = [[lng, lat] for lat, lng in corners]
    ring.append(ring[0])   # close the ring
    return {"type": "Polygon", "coordinates": [ring]}


def _bbox_to_geojson(sw_lat: float, sw_lng: float, ne_lat: float, ne_lng: float) -> dict:
    """Convert SW/NE corners to a closed GeoJSON Polygon rectangle (AABB — 4 axis-aligned corners)."""
    return _corners_to_geojson([
        (sw_lat, sw_lng),
        (sw_lat, ne_lng),
        (ne_lat, ne_lng),
        (ne_lat, sw_lng),
    ])


def _geojson_to_bbox(bounds: dict) -> tuple[float, float, float, float] | None:
    """Extract SW/NE AABB corners from a GeoJSON Polygon (used by sort algorithm for fast containment check)."""
    try:
        coords = bounds["coordinates"][0]
        lngs = [c[0] for c in coords]
        lats = [c[1] for c in coords]
        return min(lats), min(lngs), max(lats), max(lngs)
    except (KeyError, IndexError, TypeError):
        return None


def _geojson_to_corners(bounds: dict) -> list[CornerPoint]:
    """Return the actual polygon vertices (excluding the closing duplicate) as CornerPoint list."""
    try:
        coords = bounds["coordinates"][0]
        pts = coords[:-1] if len(coords) > 1 and coords[0] == coords[-1] else coords
        return [CornerPoint(lat=c[1], lng=c[0]) for c in pts]
    except (KeyError, IndexError, TypeError):
        return []


@router.get("", response_model=Optional[OperatingZoneOut])
def get_company_zone(
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_sort),
    db: Session = Depends(get_db),
):
    """Return the company's operating zone bounding box, or null if not configured."""
    zone = (
        db.query(CompanyZone)
        .filter(
            CompanyZone.company_id == caller.company_id,
            CompanyZone.parent_zone_id.is_(None),
            CompanyZone.is_active.is_(True),
        )
        .order_by(CompanyZone.created_at.desc())
        .first()
    )
    if zone is None or not zone.bounds:
        return None
    bbox = _geojson_to_bbox(zone.bounds)
    if bbox is None:
        return None
    sw_lat, sw_lng, ne_lat, ne_lng = bbox
    return OperatingZoneOut(
        id=zone.id,
        name=zone.name,
        sw_lat=sw_lat,
        sw_lng=sw_lng,
        ne_lat=ne_lat,
        ne_lng=ne_lng,
        corners=_geojson_to_corners(zone.bounds),
    )


@router.post("", response_model=OperatingZoneOut, status_code=status.HTTP_200_OK)
def upsert_company_zone(
    body: OperatingZoneIn,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_admin),
    db: Session = Depends(get_db),
):
    """Create or replace the company's operating zone from a SW/NE bounding box."""
    from datetime import datetime, timezone
    from app.services.audit import write_audit

    if body.sw_lat >= body.ne_lat:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="SW latitude must be less than NE latitude.")
    if body.sw_lng >= body.ne_lng:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="SW longitude must be less than NE longitude.")

    db.query(CompanyZone).filter(
        CompanyZone.company_id == caller.company_id,
        CompanyZone.parent_zone_id.is_(None),
        CompanyZone.is_active.is_(True),
    # ADR-312 D6 — DELETE the superseded revision rather than deactivating it.
    # Deactivating grew the table by one dead row per edit forever: every reader
    # in the codebase filters is_active=True, so an inactive row is never read by
    # anything. The edit history it might have preserved is already recorded, and
    # better, by the write_audit below — which carries the actor and timestamp
    # that CompanyZone does not.
    ).delete(synchronize_session="fetch")

    bounds = _bbox_to_geojson(body.sw_lat, body.sw_lng, body.ne_lat, body.ne_lng)
    import uuid as _uuid
    zone = CompanyZone(
        id=_uuid.uuid4(),
        company_id=caller.company_id,
        parent_zone_id=None,
        name=body.name,
        bounds=bounds,
        is_active=True,
        created_at=datetime.now(timezone.utc),
    )
    db.add(zone)
    db.flush()
    write_audit(
        db,
        action_type="company_zone.upserted",
        target_table="company_zones",
        target_id=str(zone.id),
        actor_id=str(caller.id),
        company_id=str(caller.company_id),
        after={"sw_lat": body.sw_lat, "sw_lng": body.sw_lng, "ne_lat": body.ne_lat, "ne_lng": body.ne_lng},
    )
    db.commit()
    db.refresh(zone)

    return OperatingZoneOut(
        id=zone.id,
        name=zone.name,
        sw_lat=body.sw_lat,
        sw_lng=body.sw_lng,
        ne_lat=body.ne_lat,
        ne_lng=body.ne_lng,
        corners=_geojson_to_corners(bounds),
    )


@router.post("/from-streets", response_model=OperatingZoneOut, status_code=status.HTTP_200_OK)
def upsert_company_zone_from_streets(
    body: OperatingZoneFromStreetsIn,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_admin),
    db: Session = Depends(get_db),
):
    """Create or replace the company's operating zone from street/avenue range inputs."""
    from app.tasks.enrich_manifest import _geoclient_intersection
    from datetime import datetime, timezone
    from app.services.audit import write_audit
    import uuid as _uuid

    if not settings.geoclient_app_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GeoClient API key is not configured on this server. Use the Advanced section to enter coordinates directly.",
        )

    from_st = body.from_street.strip()
    to_st   = body.to_street.strip()
    from_av = body.from_avenue.strip()
    to_av   = body.to_avenue.strip()

    corner_pairs = [
        (from_st, from_av),
        (from_st, to_av),
        (to_st,   from_av),
        (to_st,   to_av),
    ]
    # corner_pairs order: (from_st/from_av=SW, from_st/to_av=SE, to_st/from_av=NW, to_st/to_av=NE)
    geocoded: list[tuple[float, float]] = []
    for street, avenue in corner_pairs:
        result = _geoclient_intersection(street, avenue, borough=body.borough)
        if result is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Could not geocode '{street} & {avenue}' in {body.borough}. "
                    f"Check the spelling — use formats like 'W 23 ST', '6 AVE', 'BROADWAY'."
                ),
            )
        geocoded.append(result)   # (lat, lng)

    # Build a proper quadrilateral from the 4 geocoded intersection points in geographic
    # order (SW → SE → NE → NW) so the polygon hugs the actual delivery area without
    # bleeding into water or adjacent territory the way an axis-aligned rectangle would.
    sw, se, nw, ne_pt = geocoded[0], geocoded[1], geocoded[2], geocoded[3]
    quad_corners = [sw, se, ne_pt, nw]

    lats = [p[0] for p in geocoded]
    lngs = [p[1] for p in geocoded]
    sw_lat, sw_lng = min(lats), min(lngs)
    ne_lat, ne_lng = max(lats), max(lngs)

    if sw_lat >= ne_lat or sw_lng >= ne_lng:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Derived bounding box is degenerate — check that from/to streets and avenues differ.",
        )

    db.query(CompanyZone).filter(
        CompanyZone.company_id == caller.company_id,
        CompanyZone.parent_zone_id.is_(None),
        CompanyZone.is_active.is_(True),
    # ADR-312 D6 — DELETE the superseded revision rather than deactivating it.
    # Deactivating grew the table by one dead row per edit forever: every reader
    # in the codebase filters is_active=True, so an inactive row is never read by
    # anything. The edit history it might have preserved is already recorded, and
    # better, by the write_audit below — which carries the actor and timestamp
    # that CompanyZone does not.
    ).delete(synchronize_session="fetch")

    # Store the exact quadrilateral — not the axis-aligned rectangle — so the frontend
    # can draw a polygon that matches the actual street grid boundaries.
    bounds = _corners_to_geojson(quad_corners)
    zone = CompanyZone(
        id=_uuid.uuid4(),
        company_id=caller.company_id,
        parent_zone_id=None,
        name=body.name,
        bounds=bounds,
        is_active=True,
        created_at=datetime.now(timezone.utc),
    )
    db.add(zone)
    db.flush()
    write_audit(
        db,
        action_type="company_zone.upserted",
        target_table="company_zones",
        target_id=str(zone.id),
        actor_id=str(caller.id),
        company_id=str(caller.company_id),
        after={
            "from_street": from_st, "to_street": to_st,
            "from_avenue": from_av, "to_avenue": to_av,
            "sw_lat": sw_lat, "sw_lng": sw_lng,
            "ne_lat": ne_lat, "ne_lng": ne_lng,
        },
    )
    db.commit()
    db.refresh(zone)

    return OperatingZoneOut(
        id=zone.id,
        name=zone.name,
        sw_lat=sw_lat,
        sw_lng=sw_lng,
        ne_lat=ne_lat,
        ne_lng=ne_lng,
        corners=_geojson_to_corners(bounds),
    )


@router.post("/from-intersections", response_model=OperatingZoneOut, status_code=status.HTTP_200_OK)
def upsert_company_zone_from_intersections(
    body: OperatingZoneFromIntersectionsIn,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_admin),
    db: Session = Depends(get_db),
):
    """Create or replace the company zone from an ordered list of street+avenue intersections.

    Each intersection is geocoded in order; the resulting lat/lng points form the polygon
    vertices. Minimum 3 intersections required to define a valid polygon.
    """
    from app.tasks.enrich_manifest import _geoclient_intersection
    from datetime import datetime, timezone
    from app.services.audit import write_audit
    import uuid as _uuid

    if not settings.geoclient_app_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GeoClient API key is not configured. Use draw mode or raw coordinates instead.",
        )

    geocoded: list[tuple[float, float]] = []
    for ix in body.intersections:
        result = _geoclient_intersection(ix.street.strip(), ix.avenue.strip(), borough=body.borough)
        if result is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Could not geocode '{ix.street} & {ix.avenue}' in {body.borough}. "
                    f"Use formats like 'W 23 ST', '6 AVE', 'BROADWAY'."
                ),
            )
        geocoded.append(result)

    lats = [p[0] for p in geocoded]
    lngs = [p[1] for p in geocoded]
    sw_lat, sw_lng = min(lats), min(lngs)
    ne_lat, ne_lng = max(lats), max(lngs)

    bounds = _corners_to_geojson(geocoded)

    db.query(CompanyZone).filter(
        CompanyZone.company_id == caller.company_id,
        CompanyZone.parent_zone_id.is_(None),
        CompanyZone.is_active.is_(True),
    # ADR-312 D6 — DELETE the superseded revision rather than deactivating it.
    # Deactivating grew the table by one dead row per edit forever: every reader
    # in the codebase filters is_active=True, so an inactive row is never read by
    # anything. The edit history it might have preserved is already recorded, and
    # better, by the write_audit below — which carries the actor and timestamp
    # that CompanyZone does not.
    ).delete(synchronize_session="fetch")

    zone = CompanyZone(
        id=_uuid.uuid4(),
        company_id=caller.company_id,
        parent_zone_id=None,
        name=body.name,
        bounds=bounds,
        is_active=True,
        created_at=datetime.now(timezone.utc),
    )
    db.add(zone)
    db.flush()
    write_audit(
        db,
        action_type="company_zone.upserted",
        target_table="company_zones",
        target_id=str(zone.id),
        actor_id=str(caller.id),
        company_id=str(caller.company_id),
        after={"method": "intersections", "count": len(geocoded), "borough": body.borough},
    )
    db.commit()
    db.refresh(zone)

    return OperatingZoneOut(
        id=zone.id,
        name=zone.name,
        sw_lat=sw_lat,
        sw_lng=sw_lng,
        ne_lat=ne_lat,
        ne_lng=ne_lng,
        corners=_geojson_to_corners(bounds),
    )


@router.post("/from-corners", response_model=OperatingZoneOut, status_code=status.HTTP_200_OK)
def upsert_company_zone_from_corners(
    body: OperatingZoneFromCornersIn,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_admin),
    db: Session = Depends(get_db),
):
    """Create or replace the company zone from raw lat/lng corner points (click-to-draw output)."""
    from datetime import datetime, timezone
    from app.services.audit import write_audit
    import uuid as _uuid

    lats = [c.lat for c in body.corners]
    lngs = [c.lng for c in body.corners]
    sw_lat, sw_lng = min(lats), min(lngs)
    ne_lat, ne_lng = max(lats), max(lngs)

    bounds = _corners_to_geojson([(c.lat, c.lng) for c in body.corners])

    db.query(CompanyZone).filter(
        CompanyZone.company_id == caller.company_id,
        CompanyZone.parent_zone_id.is_(None),
        CompanyZone.is_active.is_(True),
    # ADR-312 D6 — DELETE the superseded revision rather than deactivating it.
    # Deactivating grew the table by one dead row per edit forever: every reader
    # in the codebase filters is_active=True, so an inactive row is never read by
    # anything. The edit history it might have preserved is already recorded, and
    # better, by the write_audit below — which carries the actor and timestamp
    # that CompanyZone does not.
    ).delete(synchronize_session="fetch")

    zone = CompanyZone(
        id=_uuid.uuid4(),
        company_id=caller.company_id,
        parent_zone_id=None,
        name=body.name,
        bounds=bounds,
        is_active=True,
        created_at=datetime.now(timezone.utc),
    )
    db.add(zone)
    db.flush()
    write_audit(
        db,
        action_type="company_zone.upserted",
        target_table="company_zones",
        target_id=str(zone.id),
        actor_id=str(caller.id),
        company_id=str(caller.company_id),
        after={"method": "draw", "vertex_count": len(body.corners)},
    )
    db.commit()
    db.refresh(zone)

    return OperatingZoneOut(
        id=zone.id,
        name=zone.name,
        sw_lat=sw_lat,
        sw_lng=sw_lng,
        ne_lat=ne_lat,
        ne_lng=ne_lng,
        corners=_geojson_to_corners(bounds),
    )




# ── Address inventory bootstrap (ADR-303 D1a) ────────────────────────────────

class ZoneBootstrapOut(BaseModel):
    """What the bootstrap did. Counts, never addresses (Dimension 7)."""
    zone_id: UUID
    enumerated: int
    created: int
    skipped_existing: int
    skipped_unparseable: int
    source: str = "nyc_addresspoint"


@router.post("/bootstrap", response_model=ZoneBootstrapOut, status_code=status.HTTP_200_OK)
def bootstrap_zone_inventory(
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_admin),
    db: Session = Depends(get_db),
):
    """Enumerate the addresses inside the company's active zone into BuildingProfile.

    ADR-303. The segment map self-seeds from packages, which workforce mode does
    not have, so nothing ever populates its address inventory. This enumerates
    from NYC AddressPoint, filtered server-side by the zone polygon.

    Explicit rather than only hooked to zone definition (D1a): a zone defined
    months ago will never fire a create event, and a background job with no way
    to re-trigger it is a job that fails once and stays failed.

    Synchronous on purpose for now — measured at 4,786 addresses in 3.6s for a
    real Midtown zone, which is inside a request budget. It makes NO GeoClient
    calls (D9); segment resolution is deferred until that cost is measured.
    """
    from app.services.address_inventory import (
        AddressSourceUnavailable, enumerate_zone_addresses, persist_zone_inventory,
    )

    zone = (
        db.query(CompanyZone)
        .filter(
            CompanyZone.company_id == caller.company_id,
            CompanyZone.parent_zone_id.is_(None),
            CompanyZone.is_active.is_(True),
        )
        .first()
    )
    if zone is None or not zone.bounds:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No operating zone is configured. Define one before bootstrapping.",
        )

    try:
        addresses = list(enumerate_zone_addresses(zone.bounds))
    except AddressSourceUnavailable:
        # Best-effort, matching segment_map's stance: the upstream being down
        # must not read as "this zone has no addresses". No str(exc) — the URL
        # carries the polygon and the header carries the token (Dimension 6).
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The address source is unavailable. Try again later.",
        )

    summary = persist_zone_inventory(db, caller.company_id, addresses)
    db.flush()
    write_audit(
        db=db,
        company_id=str(caller.company_id),
        actor_id=str(caller.id),
        action_type="company_zone.inventory_bootstrapped",
        target_table="building_profiles",
        target_id=str(zone.id),
        # Counts only — an address list in the audit log would put PII there
        # permanently (Dimension 7).
        detail={"enumerated": len(addresses), **summary},
    )
    db.commit()

    return ZoneBootstrapOut(zone_id=zone.id, enumerated=len(addresses), **summary)

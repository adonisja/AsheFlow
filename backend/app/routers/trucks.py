import os
import re
from datetime import datetime, timezone
from uuid import UUID

import aiohttp
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.api.deps import RoleChecker, get_caller_employee, Pagination
from app.models.employee import Employee
from app.models.truck import Truck
from app.schemas.truck import TruckCreate, TruckUpdate, TruckResponse, TruckAnchorPatch, TruckAnchor2Patch
from app.services.audit import write_audit

# ── Anchor input parsing (ADR-173) ────────────────────────────────────────────
# Anchors accept two forms in the same field:
#   address:      "365 W 28 ST"            → GeoClient /address.json (building point)
#   intersection: "W 28 ST & 9 AVE"        → GeoClient /intersection.json (corner node)
#                 "28th St and 9th Ave"
# Intersections are the preferred territorial form: no house-number typos, no
# building-side offset, and the bisector between two grid anchors falls exactly
# between their streets ("Atlas south of 28½ St").

_INTERSECTION_SEP = re.compile(r"\s*&\s*|\s+and\s+", re.IGNORECASE)


def _parse_intersection_input(address: str) -> tuple[str, str] | None:
    """Return (cross_street_one, cross_street_two) for intersection-form input,
    or None when the input is a plain street address."""
    parts = _INTERSECTION_SEP.split(address, maxsplit=1)
    if len(parts) == 2 and parts[0].strip() and parts[1].strip():
        return parts[0].strip(), parts[1].strip()
    return None


def _resolve_anchor_location(address: str, borough: str) -> tuple[str, float, float]:
    """Geocode anchor input (address or intersection) → (canonical, lat, lng).

    Raises HTTPException(422) with a form-specific message when GeoClient
    cannot resolve the input.
    """
    from app.tasks.enrich_manifest import _geoclient_normalise, _geoclient_intersection

    crossing = _parse_intersection_input(address)
    if crossing is not None:
        one, two = crossing
        reason: dict = {}
        result = _geoclient_intersection(one, two, borough=borough, reason_out=reason)
        if result is None:
            # GeoClient's Geosupport return code 62 = the two streets don't share a
            # node in the city street file (common for real corners near irregular
            # grid, e.g. by Penn Station / rail yards). Name-form doesn't help — the
            # fix is to enter a nearby street address instead, which geocodes fine.
            code = reason.get("return_code")
            if code == "62":
                detail = (
                    f"'{one} & {two}' isn't a registered corner in the city street file, "
                    "so it can't be placed by intersection — even though the streets meet. "
                    "Enter a nearby street address instead (e.g. a building number on "
                    f"{two} near {one})."
                )
            else:
                detail = (
                    f"Intersection '{one} & {two}' could not be geocoded in {borough}. "
                    "Check both street names and the borough, or enter a nearby street address instead."
                )
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)
        lat, lng = result
        return f"{one.upper()} & {two.upper()}", lat, lng

    geo = _geoclient_normalise(address, borough=borough)
    if geo is None or geo.lat is None or geo.lng is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Address could not be geocoded. Check the address and borough and try again.",
        )
    return geo.normalised_address or address, geo.lat, geo.lng


def _assert_anchor_not_duplicate(
    db: Session, company_id, truck_id, lat: float, lng: float, own_other_anchor: tuple | None = None,
) -> None:
    """Reject an anchor that lands on another anchor's exact spot.

    Two trucks on the same anchor make the territory split degenerate — the
    solver still balances tote counts but divides the shared area arbitrarily.
    Checked within ~10m so identical intersections collide regardless of
    floating-point noise. own_other_anchor guards a truck's own second anchor
    against its first (and vice versa).
    """
    _EPS = 1e-4  # ≈ 10m
    if own_other_anchor is not None:
        o_lat, o_lng = own_other_anchor
        if o_lat is not None and abs(o_lat - lat) < _EPS and abs(o_lng - lng) < _EPS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="This truck's other anchor is already at that location — the two anchors must differ.",
            )
    others = (
        db.query(Truck)
        .filter(Truck.company_id == company_id, Truck.id != truck_id, Truck.is_active.is_(True))
        .all()
    )
    for t in others:
        for a_lat, a_lng, label in (
            (t.initial_anchor_lat, t.initial_anchor_lng, t.initial_anchor_address),
            (t.initial_anchor2_lat, t.initial_anchor2_lng, t.initial_anchor2_address),
        ):
            if a_lat is not None and abs(a_lat - lat) < _EPS and abs(a_lng - lng) < _EPS:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        f"Truck '{t.name}' already has an anchor at that location ({label}). "
                        "Two trucks on the same anchor split their shared territory arbitrarily — "
                        "offset one of them by at least a block."
                    ),
                )

router = APIRouter(prefix="/trucks", tags=["trucks"])

allow_any_auth = RoleChecker(["driver", "walker", "trainer", "trainee", "dispatch", "management", "admin"])
# ADR-363 — the bot lists trucks to build its dispatch embeds. A separate
# gate rather than widening allow_any_auth, which guards other endpoints.
allow_any_auth_bot = RoleChecker(
    ["driver", "walker", "trainer", "trainee", "dispatch", "management", "admin"],
    machine_scopes=["asheflow.bot/dispatch.read"],
)
allow_write    = RoleChecker(["management", "admin"])


@router.post("/", response_model=TruckResponse, status_code=status.HTTP_201_CREATED)
def create_truck(
    truck: TruckCreate,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_write),
    db: Session = Depends(get_db),
):
    db_truck = Truck(company_id=caller.company_id, **truck.model_dump())
    db.add(db_truck)
    db.flush()
    write_audit(
        db,
        action_type="truck.created",
        target_table="trucks",
        target_id=str(db_truck.id),
        actor_id=str(caller.id),
        company_id=str(caller.company_id),
        after={"name": db_truck.name, "is_hub": db_truck.is_hub,
               "is_active": db_truck.is_active},
    )
    db.commit()
    db.refresh(db_truck)
    return db_truck


@router.get("/", response_model=list[TruckResponse])
def get_trucks(
    pg: Pagination = Depends(),
    include_inactive: bool = Query(default=False),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_any_auth_bot),
    db: Session = Depends(get_db),
):
    """Return trucks scoped to the caller's company. Active-only by default."""
    if include_inactive:
        groups = _.get("cognito_groups", [])
        if not any(g in groups for g in ("management", "admin")):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
        q = db.query(Truck).filter(Truck.company_id == caller.company_id)
    else:
        q = db.query(Truck).filter(Truck.company_id == caller.company_id, Truck.is_active == True)
    return pg.apply(q).all()


@router.get("/{truck_id}", response_model=TruckResponse)
def get_truck(
    truck_id: UUID,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_any_auth),
    db: Session = Depends(get_db),
):
    truck = db.query(Truck).filter(Truck.id == truck_id, Truck.company_id == caller.company_id).first()
    if not truck:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Truck not found")
    return truck


@router.put("/{truck_id}", response_model=TruckResponse)
def update_truck(
    truck_id: UUID,
    truck: TruckUpdate,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_write),
    db: Session = Depends(get_db),
):
    db_truck = db.query(Truck).filter(Truck.id == truck_id, Truck.company_id == caller.company_id).first()
    if not db_truck:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Truck not found")

    changed = truck.model_dump(exclude_unset=True)
    before = {k: getattr(db_truck, k, None) for k in changed}
    for key, value in changed.items():
        setattr(db_truck, key, value)

    write_audit(
        db,
        action_type="truck.updated",
        target_table="trucks",
        target_id=str(db_truck.id),
        actor_id=str(caller.id),
        company_id=str(caller.company_id),
        before=before,
        after=changed,
    )
    db.commit()
    db.refresh(db_truck)
    return db_truck


@router.put("/{truck_id}/deactivate", response_model=TruckResponse)
async def deactivate_truck(
    truck_id: UUID,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_write),
    db: Session = Depends(get_db),
):
    """Deactivate a truck and notify the bot to strip crew channel permissions."""
    db_truck = db.query(Truck).filter(Truck.id == truck_id, Truck.company_id == caller.company_id).first()
    if not db_truck:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Truck not found")

    channel_id = db_truck.discord_channel_id
    db_truck.is_active = False
    db_truck.discord_channel_id = None
    write_audit(
        db,
        action_type="truck.deactivated",
        target_table="trucks",
        target_id=str(db_truck.id),
        actor_id=str(caller.id),
        company_id=str(caller.company_id),
        before={"is_active": True},
        after={"is_active": False},
    )
    db.commit()
    db.refresh(db_truck)

    if channel_id:
        bot_url = os.environ.get("BOT_INTERNAL_URL", "http://bot:8001")
        secret  = os.environ.get("INTERNAL_SECRET", "")
        try:
            async with aiohttp.ClientSession() as session:
                await session.post(
                    f"{bot_url}/internal/lockdown-channel",
                    json={"channel_id": channel_id, "company_id": str(caller.company_id)},
                    headers={"X-Internal-Secret": secret},
                    timeout=aiohttp.ClientTimeout(total=5),
                )
        except Exception:
            pass

    return db_truck


@router.put("/{truck_id}/reactivate", response_model=TruckResponse)
def reactivate_truck(
    truck_id: UUID,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_write),
    db: Session = Depends(get_db),
):
    db_truck = db.query(Truck).filter(Truck.id == truck_id, Truck.company_id == caller.company_id).first()
    if not db_truck:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Truck not found")
    db_truck.is_active = True
    # deactivate_truck and delete_truck already audit; reactivate is their exact
    # inverse and did not, so a truck could be taken out of service with a record
    # and put back without one (ADR-274 D14).
    write_audit(
        db,
        action_type="truck.reactivated",
        target_table="trucks",
        target_id=str(db_truck.id),
        actor_id=str(caller.id),
        company_id=str(caller.company_id),
        before={"is_active": False},
        after={"is_active": True, "name": db_truck.name},
    )
    db.commit()
    db.refresh(db_truck)
    return db_truck


@router.patch("/{truck_id}/anchor", response_model=TruckResponse)
def set_truck_anchor(
    truck_id: UUID,
    body: TruckAnchorPatch,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_write),
    db: Session = Depends(get_db),
):
    """Set or clear a truck's initial anchor point.

    Accepts a street address ("365 W 28 ST") or an intersection
    ("W 28 ST & 9 AVE" / "28th St and 9th Ave") plus borough; GeoClient
    resolves either form to lat/lng — users never enter raw coordinates.
    Pass address=null to clear the anchor entirely.
    """
    from app.models.company import CompanyConfig
    from app.core.config import settings

    db_truck = db.query(Truck).filter(Truck.id == truck_id, Truck.company_id == caller.company_id).first()
    if not db_truck:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Truck not found.")

    if body.address is None:
        # Clear the anchor
        db_truck.initial_anchor_address         = None
        db_truck.initial_anchor_display_address = None
        db_truck.initial_anchor_lat             = None
        db_truck.initial_anchor_lng             = None
        db_truck.initial_anchor_set_by          = None
        db_truck.initial_anchor_set_at          = None
    else:
        address = body.address.strip()
        if not address:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Address cannot be blank.")

        if not settings.geoclient_app_key:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="GeoClient API key is not configured on this server. Contact your admin.",
            )

        # Resolve borough: body override → company config → default manhattan
        borough = body.borough
        if not borough:
            cfg = db.query(CompanyConfig).filter(CompanyConfig.company_id == caller.company_id).first()
            borough = (cfg.geoclient_borough if cfg and cfg.geoclient_borough else None) or "manhattan"

        # Address or intersection form — see _resolve_anchor_location.
        canonical, lat, lng = _resolve_anchor_location(address, borough)
        _assert_anchor_not_duplicate(
            db, caller.company_id, db_truck.id, lat, lng,
            own_other_anchor=(db_truck.initial_anchor2_lat, db_truck.initial_anchor2_lng),
        )

        # Store the canonical form (normalised address or "STREET & AVENUE") —
        # reliable for re-geocoding and audit. Keep raw user input for display.
        db_truck.initial_anchor_address         = canonical
        db_truck.initial_anchor_display_address = address
        db_truck.initial_anchor_lat             = lat
        db_truck.initial_anchor_lng             = lng
        db_truck.initial_anchor_set_by          = caller.id
        db_truck.initial_anchor_set_at          = datetime.now(timezone.utc)

    write_audit(
        db,
        action_type="truck.anchor_updated",
        target_table="trucks",
        target_id=str(db_truck.id),
        actor_id=str(caller.id),
        company_id=str(caller.company_id),
        after={"address": db_truck.initial_anchor_address},
    )
    db.commit()
    db.refresh(db_truck)
    return db_truck


@router.patch("/{truck_id}/anchor2", response_model=TruckResponse)
def set_truck_anchor2(
    truck_id: UUID,
    body: TruckAnchor2Patch,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_write),
    db: Session = Depends(get_db),
):
    """Set or clear a truck's optional secondary anchor point.

    When set, the truck can receive a second territory zone around this point
    when tote geography supports the split (ADR-169). Pass address=null to clear.
    """
    from app.models.company import CompanyConfig
    from app.core.config import settings

    db_truck = db.query(Truck).filter(Truck.id == truck_id, Truck.company_id == caller.company_id).first()
    if not db_truck:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Truck not found.")

    if body.address is None:
        db_truck.initial_anchor2_address         = None
        db_truck.initial_anchor2_display_address = None
        db_truck.initial_anchor2_lat             = None
        db_truck.initial_anchor2_lng             = None
        db_truck.initial_anchor2_set_by          = None
        db_truck.initial_anchor2_set_at          = None
    else:
        address = body.address.strip()
        if not address:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Address cannot be blank.")

        if not settings.geoclient_app_key:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="GeoClient API key is not configured on this server. Contact your admin.",
            )

        borough = body.borough
        if not borough:
            cfg = db.query(CompanyConfig).filter(CompanyConfig.company_id == caller.company_id).first()
            borough = (cfg.geoclient_borough if cfg and cfg.geoclient_borough else None) or "manhattan"

        # Address or intersection form — see _resolve_anchor_location.
        canonical, lat, lng = _resolve_anchor_location(address, borough)
        _assert_anchor_not_duplicate(
            db, caller.company_id, db_truck.id, lat, lng,
            own_other_anchor=(db_truck.initial_anchor_lat, db_truck.initial_anchor_lng),
        )

        db_truck.initial_anchor2_address         = canonical
        db_truck.initial_anchor2_display_address = address
        db_truck.initial_anchor2_lat             = lat
        db_truck.initial_anchor2_lng             = lng
        db_truck.initial_anchor2_set_by          = caller.id
        db_truck.initial_anchor2_set_at          = datetime.now(timezone.utc)

    write_audit(
        db,
        action_type="truck.anchor2_updated",
        target_table="trucks",
        target_id=str(db_truck.id),
        actor_id=str(caller.id),
        company_id=str(caller.company_id),
        after={"address": db_truck.initial_anchor2_address},
    )
    db.commit()
    db.refresh(db_truck)
    return db_truck


@router.delete("/{truck_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_truck(
    truck_id: UUID,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_write),
    db: Session = Depends(get_db),
):
    db_truck = db.query(Truck).filter(Truck.id == truck_id, Truck.company_id == caller.company_id).first()
    if not db_truck:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Truck not found")
    write_audit(
        db,
        action_type="truck.deleted",
        target_table="trucks",
        target_id=str(db_truck.id),
        actor_id=str(caller.id),
        company_id=str(caller.company_id),
        before={"name": db_truck.name, "is_active": db_truck.is_active},
        after=None,
    )
    db_truck.is_active = False
    db.commit()

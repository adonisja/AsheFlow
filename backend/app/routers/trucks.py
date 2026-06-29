import os
from datetime import datetime, timezone
from uuid import UUID

import aiohttp
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.api.deps import RoleChecker, get_caller_employee, Pagination
from app.models.employee import Employee
from app.models.truck import Truck
from app.schemas.truck import TruckCreate, TruckUpdate, TruckResponse, TruckAnchorPatch
from app.services.audit import write_audit

router = APIRouter(prefix="/trucks", tags=["trucks"])

allow_any_auth = RoleChecker(["driver", "walker", "trainer", "trainee", "dispatch", "management", "admin"])
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
    db.commit()
    db.refresh(db_truck)
    return db_truck


@router.get("/", response_model=list[TruckResponse])
def get_trucks(
    pg: Pagination = Depends(),
    include_inactive: bool = Query(default=False),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_any_auth),
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

    for key, value in truck.model_dump(exclude_unset=True).items():
        setattr(db_truck, key, value)

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

    Pass address + borough to geocode and store coordinates.
    Pass address=null to clear the anchor entirely.
    GeoClient resolves the address to lat/lng — users never enter raw coordinates.
    """
    from app.tasks.enrich_manifest import _geoclient_normalise
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

        geo = _geoclient_normalise(address, borough=borough)
        if geo is None or geo.lat is None or geo.lng is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Address could not be geocoded. Check the address and borough and try again.",
            )

        # Store GeoClient normalised form as the canonical address (reliable for re-geocoding,
        # API round-tripping, and sort seeds). Keep raw user input as display-only field.
        db_truck.initial_anchor_address         = geo.normalised_address or address
        db_truck.initial_anchor_display_address = address
        db_truck.initial_anchor_lat             = geo.lat
        db_truck.initial_anchor_lng             = geo.lng
        db_truck.initial_anchor_set_by          = caller.id
        db_truck.initial_anchor_set_at          = datetime.now(timezone.utc)

    write_audit(
        db,
        action_type="truck.anchor_updated",
        target_table="trucks",
        target_id=str(db_truck.id),
        actor_id=str(caller.id),
        company_id=str(caller.company_id),
        detail={"address": db_truck.initial_anchor_address},
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

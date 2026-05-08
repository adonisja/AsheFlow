"""Anchor point router.

Shift lifecycle for anchor points:

1. Driver sets a PRELIMINARY AP + ETA before leaving the station.
   → Notifies crew (truck Discord channel) and dispatch (in-app + Discord).
2. On arrival the driver taps "Arrived" (optionally updating the location).
   → Sends an "Arrived at <location>" notification to crew and dispatch.
3. If the driver needs to move to a different area mid-day they POST a new AP.
   → The previous AP is marked "relocated". Crew and dispatch are notified.

Only the first AP of the day (is_initial=True, sequence=1) feeds into
next-day driver suggestions via GET /anchor-points/truck/{id}.

Dispatch can acknowledge/confirm any AP via PATCH /{id}/confirm.
"""

import os
from datetime import date, datetime, timezone
from typing import List, Optional
from uuid import UUID

import aiohttp
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.api.deps import RoleChecker, get_caller_employee
from app.models.anchor_point import AnchorPoint
from app.models.employee import Employee
from app.models.truck import Truck
from app.models.truck_assignment import TruckAssignment
from app.models.assignment_member import AssignmentMember
from app.models.notification import Notification
from app.schemas.anchor_point import AnchorPointCreate, AnchorPointArriveUpdate, AnchorPointResponse

router = APIRouter(prefix="/anchor-points", tags=["anchor-points"])

allow_driver     = RoleChecker(["driver"])
allow_dispatch   = RoleChecker(["dispatch", "management", "admin"])
allow_truck_read = RoleChecker(["driver", "dispatch", "management", "admin"])
allow_any_auth   = RoleChecker(["driver", "walker", "trainer", "trainee", "dispatch", "management", "admin"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_assignment(db: Session, truck_id: UUID, target_date: date, driver_id: UUID) -> TruckAssignment:
    assignment = (
        db.query(TruckAssignment)
        .join(AssignmentMember, TruckAssignment.id == AssignmentMember.assignment_id)
        .filter(
            TruckAssignment.truck_id == truck_id,
            TruckAssignment.date == target_date,
            AssignmentMember.employee_id == driver_id,
            AssignmentMember.role == "driver",
        )
        .first()
    )
    if not assignment:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not assigned as driver to this truck on this date.",
        )
    return assignment


def _crew_employee_ids(db: Session, truck_id: UUID, target_date: date) -> List[UUID]:
    """Return employee IDs for everyone on the truck that day (for in-app notifications)."""
    members = (
        db.query(AssignmentMember)
        .join(TruckAssignment, TruckAssignment.id == AssignmentMember.assignment_id)
        .filter(TruckAssignment.truck_id == truck_id, TruckAssignment.date == target_date)
        .all()
    )
    return [m.employee_id for m in members]


def _notify(db: Session, employee_ids: List[UUID], notif_type: str, message: str) -> None:
    for eid in employee_ids:
        db.add(Notification(employee_id=eid, type=notif_type, message=message))


async def _post_embed_to_discord(channel_id: int, payload: dict) -> None:
    bot_url = os.environ.get("BOT_INTERNAL_URL", "http://bot:8001")
    secret  = os.environ.get("INTERNAL_SECRET", "")
    try:
        async with aiohttp.ClientSession() as session:
            await session.post(
                f"{bot_url}/internal/post-embed",
                json={"channel_id": channel_id, **payload},
                headers={"X-Internal-Secret": secret},
                timeout=aiohttp.ClientTimeout(total=5),
            )
    except Exception:
        pass


async def _post_message_to_discord(channel_id: int, message: str) -> None:
    bot_url = os.environ.get("BOT_INTERNAL_URL", "http://bot:8001")
    secret  = os.environ.get("INTERNAL_SECRET", "")
    try:
        async with aiohttp.ClientSession() as session:
            await session.post(
                f"{bot_url}/internal/post-to-channel",
                json={"channel_id": channel_id, "message": message},
                headers={"X-Internal-Secret": secret},
                timeout=aiohttp.ClientTimeout(total=5),
            )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Driver: submit preliminary AP (or new AP mid-day)
# ---------------------------------------------------------------------------

@router.post("/", response_model=AnchorPointResponse, status_code=status.HTTP_201_CREATED)
async def submit_anchor_point(
    payload: AnchorPointCreate,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_driver),
):
    """Submit a new anchor point.

    First call of the day creates the preliminary AP (is_initial=True, sequence=1).
    Subsequent calls mark the current active AP as "relocated" and create a new
    row with an incremented sequence number. Crew and dispatch are notified on
    every submission.
    """
    _get_assignment(db, payload.truck_id, payload.date, caller.id)

    # All APs for this truck today, ordered by sequence
    todays = (
        db.query(AnchorPoint)
        .filter(AnchorPoint.truck_id == payload.truck_id, AnchorPoint.date == payload.date)
        .order_by(AnchorPoint.sequence.asc())
        .all()
    )

    is_first = len(todays) == 0

    # Idempotency guard: if this is the initial AP and one already exists as
    # "preliminary" with the same location, return it rather than duplicating.
    if is_first is False:
        pass  # relocation — always create a new record
    else:
        existing_preliminary = next(
            (a for a in todays if a.status == "preliminary" and a.location == payload.location),
            None,
        )
        if existing_preliminary:
            return existing_preliminary

    sequence = 1 if is_first else todays[-1].sequence + 1

    # Mark the current active (non-relocated) AP as relocated
    for ap in todays:
        if ap.status in ("preliminary", "arrived"):
            ap.status = "relocated"

    new_ap = AnchorPoint(
        truck_id   = payload.truck_id,
        driver_id  = caller.id,
        date       = payload.date,
        sequence   = sequence,
        is_initial = is_first,
        status     = "preliminary",
        location   = payload.location,
        eta        = payload.eta,
        notes      = payload.notes,
    )
    db.add(new_ap)

    truck = db.query(Truck).filter(Truck.id == payload.truck_id).first()
    truck_name = truck.name if truck else str(payload.truck_id)

    if is_first:
        title       = f"📍 Preliminary Anchor Point — {truck_name}"
        color       = 0xF59E0B  # amber
        footer_text = "Awaiting arrival confirmation"
    else:
        title       = f"🔀 Anchor Point Relocated — {truck_name} (AP #{sequence})"
        color       = 0x8B5CF6  # purple

        footer_text = "Previous anchor point marked as relocated"

    fields = [{"name": "Driver", "value": caller.name, "inline": True},
              {"name": "Location", "value": payload.location, "inline": True}]
    if payload.eta:
        fields.append({"name": "ETA", "value": payload.eta, "inline": True})
    if payload.notes:
        fields.append({"name": "Notes", "value": payload.notes, "inline": False})

    notif_message = (
        f"{'📍' if is_first else '🔀'} {truck_name} — {caller.name} "
        f"{'set preliminary AP' if is_first else f'relocated to AP #{sequence}'}: "
        f"{payload.location}"
        + (f" ETA {payload.eta}" if payload.eta else "")
    )

    crew_ids      = _crew_employee_ids(db, payload.truck_id, payload.date)
    dispatch_emps = db.query(Employee).filter(Employee.role.in_(["dispatch", "admin"]), Employee.is_active == True).all()
    all_notify    = list({*crew_ids, *(e.id for e in dispatch_emps)})
    _notify(db, all_notify, "anchor_point_submitted", notif_message)

    db.commit()
    db.refresh(new_ap)

    if truck and truck.discord_channel_id:
        await _post_embed_to_discord(truck.discord_channel_id, {
            "title": title,
            "color": color,
            "fields": fields,
            "footer": footer_text,
        })

    return new_ap


# ---------------------------------------------------------------------------
# Driver: confirm arrival (one-tap or with location update)
# ---------------------------------------------------------------------------

@router.patch("/{anchor_id}/arrive", response_model=AnchorPointResponse)
async def arrive_anchor_point(
    anchor_id: UUID,
    payload: AnchorPointArriveUpdate,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_driver),
):
    """Driver confirms arrival at their anchor point.

    Optionally updates the location if actual conditions differed from the
    preliminary. Sets status to "arrived" and stamps arrived_at.
    Notifies crew and dispatch with an "Arrived" tag.
    """
    ap = db.query(AnchorPoint).filter(AnchorPoint.id == anchor_id).first()
    if not ap:
        raise HTTPException(status_code=404, detail="Anchor point not found.")
    if ap.driver_id != caller.id:
        raise HTTPException(status_code=403, detail="You can only confirm your own anchor point.")
    if ap.status == "relocated":
        raise HTTPException(status_code=400, detail="This anchor point has been superseded by a relocation.")
    if ap.status == "arrived":
        raise HTTPException(status_code=400, detail="Already marked as arrived.")

    if payload.location:
        ap.location = payload.location
    if payload.notes is not None:
        ap.notes = payload.notes
    ap.status     = "arrived"
    ap.arrived_at = datetime.now(timezone.utc)

    truck = db.query(Truck).filter(Truck.id == ap.truck_id).first()
    truck_name = truck.name if truck else str(ap.truck_id)

    fields = [{"name": "Driver",   "value": caller.name, "inline": True},
              {"name": "Location", "value": ap.location,  "inline": True}]
    if ap.notes:
        fields.append({"name": "Notes", "value": ap.notes, "inline": False})

    notif_message = f"✅ {truck_name} — {caller.name} arrived at: {ap.location}"

    crew_ids      = _crew_employee_ids(db, ap.truck_id, ap.date)
    dispatch_emps = db.query(Employee).filter(Employee.role.in_(["dispatch", "admin"]), Employee.is_active == True).all()
    all_notify    = list({*crew_ids, *(e.id for e in dispatch_emps)})
    _notify(db, all_notify, "anchor_point_arrived", notif_message)

    db.commit()
    db.refresh(ap)

    if truck and truck.discord_channel_id:
        await _post_embed_to_discord(truck.discord_channel_id, {
            "title": f"✅ Arrived at Anchor Point — {truck_name}",
            "color": 0x22C55E,  # green
            "fields": fields,
            "footer": "Arrival confirmed",
        })

    # Also update #drivers-chat so dispatch sees the confirmed AP without opening each truck channel
    drivers_channel_id = os.environ.get("DISCORD_DRIVERS_CHANNEL_ID")
    if drivers_channel_id and drivers_channel_id.isdigit():
        await _post_message_to_discord(
            int(drivers_channel_id),
            f"📍 **{truck_name}** — {caller.name} confirmed AP: **{ap.location}**",
        )

    return ap


# ---------------------------------------------------------------------------
# Dispatch: acknowledge an AP
# ---------------------------------------------------------------------------

@router.patch("/{anchor_id}/confirm", response_model=AnchorPointResponse)
def confirm_anchor_point(
    anchor_id: UUID,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_dispatch),
):
    """Dispatch acknowledges/confirms an anchor point. Idempotent."""
    ap = db.query(AnchorPoint).filter(AnchorPoint.id == anchor_id).first()
    if not ap:
        raise HTTPException(status_code=404, detail="Anchor point not found.")

    ap.confirmed_by = caller.id
    ap.confirmed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(ap)
    return ap


# ---------------------------------------------------------------------------
# Read endpoints
# ---------------------------------------------------------------------------

@router.get("/driver/today", response_model=List[AnchorPointResponse])
def get_my_anchor_points_today(
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_driver),
):
    """Return all of the caller's anchor points for today, ordered by sequence."""
    return (
        db.query(AnchorPoint)
        .filter(AnchorPoint.driver_id == caller.id, AnchorPoint.date == date.today())
        .order_by(AnchorPoint.sequence.asc())
        .all()
    )


@router.get("/date/{target_date}", response_model=List[AnchorPointResponse])
def get_anchor_points_for_date(
    target_date: date,
    db: Session = Depends(get_db),
    _: dict = Depends(allow_dispatch),
):
    """All anchor point submissions for a given date. Dispatch/admin only."""
    return (
        db.query(AnchorPoint)
        .filter(AnchorPoint.date == target_date)
        .order_by(AnchorPoint.truck_id, AnchorPoint.sequence.asc())
        .all()
    )


@router.get("/truck/{truck_id}", response_model=List[AnchorPointResponse])
def get_anchor_points_for_truck(
    truck_id: UUID,
    limit: int = Query(default=5, ge=1, le=30),
    db: Session = Depends(get_db),
    _: dict = Depends(allow_truck_read),
):
    """Return the last N initial APs for a truck (is_initial=True only).

    Used to populate the suggested-location list for the next day's driver.
    """
    return (
        db.query(AnchorPoint)
        .filter(AnchorPoint.truck_id == truck_id, AnchorPoint.is_initial == True)
        .order_by(AnchorPoint.date.desc())
        .limit(limit)
        .all()
    )

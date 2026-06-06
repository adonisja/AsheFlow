"""Anchor point router.

Shift lifecycle for anchor points:

1. Driver sets a PRELIMINARY AP + ETA before leaving the station.
   → Notifies crew (truck Discord channel) and dispatch (in-app + Discord).
2. On arrival the driver taps "Arrived" (optionally updating the location).
   → Sends an "Arrived at <location>" notification to crew and dispatch.
3. If the driver needs to move to a different area mid-day they POST a new AP
   with an expected_departure_at so crew know when to expect the move.
   → The previous AP is marked "relocated". Crew and dispatch are notified.
4. Driver taps "I'm leaving now" → PATCH /{id}/depart stamps actual_departed_at.
   → Crew and Discord are notified; expected_departure_at phase ends.

Running-late detection: any read of a preliminary AP whose ETA + 15 min has
passed triggers _maybe_flag_late(), which writes one AnchorPointLateFlag row
and flips is_running_late=True on the AP. Idempotent — only flags once.

Only the first AP of the day (is_initial=True, sequence=1) feeds into
next-day driver suggestions via GET /anchor-points/truck/{id}.

Dispatch can acknowledge/confirm any AP via PATCH /{id}/confirm.
"""

import os
from datetime import date, datetime, timezone, timedelta
from typing import List, Optional

from app.services.local_date import company_today
from uuid import UUID

import aiohttp
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.api.deps import RoleChecker, get_caller_employee
from app.models.anchor_point import AnchorPoint
from app.models.anchor_point_late_flag import AnchorPointLateFlag
from app.models.employee import Employee
from app.services.company_config import get_discord_config
from app.models.truck import Truck
from app.models.truck_assignment import TruckAssignment
from app.models.assignment_member import AssignmentMember
from app.models.notification import Notification
from app.schemas.anchor_point import (
    AnchorPointCreate,
    AnchorPointArriveUpdate,
    AnchorPointDepartUpdate,
    AnchorPointResponse,
)

router = APIRouter(prefix="/anchor-points", tags=["anchor-points"])

allow_driver     = RoleChecker(["driver"])
allow_dispatch   = RoleChecker(["dispatch", "management", "admin"])
allow_truck_read = RoleChecker(["driver", "dispatch", "management", "admin"])
allow_any_auth   = RoleChecker(["driver", "walker", "trainer", "trainee", "dispatch", "management", "admin"])
allow_field_staff = RoleChecker(["walker", "trainer", "trainee"])

_LATE_THRESHOLD_MINUTES = 15


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_assignment(db: Session, truck_id: UUID, target_date: date, driver_id: UUID, company_id: UUID) -> TruckAssignment:
    assignment = (
        db.query(TruckAssignment)
        .join(AssignmentMember, TruckAssignment.id == AssignmentMember.assignment_id)
        .filter(
            TruckAssignment.truck_id == truck_id,
            TruckAssignment.date == target_date,
            TruckAssignment.company_id == company_id,
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


def _crew_employee_ids(db: Session, truck_id: UUID, target_date: date, company_id: UUID) -> List[UUID]:
    """Return employee IDs for everyone on the truck that day (for in-app notifications)."""
    members = (
        db.query(AssignmentMember)
        .join(TruckAssignment, TruckAssignment.id == AssignmentMember.assignment_id)
        .filter(
            TruckAssignment.truck_id == truck_id,
            TruckAssignment.date == target_date,
            TruckAssignment.company_id == company_id,
        )
        .all()
    )
    return [m.employee_id for m in members]


def _notify(db: Session, employee_ids: List[UUID], notif_type: str, message: str, company_id: UUID) -> None:
    for eid in employee_ids:
        db.add(Notification(company_id=company_id, employee_id=eid, type=notif_type, message=message))


async def _post_embed_to_discord(channel_id: int, company_id: UUID, payload: dict) -> None:
    bot_url = os.environ.get("BOT_INTERNAL_URL", "http://bot:8001")
    secret  = os.environ.get("INTERNAL_SECRET", "")
    try:
        async with aiohttp.ClientSession() as session:
            await session.post(
                f"{bot_url}/internal/post-embed",
                json={"channel_id": channel_id, "company_id": str(company_id), **payload},
                headers={"X-Internal-Secret": secret},
                timeout=aiohttp.ClientTimeout(total=5),
            )
    except Exception:
        pass


async def _post_message_to_discord(channel_id: int, company_id: UUID, message: str) -> None:
    bot_url = os.environ.get("BOT_INTERNAL_URL", "http://bot:8001")
    secret  = os.environ.get("INTERNAL_SECRET", "")
    try:
        async with aiohttp.ClientSession() as session:
            await session.post(
                f"{bot_url}/internal/post-to-channel",
                json={"channel_id": channel_id, "company_id": str(company_id), "message": message},
                headers={"X-Internal-Secret": secret},
                timeout=aiohttp.ClientTimeout(total=5),
            )
    except Exception:
        pass


def _maybe_flag_late(db: Session, ap: AnchorPoint, truck_name: str, driver_name: str) -> bool:
    """Check if ap is overdue and flag it if not already flagged.

    Returns True if a new late flag was written (caller should commit + notify).
    Only acts on preliminary APs with a parseable ETA string.
    ETA is stored as a human string like "10:30 AM" — we parse it against today's date.
    """
    if ap.status != "preliminary" or ap.is_running_late or not ap.eta:
        return False

    now = datetime.now(timezone.utc)
    try:
        # ETA is a local time string e.g. "10:30 AM". Parse against the AP's date.
        eta_naive = datetime.strptime(f"{ap.date} {ap.eta}", "%Y-%m-%d %I:%M %p")
        # Treat as UTC for comparison purposes (no timezone config on AP yet)
        eta_dt = eta_naive.replace(tzinfo=timezone.utc)
    except ValueError:
        return False

    if now < eta_dt + timedelta(minutes=_LATE_THRESHOLD_MINUTES):
        return False

    minutes_late = int((now - eta_dt).total_seconds() / 60)

    ap.is_running_late = True
    ap.running_late_flagged_at = now

    db.add(AnchorPointLateFlag(
        company_id      = ap.company_id,
        anchor_point_id = ap.id,
        truck_id        = ap.truck_id,
        driver_id       = ap.driver_id,
        date            = ap.date,
        eta             = ap.eta,
        minutes_late    = minutes_late,
    ))
    return True


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
    row with an incremented sequence number. For relocations, expected_departure_at
    tells crew when the driver expects to leave the current AP.
    Crew and dispatch are notified on every submission.
    """
    _get_assignment(db, payload.truck_id, payload.date, caller.id, caller.company_id)

    todays = (
        db.query(AnchorPoint)
        .filter(
            AnchorPoint.truck_id == payload.truck_id,
            AnchorPoint.date == payload.date,
            AnchorPoint.company_id == caller.company_id,
        )
        .order_by(AnchorPoint.sequence.asc())
        .all()
    )

    is_first = len(todays) == 0

    if is_first:
        existing_preliminary = next(
            (a for a in todays if a.status == "preliminary" and a.location == payload.location),
            None,
        )
        if existing_preliminary:
            return existing_preliminary

    sequence = 1 if is_first else todays[-1].sequence + 1

    # Mark the current active AP as relocated; capture its location for the notification
    prev_location = None
    for ap in todays:
        if ap.status in ("preliminary", "arrived"):
            prev_location = ap.location
            ap.status = "relocated"

    new_ap = AnchorPoint(
        company_id            = caller.company_id,
        truck_id              = payload.truck_id,
        driver_id             = caller.id,
        date                  = payload.date,
        sequence              = sequence,
        is_initial            = is_first,
        status                = "preliminary",
        location              = payload.location,
        eta                   = payload.eta,
        notes                 = payload.notes,
        expected_departure_at = payload.expected_departure_at if not is_first else None,
    )
    db.add(new_ap)

    truck = db.query(Truck).filter(Truck.id == payload.truck_id, Truck.company_id == caller.company_id).first()
    truck_name = truck.name if truck else str(payload.truck_id)

    if is_first:
        title       = f"📍 Preliminary Anchor Point — {truck_name}"
        color       = 0xF59E0B  # amber
        footer_text = "Awaiting arrival confirmation"
        notif_message = (
            f"📍 {truck_name} — {caller.name} set preliminary AP: {payload.location}"
            + (f" ETA {payload.eta}" if payload.eta else "")
        )
    else:
        title       = f"🔀 Anchor Point Relocating — {truck_name} (AP #{sequence})"
        color       = 0x8B5CF6  # purple
        footer_text = "Driver relocating — previous AP marked relocated"

        dep_str = ""
        if payload.expected_departure_at:
            dep_str = f" (leaving {prev_location} at {payload.expected_departure_at.strftime('%I:%M %p')})"

        notif_message = (
            f"🔀 {truck_name} — {caller.name} relocating to AP #{sequence}: "
            f"{payload.location}"
            + dep_str
            + (f" ETA {payload.eta}" if payload.eta else "")
        )

    fields = [{"name": "Driver", "value": caller.name, "inline": True},
              {"name": "Location", "value": payload.location, "inline": True}]
    if not is_first and payload.expected_departure_at:
        fields.append({"name": "Expected Departure", "value": payload.expected_departure_at.strftime("%I:%M %p"), "inline": True})
    if payload.eta:
        fields.append({"name": "ETA", "value": payload.eta, "inline": True})
    if payload.notes:
        fields.append({"name": "Notes", "value": payload.notes, "inline": False})

    crew_ids      = _crew_employee_ids(db, payload.truck_id, payload.date, caller.company_id)
    dispatch_emps = db.query(Employee).filter(
        Employee.company_id == caller.company_id,
        Employee.role.in_(["dispatch", "admin"]),
        Employee.is_active == True,
    ).all()
    all_notify = list({*crew_ids, *(e.id for e in dispatch_emps)})
    _notify(db, all_notify, "anchor_point_submitted", notif_message, caller.company_id)

    db.commit()
    db.refresh(new_ap)

    if truck and truck.discord_channel_id:
        await _post_embed_to_discord(truck.discord_channel_id, caller.company_id, {
            "title": title,
            "color": color,
            "fields": fields,
            "footer": footer_text,
        })

    return new_ap


# ---------------------------------------------------------------------------
# Driver: confirm arrival
# ---------------------------------------------------------------------------

@router.patch("/{anchor_id}/arrive", response_model=AnchorPointResponse)
async def arrive_anchor_point(
    anchor_id: UUID,
    payload: AnchorPointArriveUpdate,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_driver),
):
    """Driver confirms arrival at their anchor point."""
    ap = db.query(AnchorPoint).filter(
        AnchorPoint.id == anchor_id,
        AnchorPoint.company_id == caller.company_id,
    ).first()
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

    truck = db.query(Truck).filter(Truck.id == ap.truck_id, Truck.company_id == caller.company_id).first()
    truck_name = truck.name if truck else str(ap.truck_id)

    fields = [{"name": "Driver",   "value": caller.name, "inline": True},
              {"name": "Location", "value": ap.location,  "inline": True}]
    if ap.notes:
        fields.append({"name": "Notes", "value": ap.notes, "inline": False})

    notif_message = f"✅ {truck_name} — {caller.name} arrived at: {ap.location}"

    crew_ids      = _crew_employee_ids(db, ap.truck_id, ap.date, caller.company_id)
    dispatch_emps = db.query(Employee).filter(
        Employee.company_id == caller.company_id,
        Employee.role.in_(["dispatch", "admin"]),
        Employee.is_active == True,
    ).all()
    all_notify = list({*crew_ids, *(e.id for e in dispatch_emps)})
    _notify(db, all_notify, "anchor_point_arrived", notif_message, caller.company_id)

    db.commit()
    db.refresh(ap)

    if truck and truck.discord_channel_id:
        await _post_embed_to_discord(truck.discord_channel_id, caller.company_id, {
            "title": f"✅ Arrived at Anchor Point — {truck_name}",
            "color": 0x22C55E,
            "fields": fields,
            "footer": "Arrival confirmed",
        })

    discord_cfg = get_discord_config(db, caller.company_id)
    if discord_cfg.is_configured and discord_cfg.drivers_channel_id:
        await _post_message_to_discord(
            discord_cfg.drivers_channel_id,
            caller.company_id,
            f"📍 **{truck_name}** — {caller.name} confirmed AP: **{ap.location}**",
        )

    return ap


# ---------------------------------------------------------------------------
# Driver: confirm actual departure ("I'm leaving now")
# ---------------------------------------------------------------------------

@router.patch("/{anchor_id}/depart", response_model=AnchorPointResponse)
async def depart_anchor_point(
    anchor_id: UUID,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_driver),
):
    """Driver taps 'I'm leaving now' — stamps actual_departed_at on the AP.

    Only valid on APs that have an expected_departure_at set (i.e. relocation
    pre-announcements). Notifies crew and Discord that the driver has left.
    """
    ap = db.query(AnchorPoint).filter(
        AnchorPoint.id == anchor_id,
        AnchorPoint.company_id == caller.company_id,
    ).first()
    if not ap:
        raise HTTPException(status_code=404, detail="Anchor point not found.")
    if ap.driver_id != caller.id:
        raise HTTPException(status_code=403, detail="You can only depart your own anchor point.")
    if ap.actual_departed_at:
        raise HTTPException(status_code=400, detail="Departure already recorded.")
    if not ap.expected_departure_at:
        raise HTTPException(status_code=400, detail="No expected departure set on this anchor point.")

    ap.actual_departed_at = datetime.now(timezone.utc)

    truck = db.query(Truck).filter(Truck.id == ap.truck_id, Truck.company_id == caller.company_id).first()
    truck_name = truck.name if truck else str(ap.truck_id)

    departed_str = ap.actual_departed_at.strftime("%I:%M %p")
    notif_message = f"🚚 {truck_name} — {caller.name} left {ap.location} at {departed_str}"

    crew_ids      = _crew_employee_ids(db, ap.truck_id, ap.date, caller.company_id)
    dispatch_emps = db.query(Employee).filter(
        Employee.company_id == caller.company_id,
        Employee.role.in_(["dispatch", "admin"]),
        Employee.is_active == True,
    ).all()
    all_notify = list({*crew_ids, *(e.id for e in dispatch_emps)})
    _notify(db, all_notify, "anchor_point_departed", notif_message, caller.company_id)

    db.commit()
    db.refresh(ap)

    if truck and truck.discord_channel_id:
        await _post_embed_to_discord(truck.discord_channel_id, caller.company_id, {
            "title": f"🚚 Departed — {truck_name}",
            "color": 0xF97316,  # orange — departure/en-route
            "fields": [
                {"name": "Driver",   "value": caller.name, "inline": True},
                {"name": "Left",     "value": ap.location,  "inline": True},
                {"name": "Departed", "value": departed_str, "inline": True},
            ],
            "footer": "En route to next anchor point",
        })

    return ap


# ---------------------------------------------------------------------------
# Dispatch: acknowledge an AP
# ---------------------------------------------------------------------------

@router.patch("/{anchor_id}/confirm", response_model=AnchorPointResponse)
async def confirm_anchor_point(
    anchor_id: UUID,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_dispatch),
):
    """Dispatch acknowledges an anchor point. Posts an in-channel embed to the truck channel."""
    ap = db.query(AnchorPoint).filter(
        AnchorPoint.id == anchor_id,
        AnchorPoint.company_id == caller.company_id,
    ).first()
    if not ap:
        raise HTTPException(status_code=404, detail="Anchor point not found.")

    ap.confirmed_by = caller.id
    ap.confirmed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(ap)

    truck = db.query(Truck).filter(Truck.id == ap.truck_id, Truck.company_id == caller.company_id).first()
    if truck and truck.discord_channel_id:
        await _post_embed_to_discord(truck.discord_channel_id, caller.company_id, {
            "title": f"✅ Anchor Point Acknowledged — {truck.name}",
            "color": 0x6366F1,
            "fields": [
                {"name": "Location", "value": ap.location, "inline": True},
                {"name": "Acknowledged by", "value": caller.name, "inline": True},
            ],
            "footer": "Dispatch has acknowledged this anchor point",
        })

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
        .filter(
            AnchorPoint.driver_id == caller.id,
            AnchorPoint.company_id == caller.company_id,
            AnchorPoint.date == company_today(db, caller.company_id),
        )
        .order_by(AnchorPoint.sequence.asc())
        .all()
    )


@router.get("/truck/{truck_id}/active", response_model=Optional[AnchorPointResponse])
async def get_active_anchor_point_for_truck(
    truck_id: UUID,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_any_auth),
):
    """Return the current active (non-relocated) AP for a truck today.

    Used by field staff (walker/trainer/trainee) to display the AP card on
    their FieldOps page. Also performs the running-late check — if the AP is
    overdue a late flag is written and crew notified in the same request.

    Returns null when no AP has been submitted yet today.
    """
    today = company_today(db, caller.company_id)

    ap = (
        db.query(AnchorPoint)
        .filter(
            AnchorPoint.truck_id   == truck_id,
            AnchorPoint.company_id == caller.company_id,
            AnchorPoint.date       == today,
            AnchorPoint.status.in_(["preliminary", "arrived"]),
        )
        .order_by(AnchorPoint.sequence.desc())
        .first()
    )

    if ap is None:
        return None

    # Running-late check — idempotent, only fires once per AP
    if _maybe_flag_late(db, ap, "", ""):
        # Fetch names for the notification
        truck = db.query(Truck).filter(Truck.id == truck_id, Truck.company_id == caller.company_id).first()
        truck_name = truck.name if truck else str(truck_id)
        driver = db.query(Employee).filter(Employee.id == ap.driver_id).first()
        driver_name = driver.name if driver else str(ap.driver_id)

        minutes_late = int((datetime.now(timezone.utc) - datetime.strptime(
            f"{ap.date} {ap.eta}", "%Y-%m-%d %I:%M %p"
        ).replace(tzinfo=timezone.utc)).total_seconds() / 60)

        notif_message = (
            f"⏰ {truck_name} — {driver_name} is running late "
            f"(ETA was {ap.eta}, {minutes_late} min overdue)"
        )
        crew_ids      = _crew_employee_ids(db, truck_id, today, caller.company_id)
        dispatch_emps = db.query(Employee).filter(
            Employee.company_id == caller.company_id,
            Employee.role.in_(["dispatch", "admin"]),
            Employee.is_active == True,
        ).all()
        all_notify = list({*crew_ids, *(e.id for e in dispatch_emps)})
        _notify(db, all_notify, "anchor_point_running_late", notif_message, caller.company_id)

        db.commit()
        db.refresh(ap)

        if truck and truck.discord_channel_id:
            await _post_embed_to_discord(truck.discord_channel_id, caller.company_id, {
                "title": f"⏰ Running Late — {truck_name}",
                "color": 0xEF4444,  # red
                "fields": [
                    {"name": "Driver",       "value": driver_name,        "inline": True},
                    {"name": "ETA Was",      "value": ap.eta,             "inline": True},
                    {"name": "Minutes Late", "value": str(minutes_late),  "inline": True},
                ],
                "footer": "Driver has not yet confirmed arrival",
            })

    return ap


@router.get("/date/{target_date}", response_model=List[AnchorPointResponse])
def get_anchor_points_for_date(
    target_date: date,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_dispatch),
):
    """All anchor point submissions for a given date. Dispatch/admin only."""
    return (
        db.query(AnchorPoint)
        .filter(AnchorPoint.date == target_date, AnchorPoint.company_id == caller.company_id)
        .order_by(AnchorPoint.truck_id, AnchorPoint.sequence.asc())
        .all()
    )


@router.get("/truck/{truck_id}", response_model=List[AnchorPointResponse])
def get_anchor_points_for_truck(
    truck_id: UUID,
    limit: int = Query(default=5, ge=1, le=30),
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_truck_read),
):
    """Return the last N initial APs for a truck (is_initial=True only).

    Used to populate the suggested-location list for the next day's driver.
    """
    return (
        db.query(AnchorPoint)
        .join(Truck, AnchorPoint.truck_id == Truck.id)
        .filter(
            AnchorPoint.truck_id == truck_id,
            AnchorPoint.is_initial == True,
            Truck.company_id == caller.company_id,
        )
        .order_by(AnchorPoint.date.desc())
        .limit(limit)
        .all()
    )

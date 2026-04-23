"""Anchor point router.

Drivers submit their EOD anchor point (truck parking location + ETA) after
completing their route. Dispatch confirms the submission. The record feeds
into next-morning dispatch planning.

Bot integration: on submit, the backend posts the AP to the truck's Discord
channel and as an in-app notification to dispatch/admin. This removes the need
for drivers to manually post in the channel — the app does it for them.
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
from app.schemas.anchor_point import AnchorPointCreate, AnchorPointResponse

router = APIRouter(prefix="/anchor-points", tags=["anchor-points"])

allow_driver     = RoleChecker(["driver"])
allow_dispatch   = RoleChecker(["dispatch", "management", "admin"])
allow_any_auth   = RoleChecker(["driver", "walker", "trainer", "trainee", "dispatch", "management", "admin"])


@router.post("/", response_model=AnchorPointResponse, status_code=status.HTTP_201_CREATED)
async def submit_anchor_point(
    payload: AnchorPointCreate,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_driver),
):
    """Submit EOD anchor point for a truck.

    Only the driver assigned to that truck on that date may submit.
    Idempotent — updates the record if one already exists for the same truck/date.

    On success:
    - Persists the anchor point record.
    - Fires in-app notifications to all active dispatch/admin employees.
    - Posts to the truck's Discord channel via the bot (best-effort).
    """
    # Verify caller is assigned as driver to this truck on this date
    assignment = (
        db.query(TruckAssignment)
        .join(AssignmentMember, TruckAssignment.id == AssignmentMember.assignment_id)
        .filter(
            TruckAssignment.truck_id == payload.truck_id,
            TruckAssignment.date == payload.date,
            AssignmentMember.employee_id == caller.id,
            AssignmentMember.role == "driver",
        )
        .first()
    )
    if not assignment:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not assigned as driver to this truck on this date.",
        )

    # Upsert — allow driver to update before dispatch confirms
    existing = db.query(AnchorPoint).filter(
        AnchorPoint.truck_id == payload.truck_id,
        AnchorPoint.date == payload.date,
    ).first()

    if existing:
        if existing.confirmed_at is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Anchor point already confirmed by dispatch and cannot be updated.",
            )
        existing.location = payload.location
        existing.eta = payload.eta
        existing.notes = payload.notes
        existing.submitted_at = datetime.now(timezone.utc)
        ap = existing
    else:
        ap = AnchorPoint(
            truck_id=payload.truck_id,
            driver_id=caller.id,
            date=payload.date,
            location=payload.location,
            eta=payload.eta,
            notes=payload.notes,
        )
        db.add(ap)

    # Notify all dispatch/admin employees in-app
    truck = db.query(Truck).filter(Truck.id == payload.truck_id).first()
    truck_name = truck.name if truck else str(payload.truck_id)
    eta_str = f" — ETA: {payload.eta}" if payload.eta else ""
    notif_message = (
        f"🅿️ {truck_name} anchor point submitted by {caller.name}: "
        f"{payload.location}{eta_str}"
        + (f". Notes: {payload.notes}" if payload.notes else "")
    )

    recipients = db.query(Employee).filter(
        Employee.role.in_(["dispatch", "admin"]),
        Employee.is_active == True,
    ).all()
    for rec in recipients:
        db.add(Notification(
            employee_id=rec.id,
            type="anchor_point_submitted",
            message=notif_message,
        ))

    db.commit()
    db.refresh(ap)

    # Post to truck's Discord channel via bot (best-effort)
    if truck and truck.discord_channel_id:
        await _post_anchor_to_discord(
            channel_id=truck.discord_channel_id,
            truck_name=truck_name,
            driver_name=caller.name,
            location=payload.location,
            eta=payload.eta,
            notes=payload.notes,
        )

    return ap


@router.patch("/{anchor_id}/confirm", response_model=AnchorPointResponse)
def confirm_anchor_point(
    anchor_id: UUID,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_dispatch),
):
    """Dispatch confirms an anchor point submission.

    Stamps confirmed_by and confirmed_at. Idempotent — re-confirming updates
    the confirmer but does not raise an error.
    """
    ap = db.query(AnchorPoint).filter(AnchorPoint.id == anchor_id).first()
    if not ap:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Anchor point not found.")

    ap.confirmed_by = caller.id
    ap.confirmed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(ap)
    return ap


@router.get("/date/{target_date}", response_model=List[AnchorPointResponse])
def get_anchor_points_for_date(
    target_date: date,
    db: Session = Depends(get_db),
    _: dict = Depends(allow_dispatch),
):
    """Return all anchor point submissions for a given date. Dispatch/admin only."""
    return db.query(AnchorPoint).filter(AnchorPoint.date == target_date).all()


@router.get("/truck/{truck_id}", response_model=List[AnchorPointResponse])
def get_anchor_points_for_truck(
    truck_id: UUID,
    limit: int = Query(default=30, ge=1, le=180),
    db: Session = Depends(get_db),
    _: dict = Depends(allow_dispatch),
):
    """Return recent anchor point history for a truck (default last 30 days)."""
    return (
        db.query(AnchorPoint)
        .filter(AnchorPoint.truck_id == truck_id)
        .order_by(AnchorPoint.date.desc())
        .limit(limit)
        .all()
    )


@router.get("/driver/today", response_model=Optional[AnchorPointResponse])
def get_my_anchor_point_today(
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_driver),
):
    """Return the caller's anchor point submission for today, if any."""
    today = date.today()
    return db.query(AnchorPoint).filter(
        AnchorPoint.driver_id == caller.id,
        AnchorPoint.date == today,
    ).first()


async def _post_anchor_to_discord(
    channel_id: int,
    truck_name: str,
    driver_name: str,
    location: str,
    eta: Optional[str],
    notes: Optional[str],
) -> None:
    """Best-effort POST to the bot's internal anchor-point endpoint."""
    bot_url = os.environ.get("BOT_INTERNAL_URL", "http://bot:8001")
    secret = os.environ.get("INTERNAL_SECRET", "")
    message_parts = [f"🅿️ **{truck_name}** — Anchor Point submitted by **{driver_name}**"]
    message_parts.append(f"📍 Location: {location}")
    if eta:
        message_parts.append(f"🕐 ETA: {eta}")
    if notes:
        message_parts.append(f"📝 {notes}")
    try:
        async with aiohttp.ClientSession() as session:
            await session.post(
                f"{bot_url}/internal/post-to-channel",
                json={"channel_id": channel_id, "message": "\n".join(message_parts)},
                headers={"X-Internal-Secret": secret},
                timeout=aiohttp.ClientTimeout(total=5),
            )
    except Exception:
        pass  # Non-fatal — driver already saved, notification already sent in-app

"""
Truck transfers router.

Intra-day transfer of field-role employees (walker, trainer, trainee) from
their original truck to a receiving truck.  The original AssignmentMember row
is preserved; a TruckTransfer row records the move.

Trainer transfers automatically pull along any paired trainees on the same
original assignment.

Endpoints:
  POST /truck-transfers              management | admin | dispatch
  GET  /truck-transfers?date=        management | admin | dispatch
  GET  /truck-transfers/mine?date=   any authenticated employee
"""

import os
import threading
import logging
import uuid
from datetime import date as date_type, datetime, timezone
from uuid import UUID

import requests as http_requests
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import RoleChecker, get_caller_employee
from app.database import get_db
from app.models.assignment_member import AssignmentMember
from app.models.employee import Employee
from app.models.notification import Notification
from app.models.truck import Truck
from app.models.truck_assignment import TruckAssignment
from app.models.truck_transfer import TruckTransfer
from app.services.audit import write_audit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/truck-transfers", tags=["truck-transfers"])

_dispatcher = RoleChecker(["management", "admin", "dispatch"])

TRANSFERABLE_ROLES = {"walker", "trainer", "trainee"}


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class TransferRequest(BaseModel):
    employee_ids: list[UUID]
    to_truck_id: UUID
    date: date_type
    note: str | None = None


class TransferOut(BaseModel):
    id: UUID
    employee_id: UUID
    employee_name: str
    from_truck_name: str
    to_truck_name: str
    transfer_date: date_type
    transferred_at: str
    note: str | None


class TransferResponse(BaseModel):
    transfers: list[TransferOut]
    warnings: list[str]


# ---------------------------------------------------------------------------
# Discord helper (mirrors _fire_swap_discord in dispatch.py)
# ---------------------------------------------------------------------------

def _fire_transfer_discord(
    company_id: str,
    discord_id: str | None,
    employee_name: str,
    old_channel_id: int | None,
    new_channel_id: int | None,
    from_truck_name: str,
    to_truck_name: str,
    transfer_date: str,
) -> None:
    bot_url = os.environ.get("BOT_INTERNAL_URL", "http://bot:8001")
    secret  = os.environ.get("INTERNAL_SECRET", "")

    payload: dict = {
        "company_id":    company_id,
        "employee_name": employee_name,
        "truck_name":    to_truck_name,
        "dispatch_date": transfer_date,
        "announce":      True,
        # Custom message context so the bot announcement reads correctly
        "transfer_context": {
            "from_truck": from_truck_name,
            "to_truck":   to_truck_name,
        },
    }
    if discord_id:
        payload["discord_id"]   = discord_id
    if old_channel_id:
        payload["old_channel_id"] = old_channel_id
    if new_channel_id:
        payload["new_channel_id"] = new_channel_id

    def _run():
        try:
            http_requests.post(
                f"{bot_url}/internal/swap",
                json=payload,
                headers={"X-Internal-Secret": secret},
                timeout=5,
            )
        except Exception as exc:
            logger.warning("transfer discord failed for %s: %s", employee_name, exc)

    threading.Thread(target=_run, daemon=True).start()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_out(
    transfer: TruckTransfer,
    employee_name: str,
    from_truck_name: str,
    to_truck_name: str,
) -> TransferOut:
    return TransferOut(
        id=transfer.id,
        employee_id=transfer.employee_id,
        employee_name=employee_name,
        from_truck_name=from_truck_name,
        to_truck_name=to_truck_name,
        transfer_date=transfer.transfer_date,
        transferred_at=transfer.transferred_at.isoformat(),
        note=transfer.note,
    )


# ---------------------------------------------------------------------------
# POST /truck-transfers
# ---------------------------------------------------------------------------

@router.post("", response_model=TransferResponse, status_code=status.HTTP_201_CREATED)
def create_transfers(
    body: TransferRequest,
    _: dict = Depends(_dispatcher),
    caller: Employee = Depends(get_caller_employee),
    db: Session = Depends(get_db),
):
    warnings: list[str] = []
    created: list[TransferOut] = []

    # Resolve destination truck assignment
    to_ta = (
        db.query(TruckAssignment)
        .join(Truck, TruckAssignment.truck_id == Truck.id)
        .filter(
            TruckAssignment.truck_id == body.to_truck_id,
            TruckAssignment.date == body.date,
            TruckAssignment.company_id == caller.company_id,
        )
        .first()
    )
    if not to_ta:
        raise HTTPException(status_code=404, detail="Destination truck has no assignment for this date.")

    to_truck = db.query(Truck).filter(
        Truck.id == body.to_truck_id,
        Truck.company_id == caller.company_id,
    ).first()

    if to_ta.status == "planned":
        raise HTTPException(
            status_code=409,
            detail="Cannot transfer to a truck that hasn't been published yet.",
        )

    # Expand: if a trainer is in the list, auto-add their paired trainees
    expanded_ids: list[UUID] = list(body.employee_ids)

    for eid in body.employee_ids:
        am = (
            db.query(AssignmentMember)
            .join(TruckAssignment, AssignmentMember.assignment_id == TruckAssignment.id)
            .filter(
                AssignmentMember.employee_id == eid,
                TruckAssignment.date == body.date,
                TruckAssignment.company_id == caller.company_id,
            )
            .first()
        )
        if am and am.role == "trainer":
            paired = (
                db.query(AssignmentMember)
                .filter(
                    AssignmentMember.assignment_id     == am.assignment_id,
                    AssignmentMember.company_id        == caller.company_id,
                    AssignmentMember.paired_trainer_id == eid,
                )
                .all()
            )
            for p in paired:
                if p.employee_id not in expanded_ids:
                    expanded_ids.append(p.employee_id)

    # Deduplicate while preserving order
    seen: set = set()
    unique_ids = []
    for eid in expanded_ids:
        if eid not in seen:
            seen.add(eid)
            unique_ids.append(eid)

    for eid in unique_ids:
        employee = db.query(Employee).filter(
            Employee.id == eid,
            Employee.company_id == caller.company_id,
        ).first()
        if not employee:
            warnings.append(f"Employee {eid} not found — skipped.")
            continue

        if employee.role not in TRANSFERABLE_ROLES:
            warnings.append(f"{employee.name} has role '{employee.role}' which cannot be transferred — skipped.")
            continue

        # Find their current assignment for this date
        from_am = (
            db.query(AssignmentMember)
            .join(TruckAssignment, AssignmentMember.assignment_id == TruckAssignment.id)
            .filter(
                AssignmentMember.employee_id == eid,
                TruckAssignment.date == body.date,
                TruckAssignment.company_id == caller.company_id,
            )
            .first()
        )
        if not from_am:
            warnings.append(f"{employee.name} has no assignment on {body.date} — skipped.")
            continue

        from_ta = db.query(TruckAssignment).filter(TruckAssignment.id == from_am.assignment_id).first()

        if from_ta.status == "planned":
            warnings.append(
                f"{employee.name}'s current truck hasn't been published yet — skipped. "
                "Use reassignment before publish instead."
            )
            continue

        if from_ta.id == to_ta.id:
            warnings.append(f"{employee.name} is already on the destination truck — skipped.")
            continue

        # Warn (don't block) if already transferred today
        existing_transfer = db.query(TruckTransfer).filter(
            TruckTransfer.employee_id == eid,
            TruckTransfer.transfer_date == body.date,
            TruckTransfer.company_id == caller.company_id,
        ).first()
        if existing_transfer:
            warnings.append(f"{employee.name} has already been transferred today.")

        from_truck = db.query(Truck).filter(Truck.id == from_ta.truck_id).first()

        transfer = TruckTransfer(
            id=uuid.uuid4(),
            company_id=caller.company_id,
            employee_id=eid,
            from_assignment_id=from_ta.id,
            to_assignment_id=to_ta.id,
            transfer_date=body.date,
            transferred_by=caller.id,
            note=body.note,
        )
        db.add(transfer)

        # Update the crew rosters to reflect the transfer (ADR-197). Previously a
        # transfer recorded a TruckTransfer + notified but left AssignmentMember
        # rows untouched, so /dispatch/{date} assigned_crews (built purely from
        # AssignmentMember) never reflected transfers — the source over-counted
        # and the destination under-counted. Now: mark the source 'transferred'
        # and add/reactivate an active row on the destination, so the live crew
        # count (F5) is correct on both trucks.
        from_am.status = "transferred"
        from_am.departed_at = datetime.now(timezone.utc)

        existing_to = db.query(AssignmentMember).filter(
            AssignmentMember.assignment_id == to_ta.id,
            AssignmentMember.employee_id == eid,
            AssignmentMember.company_id == caller.company_id,
        ).first()
        if existing_to is None:
            db.add(AssignmentMember(
                company_id        = caller.company_id,
                assignment_id     = to_ta.id,
                employee_id       = eid,
                role              = employee.role,
                paired_trainer_id = from_am.paired_trainer_id if employee.role == "trainee" else None,
                is_manual         = True,   # human-initiated placement
                status            = "active",
            ))
        else:
            # Re-activate if they'd previously departed/transferred off this truck.
            existing_to.status = "active"
            existing_to.departed_at = None

        # Notification
        db.add(Notification(
            company_id=caller.company_id,
            employee_id=eid,
            type="truck_transfer",
            message=(
                f"You've been transferred from {from_truck.name} to {to_truck.name} for today. "
                f"Check your Discord for your updated channel."
            ),
        ))

        db.flush()  # give transfer an id before building the response

        # Discord — fire and forget
        _fire_transfer_discord(
            company_id=str(caller.company_id),
            discord_id=str(employee.discord_id) if employee.discord_id else None,
            employee_name=employee.name,
            old_channel_id=from_truck.discord_channel_id if from_truck else None,
            new_channel_id=to_truck.discord_channel_id if to_truck else None,
            from_truck_name=from_truck.name if from_truck else "Unknown",
            to_truck_name=to_truck.name,
            transfer_date=str(body.date),
        )

        created.append(_build_out(
            transfer,
            employee.name,
            from_truck.name if from_truck else "Unknown",
            to_truck.name,
        ))

    db.commit()

    return TransferResponse(transfers=created, warnings=warnings)


# ---------------------------------------------------------------------------
# GET /truck-transfers/mine
# ---------------------------------------------------------------------------

@router.get("/mine", response_model=list[TransferOut])
def get_my_transfers(
    date: date_type = Query(...),
    caller: Employee = Depends(get_caller_employee),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(TruckTransfer)
        .filter(
            TruckTransfer.employee_id == caller.id,
            TruckTransfer.company_id == caller.company_id,
            TruckTransfer.transfer_date == date,
        )
        .order_by(TruckTransfer.transferred_at)
        .all()
    )

    result = []
    for t in rows:
        from_ta  = db.query(TruckAssignment).filter(TruckAssignment.id == t.from_assignment_id).first()
        to_ta    = db.query(TruckAssignment).filter(TruckAssignment.id == t.to_assignment_id).first()
        from_truck = db.query(Truck).filter(Truck.id == from_ta.truck_id).first() if from_ta else None
        to_truck   = db.query(Truck).filter(Truck.id == to_ta.truck_id).first() if to_ta else None
        result.append(_build_out(
            t,
            caller.name,
            from_truck.name if from_truck else "Unknown",
            to_truck.name if to_truck else "Unknown",
        ))
    return result


# ---------------------------------------------------------------------------
# GET /truck-transfers
# ---------------------------------------------------------------------------

@router.get("", response_model=list[TransferOut])
def get_transfers(
    date: date_type = Query(...),
    _: dict = Depends(_dispatcher),
    caller: Employee = Depends(get_caller_employee),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(TruckTransfer)
        .filter(
            TruckTransfer.transfer_date == date,
            TruckTransfer.company_id == caller.company_id,
        )
        .order_by(TruckTransfer.transferred_at)
        .all()
    )

    result = []
    for t in rows:
        employee   = db.query(Employee).filter(Employee.id == t.employee_id).first()
        from_ta    = db.query(TruckAssignment).filter(TruckAssignment.id == t.from_assignment_id).first()
        to_ta      = db.query(TruckAssignment).filter(TruckAssignment.id == t.to_assignment_id).first()
        from_truck = db.query(Truck).filter(Truck.id == from_ta.truck_id).first() if from_ta else None
        to_truck   = db.query(Truck).filter(Truck.id == to_ta.truck_id).first() if to_ta else None
        result.append(_build_out(
            t,
            employee.name if employee else str(t.employee_id),
            from_truck.name if from_truck else "Unknown",
            to_truck.name if to_truck else "Unknown",
        ))
    return result

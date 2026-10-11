import asyncio
import json
from datetime import datetime, timezone, timedelta
from sqlalchemy import or_
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import List, Literal
from pydantic import BaseModel, ConfigDict

from app.database import get_db, SessionLocal
from app.services.audit import write_audit
from app.api.deps import RoleChecker, get_caller_employee, Pagination, _resolve_employee_from_cognito
from app.core.security import verify_cognito_token
from app.models.employee import Employee
from app.models.notification import Notification
from app.models.role_guide import NotificationAcknowledgement
from app.routers.registration import ROLE_TO_COGNITO_GROUP
from app.schemas.notification import NotificationResponse, spec_fields

router = APIRouter(prefix="/notifications", tags=["notifications"])

# The SSE stream lives on its OWN router, registered in main.py WITHOUT the
# router-level require_configured dependency. That gate depends on
# get_current_user, which reads the Authorization HEADER — but EventSource
# cannot send headers, so the stream authenticates via ?token=. With the gate
# attached, every stream request 401'd ("Not authenticated") before the
# query-token auth ever ran, and browsers spun in an EventSource 401-reconnect
# loop. The stream enforces the same configured-company check INLINE after its
# token auth, so security parity is preserved.
stream_router = APIRouter(prefix="/notifications", tags=["notifications"])

# DERIVED from the canonical role list, not typed out. ADR-494: this constant
# sat here unused until the acknowledge endpoint needed it, and its hand-written
# list was missing `captain`, `field_supervisor` and `driver_trainee` -- three
# real roles in ROLE_TO_COGNITO_GROUP. Adopting it as written would have 403'd a
# captain trying to answer a timecard_mismatch GATE, which has no other exit:
# the gate would have been unanswerable for exactly the people it blocks.
#
# Deriving it means a role added to the system cannot acquire a Cognito group
# and silently lose access to its own notifications.
allow_any_auth   = RoleChecker(sorted(ROLE_TO_COGNITO_GROUP))
allow_management = RoleChecker(["dispatch", "management", "admin"])


@router.get("/{employee_id}", response_model=List[NotificationResponse])
def get_notifications(
    employee_id: UUID,
    skip:  int = Query(default=0,  ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
):
    """Get notifications for an employee, newest first.

    Only the employee themselves or management/dispatch/admin can read them.
    Defaults to the 50 most recent; supports ?skip and ?limit (max 200) for paging.
    """
    if caller.id != employee_id and caller.role not in ("dispatch", "management", "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
    now = datetime.now(timezone.utc)
    rows = (
        db.query(Notification)
        .filter(
            Notification.employee_id == employee_id,
            Notification.company_id == caller.company_id,
            or_(Notification.expires_at == None, Notification.expires_at > now),
        )
        .order_by(Notification.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    # ADR-487 D4: severity/label/tone/icon are resolved from the registry per
    # row, not stored. `from_row` rather than FastAPI's automatic
    # from_attributes conversion, because those four fields have no columns
    # behind them and automatic conversion would 500 on the missing attributes.
    # `from_row_scoped`, not `from_row`: ADR-494 D6's gate checks need a
    # session, and without one every gate degrades to a prompt. This is the
    # list a client renders its gate from, so the weaker answer here would
    # mean a gate never appears at all.
    return [NotificationResponse.from_row_scoped(r, db) for r in rows]


@router.patch("/{notification_id}/read")
def mark_read(
    notification_id: UUID,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
):
    """Mark a single notification as read. Only the owning employee can mark their own."""
    notif = db.query(Notification).filter(Notification.id == notification_id, Notification.company_id == caller.company_id).first()
    if notif:
        if notif.employee_id != caller.id and caller.role not in ("dispatch", "management", "admin"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
        notif.is_read = True
        db.commit()
    return {"ok": True}


class AcknowledgeIn(BaseModel):
    """What the person did with an interruptive notification (ADR-494 D7).

    Dimension 9: a request body, so every field is concrete and bounded and
    unknown keys are a 422. `action` is a Literal rather than `str` — the three
    values are the contract, and a fourth arriving from a client is a bug worth
    surfacing, not a row to store.
    """

    action: Literal["confirmed", "skipped", "unavailable"]
    #: Which surface the person actually saw. A gate and a prompt carry
    #: different weight in a later dispute, and the server cannot infer it after
    #: the fact: the degradation that produced a prompt is time-dependent (a
    #: deadline passes, a role guide is seeded), so re-deriving it at read time
    #: would give a different answer than the reader got.
    shown_as: Literal["gate", "prompt"]

    model_config = ConfigDict(extra="forbid")


@router.post("/{notification_id}/acknowledge", status_code=status.HTTP_201_CREATED)
def acknowledge_notification(
    notification_id: UUID,
    payload: AcknowledgeIn,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_any_auth),
):
    """Record that THIS person chose something about an interruptive notification.

    Not a read flag. `Notification.is_read` is set by RENDERING; this is set by a
    person CHOOSING, and conflating them is how a prompt closed by a stray tap
    becomes evidence of consent. For `timecard_mismatch` that evidence is what a
    payroll dispute six weeks later turns on.

    **Own notification only, with no oversight override.** `mark_read` lets
    dispatch/management/admin mark someone else's as read, which is reasonable
    for a read flag. It is not reasonable here: an acknowledgement is a
    first-person statement, and a manager recording that a walker "confirmed"
    their hours is the forgery this table exists to make impossible. Admins have
    full access everywhere else; this is a record of who clicked, so there is
    nothing for anyone else to do to it.

    Idempotent by primary key: `notification_id` IS the PK, so a double-tap or a
    retried request gets 409 rather than a second row. The first answer stands —
    a person who confirmed and then skipped has not un-confirmed.
    """
    notif = (
        db.query(Notification)
        .filter(
            Notification.id == notification_id,
            Notification.company_id == caller.company_id,
        )
        .first()
    )
    if notif is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found.",
        )

    if notif.employee_id != caller.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the person a notification was sent to can acknowledge it.",
        )

    existing = (
        db.query(NotificationAcknowledgement)
        .filter(
            NotificationAcknowledgement.notification_id == notification_id,
            NotificationAcknowledgement.company_id == caller.company_id,
        )
        .first()
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This notification has already been acknowledged.",
        )

    ack = NotificationAcknowledgement(
        notification_id=notification_id,
        # SNAPSHOTS, not a join. `prune_notifications` deletes the notification
        # after 3 days and the FK is SET NULL, so after that these two columns
        # are the only record of what the person was actually looking at when
        # they chose. An acknowledgement that cannot say WHAT was acknowledged
        # is not evidence of anything, which is the whole purpose of the row.
        notification_type=notif.type,
        message_snapshot=notif.message,
        employee_id=caller.id,
        company_id=caller.company_id,
        acknowledged_at=datetime.now(timezone.utc),
        action=payload.action,
        shown_as=payload.shown_as,
    )
    db.add(ack)

    # Acknowledging is seeing it. The reverse is NOT true -- that is the whole
    # point of two columns -- but a person who answered a gate has certainly
    # read it, and leaving the row unread would keep the banner up behind the
    # sheet they just dismissed.
    notif.is_read = True

    db.flush()
    write_audit(
        db=db,
        company_id=caller.company_id,
        actor_id=caller.id,
        action_type="notification.acknowledge",
        target_table="notification_acknowledgements",
        target_id=str(notification_id),
        detail={
            "notification_type": notif.type,
            "action": payload.action,
            "shown_as": payload.shown_as,
        },
    )
    db.commit()

    return {
        "notification_id": str(notification_id),
        "action": payload.action,
        "shown_as": payload.shown_as,
        "acknowledged_at": ack.acknowledged_at.isoformat(),
    }


@router.patch("/employee/{employee_id}/read-all")
def mark_all_read(
    employee_id: UUID,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
):
    """Mark all notifications as read, except ACTIONABLE dispatch assignments.

    dispatch_assignment notifications for TODAY or later still require an
    explicit Confirm/Decline and cannot be bulk-dismissed. Past ones can no
    longer be responded to (the confirmation window is closed), so excluding
    them left users with permanently-unread rows that "All read" appeared to
    ignore — those are now included in the bulk mark.

    Returns counts so clients can explain any rows deliberately left unread.
    """
    if caller.id != employee_id and caller.role not in ("dispatch", "management", "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

    from datetime import date as _date
    from sqlalchemy import and_, or_
    today = _date.today()

    base = db.query(Notification).filter(
        Notification.employee_id == employee_id,
        Notification.company_id == caller.company_id,
        Notification.is_read == False,  # noqa: E712
    )
    # Actionable = assignment for today/future (or unknown date — err safe).
    actionable = and_(
        Notification.type == "dispatch_assignment",
        or_(Notification.dispatch_date == None, Notification.dispatch_date >= today),  # noqa: E711
    )
    marked = base.filter(~actionable).update({"is_read": True}, synchronize_session=False)
    skipped = base.filter(actionable).count()
    db.commit()
    return {"ok": True, "marked": marked, "skipped_actionable": skipped}


@router.delete("/prune", status_code=status.HTTP_200_OK)
def prune_notifications(
    days: int = Query(default=3, ge=1, le=365, description="Delete notifications older than this many days"),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_management),
    db: Session = Depends(get_db),
):
    """Delete notifications older than N days (default 3). Management/admin only.

    Removes anything older than the window (read OR unread — an operational
    notice's shift is long over after a few days) plus any expired notification
    regardless of age (ADR-227). Same rule as the nightly prune_notifications
    task, so the manual and automated paths behave identically.
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    deleted = (
        db.query(Notification)
        .filter(
            Notification.company_id == caller.company_id,
            or_(
                # aged out (read or unread)
                Notification.created_at < cutoff,
                # expired regardless of read state
                (Notification.expires_at != None) & (Notification.expires_at <= now),
            ),
        )
        .delete(synchronize_session=False)
    )
    # ADR-132 DP-1 shape: a bulk delete records the COUNT and the criteria, since
    # the rows themselves are gone and cannot be snapshotted individually.
    write_audit(
        db=db,
        company_id=str(caller.company_id),
        actor_id=str(caller.id),
        action_type="notification.prune",
        target_table="notifications",
        target_id=str(caller.company_id),
        before={"deleted_count": deleted},
        after={"cutoff": cutoff.isoformat(), "days": days},
    )
    db.commit()
    return {"deleted": deleted, "cutoff": cutoff.date().isoformat(), "days": days}


_SSE_POLL_SECONDS = 10
_SSE_KEEPALIVE_SECONDS = 25


@stream_router.get("/{employee_id}/stream")
async def stream_notifications(
    employee_id: UUID,
    token: str = Query(..., description="Cognito ID token for authentication"),
):
    """Server-Sent Events stream of unread notifications for an employee.

    Sends the full unread list immediately on connect, then pushes a delta
    whenever new notifications appear (polled every 10 s server-side).
    Keepalive comments are sent every 25 s to prevent proxy timeouts.

    Auth is via ?token= query param because EventSource cannot send headers.
    Access: the employee themselves or management/dispatch/admin.
    """
    # Verify the token and resolve the caller — mirrors get_caller_employee but
    # reads the token from the query string instead of the Authorization header.
    try:
        claims = verify_cognito_token(token)
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token.")

    current_user = {
        "id": claims.get("sub", ""),
        "email": claims.get("email", ""),
        "username": claims.get("cognito:username") or claims.get("username", ""),
        "cognito_groups": claims.get("cognito:groups", []),
    }

    db = SessionLocal()
    try:
        caller, sub = _resolve_employee_from_cognito(current_user, db)
    finally:
        db.close()

    if not caller:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Employee not found.")
    if caller.id != employee_id and caller.role not in ("dispatch", "management", "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

    # Inline require_configured parity (this router skips the header-based
    # router-level gate — see stream_router comment above).
    from app.models.company import CompanyConfig
    db = SessionLocal()
    try:
        cfg = db.query(CompanyConfig).filter(
            CompanyConfig.company_id == caller.company_id
        ).first()
    finally:
        db.close()
    if cfg is None or not cfg.is_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Company setup is not complete.",
        )

    company_id = caller.company_id

    def _fetch_unread(seen_ids: set) -> tuple[list[dict], set]:
        """Query unread notifications, return only ones not yet sent."""
        db = SessionLocal()
        try:
            now = datetime.now(timezone.utc)
            rows = (
                db.query(Notification)
                .filter(
                    Notification.employee_id == employee_id,
                    Notification.company_id == company_id,
                    Notification.is_read == False,
                    or_(Notification.expires_at == None, Notification.expires_at > now),
                )
                .order_by(Notification.created_at.desc())
                .limit(50)
                .all()
            )
            new_rows = [r for r in rows if str(r.id) not in seen_ids]
            new_seen = seen_ids | {str(r.id) for r in rows}
            # ADR-487 D4. This dict is hand-built because it goes to
            # json.dumps, so it does NOT get the schema's fields for free —
            # which is the whole reason `spec_fields` exists rather than the
            # resolution being inlined in NotificationResponse. Two
            # serialisation paths for one model is where a half-converted
            # change fails only on the path nobody tested, and the client
            # would then see a severity over REST and none over the stream.
            payload = [
                {
                    "id": str(r.id),
                    "employee_id": str(r.employee_id),
                    "type": r.type,
                    "message": r.message,
                    "is_read": r.is_read,
                    "created_at": r.created_at.isoformat(),
                    "dispatch_date": r.dispatch_date.isoformat() if r.dispatch_date else None,
                    "expires_at": r.expires_at.isoformat() if r.expires_at else None,
                    # row + db so the stream and REST agree about a gate.
                    # ADR-494 D6 exists because two surfaces computing a
                    # downgrade independently is how they drift; two
                    # SERIALISATION paths doing it is the same bug one
                    # layer down.
                    **spec_fields(r.type, row=r, db=db),
                }
                for r in new_rows
            ]
            return payload, new_seen
        finally:
            db.close()

    async def _generate():
        seen_ids: set = set()
        seconds_since_keepalive = 0

        # Send initial batch immediately on connect
        payload, seen_ids = await asyncio.get_event_loop().run_in_executor(
            None, _fetch_unread, seen_ids
        )
        if payload:
            yield f"data: {json.dumps(payload)}\n\n"

        while True:
            await asyncio.sleep(_SSE_POLL_SECONDS)
            seconds_since_keepalive += _SSE_POLL_SECONDS

            payload, seen_ids = await asyncio.get_event_loop().run_in_executor(
                None, _fetch_unread, seen_ids
            )
            if payload:
                yield f"data: {json.dumps(payload)}\n\n"
                seconds_since_keepalive = 0
            elif seconds_since_keepalive >= _SSE_KEEPALIVE_SECONDS:
                yield ": keepalive\n\n"
                seconds_since_keepalive = 0

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )

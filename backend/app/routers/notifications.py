import asyncio
import json
from datetime import datetime, timezone, timedelta
from sqlalchemy import or_
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import List

from app.database import get_db, SessionLocal
from app.api.deps import RoleChecker, get_caller_employee, Pagination, _resolve_employee_from_cognito
from app.core.security import verify_cognito_token
from app.models.employee import Employee
from app.models.notification import Notification
from app.schemas.notification import NotificationResponse

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

allow_any_auth   = RoleChecker(["driver", "walker", "trainer", "trainee", "dispatch", "management", "admin"])
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
    return (
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
    days: int = Query(default=30, ge=1, le=365, description="Delete read notifications older than this many days"),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_management),
    db: Session = Depends(get_db),
):
    """Delete read notifications older than N days (default 30). Management/admin only.

    Only removes notifications that have already been marked as read — unread
    notifications are never pruned regardless of age.
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    deleted = (
        db.query(Notification)
        .filter(
            Notification.company_id == caller.company_id,
            or_(
                # old read notifications
                (Notification.is_read == True) & (Notification.created_at < cutoff),
                # expired notifications regardless of read state
                (Notification.expires_at != None) & (Notification.expires_at <= now),
            ),
        )
        .delete(synchronize_session=False)
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

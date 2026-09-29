"""Audit log helper.

Usage inside any router — call write_audit() before db.commit():

    write_audit(
        db,
        actor_id=current_user.get("id"),        # cognito sub / employee UUID
        action_type="pto.approved",
        target_table="time_off_requests",
        target_id=str(db_request.id),
        before={"status": "pending"},
        after={"status": "approved"},
    )
    db.commit()
"""

from __future__ import annotations

import datetime as _dt
import logging
from decimal import Decimal as _Decimal
from typing import Any, Optional
from uuid import UUID as _UUID_T

from sqlalchemy.orm import Session
from app.models.audit_log import AuditLog

logger = logging.getLogger(__name__)


def _jsonable(value: Any) -> Any:
    """Coerce an ORM value into something JSONB can hold (ADR-481).

    `before` snapshots are built with getattr() off the ORM, so they carry the
    COLUMN's Python type -- `Column(Time)` reads back as `datetime.time`, which
    json cannot encode. `after` comes from the request and is already strings,
    so the two halves of one snapshot had different types and only one survived.

    PATCH /companies/my-config 500'd on every save touching a time field, in
    prod, on the form an Owner must complete before the platform is usable.

    Coerced here rather than at the six call sites that build these snapshots:
    this function owns the JSONB boundary, and making every caller remember is
    the arrangement that produced the bug.
    """
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    # One isinstance tuple, so order within it does not matter -- .isoformat()
    # dispatches on the real type and a datetime keeps its time half. Order WOULD
    # matter if these became separate branches with different bodies (e.g. a
    # date-only str(value)), which is why they are deliberately one branch.
    if isinstance(value, (_dt.datetime, _dt.date, _dt.time)):
        return value.isoformat()
    if isinstance(value, _Decimal):
        return float(value)
    if isinstance(value, _UUID_T):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    # Unknown type: str() it rather than letting json raise. An audit row with a
    # stringified value is a record; a TypeError is a user who cannot save.
    return str(value)


def _safe_snapshot(snapshot: Optional[dict], which: str, action_type: str) -> Optional[dict]:
    """_jsonable over a whole snapshot, with a placeholder if it still fails.

    ADR-481 D2: an audit write must never be the reason an action fails. The row
    records the action; it is not the action. A snapshot that cannot be encoded
    even after coercion is replaced by a marker that NAMES the failure, so the
    gap is visible in the trail rather than looking like an absence of change.
    """
    if snapshot is None:
        return None
    try:
        return {str(k): _jsonable(v) for k, v in snapshot.items()}
    except Exception as exc:
        logger.warning(
            "audit %s: %s snapshot could not be serialised (%s); "
            "writing a placeholder so the action itself proceeds",
            action_type, which, type(exc).__name__,
        )
        return {"_unserialisable": True, "_error": type(exc).__name__}


def super_admin_identity(claims: dict) -> dict:
    """Who the platform owner is, for an audit row's PAYLOAD (ADR-274 D13/D14).

    Deliberately NOT for `actor_id`. That column is `ForeignKey("employees.id")`
    and a super admin has no Employee row by design (`get_super_admin` never
    touches the table), so writing their Cognito sub there raises
    ForeignKeyViolation and 500s the endpoint. The first implementation of the
    company audits did exactly that, and staging caught it.

    Super-admin rows leave `actor_id` NULL — which the column already documents
    as "system actions" — and carry the identity here instead: JSONB has no
    constraint. Lives in the audit service rather than a router because two
    super-admin surfaces now need it (companies, building_profile_library).
    """
    return {
        "actor_kind": "super_admin",
        "actor_cognito_sub": claims.get("id"),
        "actor_email": claims.get("email"),
    }


def write_audit(
    db: Session,
    *,
    action_type: str,
    target_table: str,
    target_id: str,
    actor_id: Optional[str] = None,
    company_id: Optional[str] = None,
    before: Optional[dict[str, Any]] = None,
    after: Optional[dict[str, Any]] = None,
    detail: Optional[dict[str, Any]] = None,
) -> None:
    """Append one immutable audit row to the session (does NOT commit).

    The caller is responsible for committing.  Placing write_audit() just
    before db.commit() ensures the audit row is part of the same transaction
    as the state change it records — either both land or neither does.

    `detail` is an accepted alias for `after` — many callers (walker_routes,
    rts, roll_call, employees, building_profiles) pass the post-change payload
    as `detail=`. It maps to `after` unless `after` is explicitly given.
    Previously those calls raised TypeError and 500-ed the endpoint (e.g.
    commit-sort, which surfaced in the browser as a misleading CORS error,
    2026-07-04).
    """
    from uuid import UUID as _UUID

    if after is None and detail is not None:
        after = detail

    actor_uuid: Optional[_UUID] = None
    if actor_id:
        try:
            actor_uuid = _UUID(str(actor_id))
        except (ValueError, AttributeError):
            pass

    company_uuid: Optional[_UUID] = None
    if company_id:
        try:
            company_uuid = _UUID(str(company_id))
        except (ValueError, AttributeError):
            pass

    try:
        target_uuid = _UUID(str(target_id))
    except (ValueError, AttributeError):
        return  # Silently skip if target_id is not a valid UUID

    db.add(AuditLog(
        actor_id=actor_uuid,
        company_id=company_uuid,
        action_type=action_type,
        target_table=target_table,
        target_id=target_uuid,
        before_snapshot=_safe_snapshot(before, "before", action_type),
        after_snapshot=_safe_snapshot(after, "after", action_type),
    ))

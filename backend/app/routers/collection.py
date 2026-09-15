"""Public data collection (ADR-415).

THE ONLY UNAUTHENTICATED WRITE PATH IN THIS SYSTEM. Everything here follows
from that, so the reasoning is worth stating rather than assuming:

  * Submissions land in `collected_address_profiles`, a quarantine table nothing
    reads except an authenticated promotion review (D1). The production
    `building_profiles` feeds the sort algorithm; an anonymous writer must not
    reach it.
  * `company_id` comes from the token, never the request body (D2). A public
    endpoint that trusted a body-supplied tenant id is a cross-tenant write.
  * POST only. No listing, no lookup, no "did it arrive" (D4) — the table holds
    customer delivery addresses, and the submitter already has a local copy.

CLAUDE.md Dimension 1 asks every query to filter by `caller.company_id`. There
is no caller here. Scoping is by token-derived company_id instead, which is the
same guarantee reached differently — recorded in ADR-415 rather than left as an
apparent omission.
"""
import logging
import secrets
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func as sa_func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import RoleChecker, get_caller_employee, get_super_admin
from app.api.ratelimit import limiter
from app.database import get_db
from app.models.collection import CollectedAddressProfile, CollectionToken
from app.models.employee import Employee
from app.schemas.collection import (
    CollectionCheckIn,
    CollectionCheckOut,
    CollectedProfileOut, CollectionSubmitIn, CollectionSubmitOut,
    CollectionTokenCreate, CollectionTokenOut, CollectionTokenSummary,
)
from app.services.audit import write_audit
from app.services.door_key import door_key
from app.schemas.building_taxonomy import category_for

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/collection", tags=["collection"])


def _resolve_token(db: Session, raw: str) -> CollectionToken:
    """Token → campaign, or 404.

    ALWAYS 404, never 401/403, and never a message distinguishing "no such
    token" from "revoked" from "expired". A public endpoint that reports which
    of those applies confirms a guessed token exists, turning the response into
    an oracle.
    """
    tok = db.query(CollectionToken).filter(CollectionToken.token == raw).first()
    now = datetime.now(timezone.utc)
    if (
        tok is None
        or tok.revoked_at is not None
        or (tok.expires_at is not None and tok.expires_at <= now)
    ):
        raise HTTPException(status_code=404, detail="Collection link is not active.")
    return tok


@router.post("/submit", response_model=CollectionSubmitOut, status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("30/minute")
def submit_profiles(
    request: Request,
    body: CollectionSubmitIn,
    db: Session = Depends(get_db),
):
    """Accept a batch of collected building profiles.

    202, not 201: this is a submission for later review, not a created resource
    the caller can go look at.
    """
    tok = _resolve_token(db, body.token)

    # D3 — a per-IP rate limit does not stop a distributed flood on one leaked
    # token, so the token carries its own daily ceiling.
    today = date.today()
    used = (
        db.query(sa_func.count(CollectedAddressProfile.id))
        .filter(
            CollectedAddressProfile.token_id == tok.id,
            CollectedAddressProfile.collected_on == today,
        )
        .scalar()
        or 0
    )
    if used + len(body.profiles) > tok.daily_cap:
        raise HTTPException(
            status_code=429,
            detail="Daily collection limit reached for this link.",
        )

    accepted = 0
    duplicate = 0
    # Which of THIS request's addresses the campaign already had. Not a read
    # path: every entry is an address the submitter just supplied (D4).
    duplicate_addresses: list[str] = []

    for p in body.profiles:
        row = CollectedAddressProfile(
            company_id=tok.company_id,          # from the TOKEN (D2)
            token_id=tok.id,
            address=p.address,
            building_type=p.building_type,
            # DERIVED, never from the body (ADR-418): a client-supplied category
            # could contradict its own type.
            building_category=category_for(p.building_type),
            has_security_desk=p.has_security_desk,
            workloads=p.workloads,
            workload_other=p.workload_other,
            # Kept in step for the readers that still expect one value. The
            # first tag is the collector's own primary choice, which is a
            # better single answer than re-deriving one from building_type.
            workload_class=p.workloads[0],
            note=p.note,
            opens_at=p.opens_at,
            closes_at=p.closes_at,
            break_start=p.break_start,
            break_end=p.break_end,
            troublesome=p.troublesome,
            collected_by=p.collected_by,
            collected_on=p.collected_on,
            # D7 — the folded key, set at the one place rows are created so it
            # can never drift from `address`.
            door_key=door_key(p.address)[:200],
        )
        db.add(row)
        try:
            # Per-row flush so one duplicate does not discard the batch. A
            # collector resubmitting after a dropped connection is the normal
            # case, not an error — the unique constraint absorbs it.
            db.flush()
            accepted += 1
        except IntegrityError:
            db.rollback()
            duplicate += 1
            duplicate_addresses.append(p.address)

    if accepted:
        write_audit(
            db,
            action_type="collection.submit",
            target_table="collected_address_profiles",
            target_id=str(tok.id),
            company_id=str(tok.company_id),
            # No actor_id: there is no account behind this, and inventing one
            # would make the audit log claim something untrue.
            detail={"label": tok.label, "accepted": accepted, "duplicate": duplicate},
        )
    db.commit()

    # D4 — receipt only. No ids, no echo of stored content.
    return CollectionSubmitOut(
        accepted=accepted,
        duplicate=duplicate,
        duplicate_addresses=duplicate_addresses,
    )


@router.post("/check", response_model=CollectionCheckOut, status_code=status.HTTP_200_OK)
@limiter.limit("60/minute")
def check_address(
    request: Request,
    body: CollectionCheckIn,
    db: Session = Depends(get_db),
):
    """Is this door already collected under this campaign? (ADR-417 D7)

    THIS IS A READ ON THE PUBLIC PATH, which ADR-415 D4 forbade outright. The
    narrowing that makes it acceptable, and the reasoning, are in ADR-417 D7.
    In short: the caller must already know the address to ask about it, so no
    content is disclosed — only existence, one address at a time.

    Why it exists: collection is a GROUP activity. A collector cannot know that
    a coworker profiled a building yesterday, so without this they walk to a
    door that is already done, and keep doing it. The waste is somebody's time
    in the field, repeatedly.

    What keeps it from being an enumeration oracle:
      - ONE address per request. No list parameter, ever.
      - Scoped to the caller's own campaign (`token_id`), so a token reveals
        only what that campaign itself collected — nothing about other
        campaigns or the wider table.
      - Rate limited per IP, so probing addresses is slow.
      - Returns a bool and a date. No id, no building type, no collector.
      - Same 404 for an inactive token as everywhere else, so it cannot be used
        to test whether a token is live any more cheaply than /submit can.

    Campaign-wide, NOT per-day (unlike the unique constraint, which is keyed by
    `collected_on` because re-observing a building later is legitimately new
    information). For "should I walk to this door", a profile from last week
    counts — that is exactly the walk worth skipping.
    """
    tok = _resolve_token(db, body.token)

    key = door_key(body.address)[:200]
    if not key:
        # An address that folds to nothing cannot match anything. Answer
        # honestly rather than running a query on an empty key.
        return CollectionCheckOut(known=False)

    row = (
        db.query(CollectedAddressProfile.collected_on)
        .filter(
            CollectedAddressProfile.token_id == tok.id,
            CollectedAddressProfile.door_key == key,
        )
        .order_by(CollectedAddressProfile.collected_on.desc())
        .first()
    )
    if row is None:
        return CollectionCheckOut(known=False)
    return CollectionCheckOut(known=True, collected_on=row[0])


# ── Operator side — authenticated ────────────────────────────────────────────

@router.post("/tokens", response_model=CollectionTokenOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
def create_token(
    request: Request,
    body: CollectionTokenCreate,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(RoleChecker(["management", "admin"])),
):
    """Issue a collection link. Management and admin only.

    Issuing one hands out write access to a tenant's collection table, so it
    sits behind the same gate as the rest of the tenant's configuration.
    """
    raw = secrets.token_urlsafe(32)[:64]
    tok = CollectionToken(
        company_id=caller.company_id,
        token=raw,
        label=body.label,
        daily_cap=body.daily_cap,
        expires_at=(
            datetime.now(timezone.utc) + timedelta(days=body.expires_in_days)
            if body.expires_in_days else None
        ),
        created_by=caller.id,
        created_by_name=f"{caller.first_name} {caller.last_name}".strip(),
    )
    db.add(tok)
    db.flush()
    write_audit(
        db,
        action_type="collection.token.create",
        target_table="collection_tokens",
        target_id=str(tok.id),
        actor_id=str(caller.id),
        company_id=str(caller.company_id),
        detail={"label": tok.label, "daily_cap": tok.daily_cap},
    )
    db.commit()
    db.refresh(tok)

    out = CollectionTokenOut.model_validate(tok)
    # Returned exactly once, here. Never readable afterwards.
    out.token = raw
    return out


@router.post("/tokens/{token_id}/revoke", status_code=status.HTTP_200_OK)
@limiter.limit("10/minute")
def revoke_token(
    request: Request,
    token_id: str,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(RoleChecker(["management", "admin"])),
):
    """The kill switch. Revoking stops submissions immediately."""
    tok = (
        db.query(CollectionToken)
        .filter(
            CollectionToken.id == token_id,
            # Dimension 1: scoped to the caller's tenant, so one company cannot
            # revoke another's link.
            CollectionToken.company_id == caller.company_id,
        )
        .first()
    )
    if tok is None:
        raise HTTPException(status_code=404, detail="Collection link not found.")
    if tok.revoked_at is not None:
        # One-way state stamp — 409 rather than silently re-stamping.
        raise HTTPException(status_code=409, detail="Already revoked.")

    tok.revoked_at = datetime.now(timezone.utc)
    db.flush()
    write_audit(
        db,
        action_type="collection.token.revoke",
        target_table="collection_tokens",
        target_id=str(tok.id),
        actor_id=str(caller.id),
        company_id=str(caller.company_id),
        detail={"label": tok.label},
    )
    db.commit()
    return {"revoked": True}


# ── Platform owner read (ADR-415 addendum) ───────────────────────────────────
#
# WHY get_super_admin AND NOT get_platform_staff
# ----------------------------------------------
# These rows are customer delivery addresses. ADR-343 D4 is explicit that no
# endpoint gated by `platform_support` may return addresses or personal data,
# because that login is cross-tenant and PII behind it becomes a cross-tenant
# PII surface. The platform OWNER reading data collected for their own campaigns
# is a different principal from support staff diagnosing a ticket, so this takes
# the stricter gate.
#
# These are the ONLY reads on collected data. The public submit path still
# exposes none (ADR-415 D4) — the collector already has their own local copy.


@router.get("/tokens", status_code=status.HTTP_200_OK)
@limiter.limit("60/minute")
def list_tokens(
    request: Request,
    company_id: str | None = Query(None, description="Filter to one tenant."),
    include_revoked: bool = Query(True),
    db: Session = Depends(get_db),
    _super: dict = Depends(get_super_admin),
) -> list[CollectionTokenSummary]:
    """Campaigns and how much has arrived under each.

    No company filter by default: the platform owner is looking across tenants,
    and `company_id` is offered as a narrowing option rather than imposed.

    The token VALUE is never returned — see CollectionTokenSummary.
    """
    q = db.query(CollectionToken)
    if company_id:
        q = q.filter(CollectionToken.company_id == company_id)
    if not include_revoked:
        q = q.filter(CollectionToken.revoked_at.is_(None))
    toks = q.order_by(CollectionToken.created_at.desc()).all()

    # One grouped count rather than a query per token: a listing that issues N+1
    # queries is fine at three campaigns and a problem at three hundred.
    counts = dict(
        db.query(
            CollectedAddressProfile.token_id,
            sa_func.count(CollectedAddressProfile.id),
        )
        .group_by(CollectedAddressProfile.token_id)
        .all()
    )

    out = []
    for t in toks:
        row = CollectionTokenSummary.model_validate(t)
        row.submission_count = counts.get(t.id, 0)
        out.append(row)
    return out


@router.get("/profiles", status_code=status.HTTP_200_OK)
@limiter.limit("60/minute")
def list_collected_profiles(
    request: Request,
    company_id: str | None = Query(None),
    token_id: str | None = Query(None),
    collected_on: date | None = Query(None, description="Single collection date."),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _super: dict = Depends(get_super_admin),
) -> list[CollectedProfileOut]:
    """Collected building profiles, newest first.

    Paged rather than unbounded: this table grows one row per building per
    collector per day, and an accidental full-table response over a phone
    connection is its own kind of outage.
    """
    q = db.query(CollectedAddressProfile)
    if company_id:
        q = q.filter(CollectedAddressProfile.company_id == company_id)
    if token_id:
        q = q.filter(CollectedAddressProfile.token_id == token_id)
    if collected_on:
        q = q.filter(CollectedAddressProfile.collected_on == collected_on)

    rows = (
        q.order_by(CollectedAddressProfile.submitted_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [CollectedProfileOut.model_validate(r) for r in rows]

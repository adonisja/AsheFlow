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

from app.api.deps import (
    RoleChecker,
    get_caller_employee,
    get_caller_employee_optional,
    get_current_user,
)
from app.api.ratelimit import limiter
from app.database import get_db
from app.models.collection import CollectedAddressProfile, CollectedWalkerDay, CollectionToken
from app.models.employee import Employee
from app.schemas.walker_day import (
    CollectedWalkerDayDetail, CollectedWalkerDayOut,
    WalkerDaySubmitIn, WalkerDaySubmitOut,
)
from app.schemas.collection import (
    SCOPE_COMPANY,
    SCOPE_OPEN,
    VERIFICATION_LIMIT,
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


def _authorise_scope(tok: CollectionToken, caller: Employee | None) -> None:
    """Who may submit under this campaign (ADR-423 D2).

    OPEN campaigns are unchanged: the link is the credential, which is the whole
    point of the public collection page.

    COMPANY campaigns require an authenticated employee of the owning company.
    The link alone is not enough — it can be forwarded, and a company survey is
    scoped to a staff pool the way Driver Survey is. Two checks, not one:
    authenticated AND of the right tenant, because an employee of company B
    holding company A's link must not write into A's data.

    Raises 401 when unauthenticated (the client can fix that by logging in) and
    403 when authenticated as the wrong tenant (it cannot).
    """
    if tok.scope != SCOPE_COMPANY:
        return
    if caller is None:
        raise HTTPException(
            status_code=401,
            detail="This collection link requires you to sign in.",
        )
    if caller.company_id != tok.company_id:
        raise HTTPException(
            status_code=403,
            detail="This collection link belongs to another company.",
        )


@router.post("/submit", response_model=CollectionSubmitOut, status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("30/minute")
def submit_profiles(
    request: Request,
    body: CollectionSubmitIn,
    db: Session = Depends(get_db),
    # ADR-423: optional, so an OPEN campaign still needs no login.
    caller: Employee | None = Depends(get_caller_employee_optional),
):
    """Accept a batch of collected building profiles.

    202, not 201: this is a submission for later review, not a created resource
    the caller can go look at.
    """
    tok = _resolve_token(db, body.token)
    _authorise_scope(tok, caller)

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

    # ADR-420. Doors already at the verification limit, counted once up front.
    #
    # The UI refuses a locked door on blur; this is what makes it a rule rather
    # than a suggestion — /submit is public, so anything holding a token can
    # post a batch the form would never have produced. One grouped query, not
    # one per row: a batch of a hundred profiles should not be a hundred counts.
    keys = [door_key(p.address)[:200] for p in body.profiles]
    locked_keys = {
        k for k, n in (
            db.query(
                CollectedAddressProfile.door_key,
                sa_func.count(CollectedAddressProfile.id),
            )
            .filter(
                CollectedAddressProfile.token_id == tok.id,
                CollectedAddressProfile.door_key.in_(keys),
            )
            .group_by(CollectedAddressProfile.door_key)
            .all()
        )
        if n >= VERIFICATION_LIMIT
    }

    for p in body.profiles:
        if door_key(p.address)[:200] in locked_keys:
            # Counted as a duplicate rather than failing the batch: the rest of
            # the submission is good, and the collector is told which addresses
            # were already answered.
            duplicate += 1
            duplicate_addresses.append(p.address)
            continue
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
    # ADR-423: optional, so an OPEN campaign still needs no login.
    caller: Employee | None = Depends(get_caller_employee_optional),
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
    _authorise_scope(tok, caller)

    key = door_key(body.address)[:200]
    if not key:
        # An address that folds to nothing cannot match anything. Answer
        # honestly rather than running a query on an empty key.
        return CollectionCheckOut(known=False)

    rows = (
        db.query(CollectedAddressProfile.collected_on)
        .filter(
            CollectedAddressProfile.token_id == tok.id,
            CollectedAddressProfile.door_key == key,
        )
        .order_by(CollectedAddressProfile.collected_on.desc())
        # Bounded: the answer only needs to distinguish 0, 1 and "at the limit",
        # so there is no reason to read an unbounded set to count it.
        .limit(VERIFICATION_LIMIT + 1)
        .all()
    )
    if not rows:
        return CollectionCheckOut(known=False)
    return CollectionCheckOut(
        known=True,
        collected_on=rows[0][0],
        count=len(rows),
        locked=len(rows) >= VERIFICATION_LIMIT,
    )


@router.post("/submit-day", response_model=WalkerDaySubmitOut,
             status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("30/minute")
def submit_walker_days(
    request: Request,
    body: WalkerDaySubmitIn,
    db: Session = Depends(get_db),
    # ADR-423: optional, so an OPEN campaign still needs no login.
    caller: Employee | None = Depends(get_caller_employee_optional),
):
    """Accept a batch of logged walker days (ADR-417 D3-D5).

    202, not 201: a submission for later review, not a resource the caller can
    go and look at. There is no read on this path, for the same reason there is
    none on /submit — see ADR-415 D4.

    UPSERTS on (token, collected_on, walker_name). A resubmission REPLACES the
    day rather than adding a second one: the field connection drops mid-submit
    often enough that a retry has to be safe, and the page already models one
    row per walker per date locally, so last-write-wins is what the collector
    sees. `revision` counts the overwrites so a reader can tell a corrected day
    from a first submission.
    """
    tok = _resolve_token(db, body.token)
    _authorise_scope(tok, caller)

    # Same daily ceiling as addresses, counted in the same unit: one row is one
    # day's work by one walker. A leaked token that could not write addresses
    # but could write unlimited days would not be bounded at all.
    today = date.today()
    used = (
        db.query(sa_func.count(CollectedWalkerDay.id))
        .filter(
            CollectedWalkerDay.token_id == tok.id,
            CollectedWalkerDay.collected_on == today,
        )
        .scalar()
        or 0
    )
    if used + len(body.days) > tok.daily_cap:
        raise HTTPException(
            status_code=429,
            detail="Daily collection limit reached for this link.",
        )

    accepted = 0
    replaced = 0

    for d in body.days:
        # `.model_dump(mode="json")` and not the model object: a JSONB column
        # handed a Pydantic object stores a Python repr, not JSON. `mode="json"`
        # so the nested `date` becomes a string rather than a date instance
        # psycopg cannot serialise inside a dict.
        payload = d.model_dump(mode="json")

        routes = d.routes
        counts = dict(
            route_count=len(routes),
            tote_count=sum(len(r.totes) for r in routes),
            rts_count=sum(len(r.rts) for r in routes),
        )

        existing = (
            db.query(CollectedWalkerDay)
            .filter(
                CollectedWalkerDay.token_id == tok.id,
                CollectedWalkerDay.collected_on == d.collected_on,
                CollectedWalkerDay.walker_name == d.walker_name,
            )
            .first()
        )

        if existing is not None:
            existing.arrival_time   = d.arrival_time or None
            existing.departure_time = d.departure_time or None
            existing.payload        = payload
            existing.revision       = (existing.revision or 1) + 1
            existing.submitted_at   = datetime.now(timezone.utc)
            for k, v in counts.items():
                setattr(existing, k, v)
            replaced += 1
        else:
            db.add(CollectedWalkerDay(
                company_id=tok.company_id,      # from the TOKEN, never the body
                token_id=tok.id,
                walker_name=d.walker_name,
                collected_on=d.collected_on,
                arrival_time=d.arrival_time or None,
                departure_time=d.departure_time or None,
                payload=payload,
                **counts,
            ))
            accepted += 1

        try:
            # Per-row flush so one bad day does not discard the batch, and so a
            # concurrent submit of the same day surfaces here rather than at
            # commit.
            db.flush()
        except IntegrityError:
            # Two devices submitting the same walker-day at once: the loser
            # re-reads and overwrites, which is the same last-write-wins rule
            # the sequential path applies.
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail="That day was submitted concurrently. Send it again.",
            )

    if accepted or replaced:
        write_audit(
            db,
            action_type="collection.submit_day",
            target_table="collected_walker_days",
            target_id=str(tok.id),
            company_id=str(tok.company_id),
            # No actor_id: there is no account behind this, and inventing one
            # would make the audit log claim something untrue.
            detail={"label": tok.label, "accepted": accepted, "replaced": replaced},
        )
    db.commit()

    return WalkerDaySubmitOut(accepted=accepted, replaced=replaced)


# ── Operator side — authenticated ────────────────────────────────────────────

@router.post("/tokens", response_model=CollectionTokenOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
def create_token(
    request: Request,
    body: CollectionTokenCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    caller: Employee | None = Depends(get_caller_employee_optional),
):
    """Issue a collection link (ADR-423).

    TWO PRINCIPALS, and the caller decides the scope — not the request body.

      super admin   -> an OPEN campaign. company_id NULL, anyone with the link
                       may submit. It collects across tenants, so no company
                       admin can read it.
      company admin -> a COMPANY campaign bound to their own company, and only
                       an authenticated employee of that company may submit.

    This endpoint used to take `get_caller_employee` unconditionally, so a
    super admin hit "No employee record found for your account" on the very
    page built for them: the platform owner has no Employee row by design
    (see get_super_admin). The optional resolver lets both through, and the
    branch below is what refuses everyone else.
    """
    groups = current_user.get("cognito_groups", [])
    is_super = "super_admin" in groups

    if is_super:
        company_id = None
        scope = SCOPE_OPEN
        created_by = None
        created_by_name = current_user.get("username") or "platform"
    else:
        # A company admin. RoleChecker is not used here because the two
        # principals need different gates on one endpoint; the role check is
        # inline and does the same job.
        if caller is None:
            raise HTTPException(
                status_code=403,
                detail="No employee record found for your account. Contact your manager.",
            )
        if (caller.role or "").lower() not in ("management", "admin"):
            raise HTTPException(
                status_code=403,
                detail="Only management or admin can issue a collection link.",
            )
        company_id = caller.company_id
        scope = SCOPE_COMPANY
        created_by = caller.id
        created_by_name = f"{caller.first_name} {caller.last_name}".strip()

    raw = secrets.token_urlsafe(32)[:64]
    tok = CollectionToken(
        scope=scope,
        company_id=company_id,
        token=raw,
        label=body.label,
        daily_cap=body.daily_cap,
        expires_at=(
            datetime.now(timezone.utc) + timedelta(days=body.expires_in_days)
            if body.expires_in_days else None
        ),
        created_by=created_by,
        created_by_name=created_by_name,
    )
    db.add(tok)
    db.flush()
    write_audit(
        db,
        action_type="collection.token.create",
        target_table="collection_tokens",
        target_id=str(tok.id),
        actor_id=str(created_by) if created_by else None,
        company_id=str(company_id) if company_id else None,
        detail={"label": tok.label, "daily_cap": tok.daily_cap, "scope": scope},
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


# ── Reads (ADR-415 addendum, rescoped by ADR-423) ────────────────────────────
#
# WHO CAN READ WHAT
# -----------------
# super admin   — everything. Open campaigns are the platform's own.
# company admin — only rows carrying their company_id. Open-campaign rows carry
#                 NULL, and `company_id == <uuid>` never matches NULL, so they
#                 are excluded by the comparison rather than by a clause someone
#                 has to remember. See _scope_reads.
# anyone else   — 403.
#
# STILL NOT get_platform_staff, and this is the part ADR-423 must not erode.
# These rows are customer delivery addresses and, on the walker-day side, real
# coworkers' names. ADR-343 D4 is explicit that no endpoint gated by
# `platform_support` may return addresses or personal data, because that login
# is cross-tenant and PII behind it becomes a cross-tenant PII surface. Widening
# from "super admin only" to "super admin OR the owning company's admin" adds a
# principal who already owns the data; it does not add a cross-tenant one.
#
# These are the ONLY reads on collected data. The public submit path still
# exposes none (ADR-415 D4) — the collector already has their own local copy.


def _scope_reads(q, model, current_user: dict, caller: Employee | None):
    """Narrow a read to what this caller may see (ADR-423 D3).

    A super admin sees everything, open and company alike — they are the
    platform owner and the open campaigns are theirs.

    A company admin sees ONLY rows carrying their own company_id. Open-campaign
    rows carry NULL, and `company_id == <uuid>` never matches NULL in SQL, so
    they are excluded by the comparison itself rather than by an extra clause
    someone has to remember to write.

    Anyone else gets 403 rather than an empty list: "you may not read this" and
    "there is nothing here" are different answers, and returning the second for
    the first teaches a caller the wrong thing.
    """
    if "super_admin" in current_user.get("cognito_groups", []):
        return q
    if caller is None or (caller.role or "").lower() not in ("management", "admin"):
        raise HTTPException(
            status_code=403,
            detail="Only management or admin can read collected data.",
        )
    return q.filter(model.company_id == caller.company_id)


@router.get("/tokens", status_code=status.HTTP_200_OK)
@limiter.limit("60/minute")
def list_tokens(
    request: Request,
    company_id: str | None = Query(None, description="Filter to one tenant."),
    include_revoked: bool = Query(True),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    caller: Employee | None = Depends(get_caller_employee_optional),
) -> list[CollectionTokenSummary]:
    """Campaigns and how much has arrived under each.

    No company filter by default: the platform owner is looking across tenants,
    and `company_id` is offered as a narrowing option rather than imposed.

    The token VALUE is never returned — see CollectionTokenSummary.
    """
    q = _scope_reads(db.query(CollectionToken), CollectionToken, current_user, caller)
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


@router.get("/walker-days", status_code=status.HTTP_200_OK)
@limiter.limit("60/minute")
def list_collected_days(
    request: Request,
    company_id: str | None = Query(None),
    token_id: str | None = Query(None),
    collected_on: date | None = Query(None, description="Single collection date."),
    walker: str | None = Query(None, max_length=100, description="Exact walker name."),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    caller: Employee | None = Depends(get_caller_employee_optional),
) -> list[CollectedWalkerDayOut]:
    """Logged walker days, newest first. Counts only, no payloads.

    SUPER ADMIN, not platform staff. These rows carry real coworkers' names and
    ADR-343 D4 keeps personal data off every cross-tenant support path.

    The payload is excluded deliberately: a page of forty days with every tote
    and address inline is a large response for a listing that only needs the
    counts. Use /walker-days/{id} for one day in full.
    """
    q = _scope_reads(db.query(CollectedWalkerDay), CollectedWalkerDay,
                     current_user, caller)
    if company_id:
        q = q.filter(CollectedWalkerDay.company_id == company_id)
    if token_id:
        q = q.filter(CollectedWalkerDay.token_id == token_id)
    if collected_on:
        q = q.filter(CollectedWalkerDay.collected_on == collected_on)
    if walker:
        q = q.filter(CollectedWalkerDay.walker_name == walker)

    rows = (
        q.order_by(CollectedWalkerDay.collected_on.desc(),
                   CollectedWalkerDay.submitted_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [CollectedWalkerDayOut.model_validate(r) for r in rows]


@router.get("/walker-days/{day_id}", status_code=status.HTTP_200_OK)
@limiter.limit("60/minute")
def get_collected_day(
    request: Request,
    day_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    caller: Employee | None = Depends(get_caller_employee_optional),
) -> CollectedWalkerDayDetail:
    """One logged day, payload included."""
    # Scoped, not just fetched by id: without this a company admin could read
    # any day by guessing a UUID, which is the classic IDOR.
    row = _scope_reads(db.query(CollectedWalkerDay), CollectedWalkerDay,
                       current_user, caller).filter(
        CollectedWalkerDay.id == day_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="No such collected day.")
    return CollectedWalkerDayDetail.model_validate(row)


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
    current_user: dict = Depends(get_current_user),
    caller: Employee | None = Depends(get_caller_employee_optional),
) -> list[CollectedProfileOut]:
    """Collected building profiles, newest first.

    Paged rather than unbounded: this table grows one row per building per
    collector per day, and an accidental full-table response over a phone
    connection is its own kind of outage.
    """
    q = _scope_reads(db.query(CollectedAddressProfile), CollectedAddressProfile,
                     current_user, caller)
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

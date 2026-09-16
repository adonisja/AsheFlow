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
    get_caller_employee_anonymous,
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
    LeaderboardEntryOut,
    LeaderboardIn,
    SCOPE_COMPANY,
    SCOPE_OPEN,
    TOP_COLLECTORS,
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
    # ADR-423: anonymous-tolerant. NOT get_caller_employee_optional — that one
    # is optional about the employee ROW but still 401s on a missing
    # Authorization header, which made every public collection path demand a
    # login.
    caller: Employee | None = Depends(get_caller_employee_anonymous),
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
    updated = 0
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

    # ADR-426. Rows THIS device already owns, so a correction updates in place
    # instead of being refused as a duplicate.
    #
    # Checked BEFORE the lock, deliberately: the verification limit exists to
    # stop a third OBSERVATION, not to freeze a collector's own typo into the
    # data. A device correcting its own row leaves the door with exactly the
    # same number of observations it had.
    owned: dict[str, CollectedAddressProfile] = {}
    if body.device_id:
        owned = {
            r.door_key: r
            for r in db.query(CollectedAddressProfile).filter(
                CollectedAddressProfile.token_id == tok.id,
                CollectedAddressProfile.device_id == body.device_id,
                CollectedAddressProfile.door_key.in_(keys),
            )
        }

    for p in body.profiles:
        key = door_key(p.address)[:200]

        mine = owned.get(key)
        if mine is not None:
            # An update, not a new observation. `collected_on` is deliberately
            # NOT changed: the date records when the door was seen, and
            # correcting a typo days later does not move that.
            mine.address           = p.address
            mine.building_type     = p.building_type
            mine.building_category = category_for(p.building_type)
            mine.has_security_desk = p.has_security_desk
            mine.workloads         = p.workloads
            mine.workload_other    = p.workload_other
            mine.workload_class    = p.workloads[0]
            mine.note              = p.note
            mine.opens_at          = p.opens_at
            mine.closes_at         = p.closes_at
            mine.break_start       = p.break_start
            mine.break_end         = p.break_end
            mine.troublesome       = p.troublesome
            mine.collected_by      = p.collected_by
            updated += 1
            continue

        if key in locked_keys:
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
            door_key=key,
            # ADR-426 — who may later correct this row.
            device_id=body.device_id,
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

    if accepted or updated:
        write_audit(
            db,
            action_type="collection.submit",
            target_table="collected_address_profiles",
            target_id=str(tok.id),
            company_id=str(tok.company_id),
            # No actor_id: there is no account behind this, and inventing one
            # would make the audit log claim something untrue.
            detail={"label": tok.label, "accepted": accepted,
                    "duplicate": duplicate, "updated": updated},
        )
    db.commit()

    # D4 — receipt only. No ids, no echo of stored content.
    return CollectionSubmitOut(
        accepted=accepted,
        duplicate=duplicate,
        duplicate_addresses=duplicate_addresses,
        updated=updated,
    )


@router.post("/check", response_model=CollectionCheckOut, status_code=status.HTTP_200_OK)
@limiter.limit("60/minute")
def check_address(
    request: Request,
    body: CollectionCheckIn,
    db: Session = Depends(get_db),
    # ADR-423: anonymous-tolerant. NOT get_caller_employee_optional — that one
    # is optional about the employee ROW but still 401s on a missing
    # Authorization header, which made every public collection path demand a
    # login.
    caller: Employee | None = Depends(get_caller_employee_anonymous),
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
        db.query(CollectedAddressProfile.collected_on,
                 CollectedAddressProfile.device_id)
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

    # ADR-426. A door this device already submitted is not locked TO THIS
    # DEVICE: a resubmission updates that row rather than adding a third
    # observation. Without this the form cleared the field on a door the
    # collector had profiled themselves, which is the worst possible moment to
    # discard their typing.
    mine = body.device_id is not None and any(
        d == body.device_id for _, d in rows
    )
    return CollectionCheckOut(
        known=True,
        collected_on=rows[0][0],
        count=len(rows),
        locked=len(rows) >= VERIFICATION_LIMIT and not mine,
        mine=mine,
    )


@router.post("/submit-day", response_model=WalkerDaySubmitOut,
             status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("30/minute")
def submit_walker_days(
    request: Request,
    body: WalkerDaySubmitIn,
    db: Session = Depends(get_db),
    # ADR-423: anonymous-tolerant. NOT get_caller_employee_optional — that one
    # is optional about the employee ROW but still 401s on a missing
    # Authorization header, which made every public collection path demand a
    # login.
    caller: Employee | None = Depends(get_caller_employee_anonymous),
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
    current_user: dict = Depends(get_current_user),
    caller: Employee | None = Depends(get_caller_employee_optional),
):
    """The kill switch. Revoking stops submissions immediately.

    ADR-424. Same two principals as create_token, and for the same reason: a
    super admin has no Employee row, so `get_caller_employee` 403'd them on
    their own campaigns. ADR-423 fixed that on create and missed its sibling —
    the platform owner could issue an open campaign and then not revoke it.

    Scoping comes from `_scope_reads`, so a company admin still cannot revoke
    another tenant's link and cannot touch an open one (its company_id is NULL,
    which `=` never matches).
    """
    tok = (
        _scope_reads(db.query(CollectionToken), CollectionToken, current_user, caller)
        .filter(CollectionToken.id == token_id)
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
        actor_id=str(caller.id) if caller else None,
        company_id=str(tok.company_id) if tok.company_id else None,
        detail={"label": tok.label},
    )
    db.commit()
    return {"revoked": True}


@router.post("/leaderboard", status_code=status.HTTP_200_OK)
@limiter.limit("60/minute")
def campaign_leaderboard(
    request: Request,
    body: LeaderboardIn,
    db: Session = Depends(get_db),
    caller: Employee | None = Depends(get_caller_employee_anonymous),
) -> list[LeaderboardEntryOut]:
    """A campaign's top collectors (ADR-427).

    ANOTHER READ ON THE PUBLIC PATH, and narrower than the duplicate check:
    it returns handles and counts, never an address. ADR-415 D4 forbade reads
    because collected ADDRESSES are customer data; a count of submissions by
    self-chosen handle is not.

    The handle is what makes this safe. The field asks for an alias and says
    why, so what appears here is "Sparky — 14", not a coworker's legal name.
    A collector who types their real name has disclosed it to people who
    already hold the same campaign link.

    Scoped by token, so a leaderboard shows one campaign and cannot be used to
    enumerate others. Company campaigns require a login like every other path
    on this endpoint.

    Rows with no handle are omitted rather than bucketed as "Anonymous": they
    are not a competitor, and a large unnamed row at the top would read as one
    person dominating.
    """
    tok = _resolve_token(db, body.token)
    _authorise_scope(tok, caller)

    rows = (
        db.query(
            CollectedAddressProfile.collected_by,
            sa_func.count(CollectedAddressProfile.id).label("n"),
        )
        .filter(
            CollectedAddressProfile.token_id == tok.id,
            CollectedAddressProfile.collected_by.isnot(None),
            CollectedAddressProfile.collected_by != "",
        )
        .group_by(CollectedAddressProfile.collected_by)
        .order_by(sa_func.count(CollectedAddressProfile.id).desc())
        # Top three, plus enough to break a tie sensibly at the boundary.
        .limit(TOP_COLLECTORS)
        .all()
    )
    return [LeaderboardEntryOut(handle=h, count=n) for h, n in rows]


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
        # ADR-424: a revoked campaign shows no link. The string still exists in
        # the row, but it no longer works — displaying it invites someone to
        # send a link that will 404 for whoever receives it.
        if t.revoked_at is not None:
            row.token = None
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


@router.delete("/profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/minute")
def delete_collected_profile(
    request: Request,
    profile_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    caller: Employee | None = Depends(get_caller_employee_optional),
):
    """Remove one collected observation. ADR-431.

    DELETE AND NOT EDIT, deliberately. This table records what collectors
    actually submitted, which is the only reason a conclusion drawn from it is
    worth anything. An admin edit would make a row a claim about two people
    while still reading as one, and an observation retyped by someone who was
    not at the door is indistinguishable afterwards from one that was. Removing
    a row asserts nothing on the collector's behalf, so it carries no such
    ambiguity. A wrong VALUE is fixed by the collector resubmitting (ADR-426).

    HARD delete, not a `deleted_at` flag. ADR-415 calls this table a quarantine
    holding customer delivery addresses that are meant to be stripped later; a
    soft-deleted address is still in the table, still in backups, and one
    forgotten WHERE clause from an export.

    The audit detail therefore carries the WHOLE row rather than just its id.
    This is the only surviving record of the observation, and an audit entry
    reading "profile 8f3a deleted" answers nothing later.
    """
    row = (
        _scope_reads(db.query(CollectedAddressProfile), CollectedAddressProfile,
                     current_user, caller)
        .filter(CollectedAddressProfile.id == profile_id)
        .first()
    )
    # 404 whether it never existed or belongs to another tenant: _scope_reads
    # has already narrowed the query, so a wrong-tenant id is simply not found.
    # Distinguishing the two would confirm the row exists.
    if row is None:
        raise HTTPException(status_code=404, detail="Collected address not found.")

    write_audit(
        db,
        action_type="collection.profile.delete",
        target_table="collected_address_profiles",
        target_id=str(row.id),
        actor_id=str(caller.id) if caller else None,
        company_id=str(row.company_id) if row.company_id else None,
        detail={
            "address": row.address,
            "building_type": row.building_type,
            "workloads": list(row.workloads or []),
            "collected_by": row.collected_by,
            "collected_on": row.collected_on.isoformat() if row.collected_on else None,
            "token_id": str(row.token_id),
        },
    )
    # Audit BEFORE the delete: write_audit reads the row's own fields, and
    # they are gone after db.delete() flushes.
    db.delete(row)
    db.commit()
    return None


@router.delete("/profiles", status_code=status.HTTP_200_OK)
@limiter.limit("10/minute")
def delete_profiles_by_device(
    request: Request,
    token_id: str = Query(..., description="Campaign the rows belong to."),
    device_id: str = Query(..., min_length=8, max_length=64),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    caller: Employee | None = Depends(get_caller_employee_optional),
):
    """Remove every row one device submitted to one campaign. ADR-435.

    THE CLEANUP PATH FOR AN ABUSED LINK. The collection link is public by
    design, so the realistic incident is a flood of junk rows, and ADR-431's
    per-row delete is the wrong tool for 500 of them — it is not a rate problem,
    it is that the admin would be clicking delete until the campaign ends.

    Scoped to ONE device AND ONE campaign, never "delete everything matching a
    filter". A spammer submits from one device; a mistake here that took a
    filter would let a stray click erase a whole campaign of real field work,
    and ADR-431 D2 made this a hard delete precisely because there is nothing
    to restore from.

    Returns the count rather than 204: "deleted 412 rows" is what the admin
    needs to know, and a silent success after a destructive bulk action is how
    someone runs it twice.
    """
    rows = (
        _scope_reads(db.query(CollectedAddressProfile), CollectedAddressProfile,
                     current_user, caller)
        .filter(
            CollectedAddressProfile.token_id == token_id,
            CollectedAddressProfile.device_id == device_id,
        )
        .all()
    )
    if not rows:
        # 404 rather than "deleted 0": an admin who mistyped a device id should
        # not be told the operation succeeded.
        raise HTTPException(status_code=404, detail="No rows for that device.")

    # ONE audit entry for the batch, carrying the addresses. ADR-431 D3 wants a
    # hard delete to leave a record of what it destroyed; 500 separate entries
    # would bury the incident rather than document it.
    write_audit(
        db,
        action_type="collection.profile.bulk_delete",
        target_table="collected_address_profiles",
        target_id=str(token_id),
        actor_id=str(caller.id) if caller else None,
        company_id=str(rows[0].company_id) if rows[0].company_id else None,
        detail={
            "device_id": device_id,
            "count": len(rows),
            # Capped: an audit detail is not a backup, and a 10k-row flood
            # would otherwise write a JSONB blob nobody can read.
            "addresses": [r.address for r in rows[:100]],
            "truncated": len(rows) > 100,
        },
    )
    for r in rows:
        db.delete(r)
    db.commit()
    return {"deleted": len(rows)}


def _campaign_for_cleanup(db, token_id: str, current_user, caller) -> CollectionToken:
    """The campaign, if this caller may destroy its data (ADR-437 D2).

    The revoke gate is the point: purging a LIVE campaign races the collectors
    still using it, and submissions landing seconds after the purge become
    indistinguishable from data meant to survive. A silent partial wipe is worse
    than either outcome, so an active link is refused with the remedy in the
    message rather than being quietly allowed.
    """
    tok = (
        _scope_reads(db.query(CollectionToken), CollectionToken, current_user, caller)
        .filter(CollectionToken.id == token_id)
        .first()
    )
    if tok is None:
        raise HTTPException(status_code=404, detail="Collection link not found.")
    if tok.revoked_at is None:
        raise HTTPException(
            status_code=409,
            detail="Revoke this link before purging or deleting its data.",
        )
    return tok


def _count_campaign_rows(db, token_id) -> tuple[int, int]:
    """How much is about to be destroyed.

    Counted BEFORE the delete and never after: both child tables carry
    ondelete="CASCADE" on token_id, so the rows are gone at the DATABASE level
    without the ORM ever seeing them. A count taken afterwards is always zero,
    and an audit entry that cannot say what it destroyed is not an audit entry.
    """
    profiles = (
        db.query(sa_func.count(CollectedAddressProfile.id))
        .filter(CollectedAddressProfile.token_id == token_id)
        .scalar()
    ) or 0
    days = (
        db.query(sa_func.count(CollectedWalkerDay.id))
        .filter(CollectedWalkerDay.token_id == token_id)
        .scalar()
    ) or 0
    return profiles, days


@router.delete("/tokens/{token_id}/data", status_code=status.HTTP_200_OK)
@limiter.limit("5/minute")
def purge_campaign_data(
    request: Request,
    token_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    caller: Employee | None = Depends(get_caller_employee_optional),
):
    """Empty a campaign, keeping the campaign itself. ADR-437 D1.

    THE CLEANUP AT THE END OF A MIGRATION. The exports are the migration path
    and had nothing at the end of them: a finished campaign's rows sat in
    `collected_address_profiles` — customer delivery addresses that ADR-415
    calls a quarantine to be stripped later — with no mechanism for "later".

    Keeps the token row deliberately. After a migration the rows are a
    liability and the RECORD that the survey ran (its label, dates and cap) is
    the useful residue. Deleting both would mean freeing space also erases the
    evidence a campaign existed, which is the wrong trade for the common case;
    `delete_campaign` below is for when that IS what you want.

    The audit carries COUNTS, not addresses (ADR-437 D3). ADR-431 D3 put row
    content in the audit for a single delete because one observation is
    recoverable information; 400 addresses in a JSONB blob is a copy of the
    quarantine inside the audit log, which defeats the purge.
    """
    tok = _campaign_for_cleanup(db, token_id, current_user, caller)
    profiles, days = _count_campaign_rows(db, tok.id)
    if profiles == 0 and days == 0:
        raise HTTPException(status_code=409, detail="This campaign holds no data.")

    write_audit(
        db,
        action_type="collection.campaign.purge",
        target_table="collection_tokens",
        target_id=str(tok.id),
        actor_id=str(caller.id) if caller else None,
        company_id=str(tok.company_id) if tok.company_id else None,
        detail={"label": tok.label, "profiles": profiles, "walker_days": days},
    )
    # Bulk DELETEs rather than loading every row to delete it one at a time —
    # a 500-row campaign should not become 500 ORM objects to destroy them.
    db.query(CollectedAddressProfile).filter(
        CollectedAddressProfile.token_id == tok.id
    ).delete(synchronize_session=False)
    db.query(CollectedWalkerDay).filter(
        CollectedWalkerDay.token_id == tok.id
    ).delete(synchronize_session=False)
    db.commit()
    return {"profiles": profiles, "walker_days": days}


@router.delete("/tokens/{token_id}", status_code=status.HTTP_200_OK)
@limiter.limit("5/minute")
def delete_campaign(
    request: Request,
    token_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    caller: Employee | None = Depends(get_caller_employee_optional),
):
    """Remove a campaign and everything collected under it. ADR-437 D1.

    For a campaign that should not exist — a test, a mistake, a duplicate link
    — rather than one whose data has been migrated out. That is `purge`.

    THE CASCADE IS WHY THIS MUST COUNT FIRST. Both child tables declare
    ondelete="CASCADE" on token_id and there are no ORM relationships, so
    deleting the token takes every profile and walker-day with it at the
    database level, invisibly to the application. The cascade is correct;
    issuing it blind is not, so the rows are counted and audited before the
    delete rather than discovered missing after it.
    """
    tok = _campaign_for_cleanup(db, token_id, current_user, caller)
    profiles, days = _count_campaign_rows(db, tok.id)

    write_audit(
        db,
        action_type="collection.campaign.delete",
        target_table="collection_tokens",
        target_id=str(tok.id),
        actor_id=str(caller.id) if caller else None,
        company_id=str(tok.company_id) if tok.company_id else None,
        detail={
            "label": tok.label,
            "scope": tok.scope,
            "profiles": profiles,
            "walker_days": days,
        },
    )
    # The FK cascade removes the children. Counted above, so the audit records
    # what this destroyed even though the ORM never loads the rows.
    db.delete(tok)
    db.commit()
    return {"deleted": True, "profiles": profiles, "walker_days": days}


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

    # ADR-430. How many observations each door on this PAGE has across the whole
    # campaign. One grouped query over the page's keys, not a count per row, and
    # not a count of the page itself — a pair split across a page boundary would
    # otherwise read as two single observations.
    keys = {r.door_key for r in rows if r.door_key}
    counts: dict[str, int] = {}
    if keys:
        counts = dict(
            db.query(
                CollectedAddressProfile.door_key,
                sa_func.count(CollectedAddressProfile.id),
            )
            .filter(
                CollectedAddressProfile.token_id.in_({r.token_id for r in rows}),
                CollectedAddressProfile.door_key.in_(keys),
            )
            .group_by(CollectedAddressProfile.door_key)
            .all()
        )

    out = []
    for r in rows:
        item = CollectedProfileOut.model_validate(r)
        item.observations = counts.get(r.door_key, 1)
        item.closed = item.observations >= VERIFICATION_LIMIT
        out.append(item)
    return out

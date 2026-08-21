"""Unregistered package intake (ADR-246).

  POST /packages/intake/preview   field roles — dry run, writes nothing
  POST /packages/intake           field roles — walker self-add, own route
  POST /packages/intake/assign    dispatch+   — assign to any route
  GET  /packages/intake/field-added  dispatch+ — oversight feed

A walker opens a tote and finds a package that was never registered: not on any
manifest, not on any route. Until now there was no way to record it, so the
delivery either went untracked or the package came back.

The decision tree lives in services/package_intake.py; this module is the HTTP
edge — gates, request shape, transaction boundary, and audit.
"""
from datetime import date
from typing import Optional
from uuid import UUID

from fastapi import (
    APIRouter, Depends, File, HTTPException, Query, UploadFile, status,
)
from sqlalchemy.orm import Session

from app.api.deps import RoleChecker, get_caller_employee
from app.database import get_db
from app.models.audit_log import AuditLog
from app.models.employee import Employee
from app.models.walker_route import Route
from app.schemas.package_intake import (
    DispatchAssignRequest, FieldAddedPackage, FieldAddedResponse,
    IntakeAssessmentOut, IntakeCandidate, LabelReadResponse,
    PackageIntakeRequest, PackageIntakeResponse,
)
from app.services.audit import write_audit
from app.services.local_date import company_today
from app.services.package_intake import (
    IntakeAssessment, attach_to_route, check_duplicate, check_zone,
    create_foreign_removal, find_best_fit, resolve_address,
)

router = APIRouter(prefix="/packages/intake", tags=["packages"])

# The walker holding the package is the one who records it. Every field role
# can, because any of them can be the one who opens the tote — a trainer
# covering a route finds packages exactly as a walker does.
_allow_field = RoleChecker(
    ["walker", "trainer", "trainee", "driver", "dispatch", "management", "admin"]
)
# Assigning to *someone else's* route is a dispatch decision, not a field one.
_allow_dispatch = RoleChecker(["dispatch", "management", "admin"])

_ACTION = "package.field_added"


def _company_today(db: Session, company_id: UUID) -> date:
    """Today in the company's timezone.

    A UTC date rolls over mid-evening for US operators, which would file an
    evening find against tomorrow's routes and make it invisible on today's
    oversight feed.
    """
    return company_today(db, company_id)


def _cand(c) -> Optional[IntakeCandidate]:
    if c is None:
        return None
    return IntakeCandidate(
        route_id=c.route_id, route_number=c.route_number,
        walker_name=c.walker_name, status=c.status,
        can_accept=c.can_accept, match=c.match,
        distance=c.distance,
        is_adders_route=c.is_adders_route,
    )


def _assessment_out(a: IntakeAssessment) -> IntakeAssessmentOut:
    return IntakeAssessmentOut(
        in_zone=a.zone.in_zone,
        decidable=a.zone.decidable,
        zone_reason=a.zone.reason,
        best_fit=_cand(a.best_fit),
        adders_route=_cand(a.adders_route),
        candidates=[_cand(c) for c in a.candidates],
        absorbed_reason=a.absorbed_reason,
        routes_exist=a.routes_exist,
    )


def _resolve(
    db: Session,
    caller: Employee,
    payload: PackageIntakeRequest,
    *,
    target_route_id: Optional[UUID] = None,
    adder_id: Optional[UUID] = None,
    restrict_to_own_route: bool = False,
    commit: bool = True,
) -> PackageIntakeResponse:
    """The shared decision + write path for both entry points.

    Walker self-add and dispatch assign differ only in who may be the executor
    of the receiving route and whether a route can be named explicitly. The
    ownership tree, the duplicate guard and the audit are identical, so they are
    written once here rather than twice.
    """
    cid = caller.company_id
    tba = payload.tba.strip().upper()
    # Always today, never a client-supplied date (ADR-260). The package is
    # physically in someone's hand right now — there is no coherent meaning to
    # filing a find against yesterday or tomorrow, and accepting a date let a
    # caller write onto a closed day's routes.
    when = _company_today(db, cid)

    # ── 1. already known? Name the holder rather than refusing blankly. ──
    dup = check_duplicate(db, cid, tba, when)
    if dup.is_duplicate:
        return PackageIntakeResponse(
            outcome="duplicate", tba=tba,
            existing_holder=dup.holder_name,
            existing_route_number=dup.route_number,
            route_id=dup.route_id,
            reason=dup.basis,
        )

    # ── 2. work out where this actually is (ADR-259). ──
    # Clients send the text off the label and nothing more; the server derives
    # coords, the canonical address and the block key. Anything the caller DID
    # send wins, so a corrected value is never silently overridden.
    resolved = resolve_address(
        db, cid, payload.normalised_address, tba,
        lat=payload.lat, lng=payload.lng,
        block_key=payload.block_key,
        normalised_address=payload.normalised_address,
    )

    # ── 3. ours to deliver? Ownership is decided BEFORE routing. ──
    zone = check_zone(db, cid, lat=resolved.lat, lng=resolved.lng)
    if zone.decidable and not zone.in_zone:
        # Out-of-zone is terminal: the package is not ours, so no route is
        # offered and the custody chain takes it (ADR-176).
        #
        # A dry run must NOT build the removal. create_foreign_removal + the
        # audit row are a real write that only a rollback was undoing, and a
        # preview that constructs a custody record is one missing `finally`
        # away from persisting one (ADR-259).
        if not commit:
            return PackageIntakeResponse(
                outcome="removal", tba=tba, reason="out_of_zone",
            )
        removal = create_foreign_removal(
            db, company_id=cid, tba=tba, removal_date=when,
            removed_by=caller.id, removed_by_name=caller.name,
        )
        db.flush()
        write_audit(
            db, company_id=str(cid), actor_id=str(caller.id),
            action_type=_ACTION, target_table="package_removals",
            target_id=str(removal.id),
            detail={"tba": tba, "outcome": "removal", "reason": "out_of_zone",
                    "route_date": when.isoformat()},
        )
        db.commit()
        return PackageIntakeResponse(
            outcome="removal", tba=tba, removal_id=removal.id,
            reason="out_of_zone",
        )

    assessment = find_best_fit(
        db, cid, when, resolved.block_key, resolved.normalised_address,
        adder_employee_id=adder_id,
        segment_id=resolved.segment_id,
    )
    assessment.zone = zone
    out = _assessment_out(assessment)

    # Undecidable ownership escalates rather than guessing. Without coords we
    # cannot prove the package is foreign, and declaring it so would strand a
    # deliverable package (ADR-246).
    #
    # The ranked candidates ride along: the block key is derived offline, so a
    # geocode failure still knows which routes cover the block. Dispatch gets
    # something to act on instead of "could not place this address" (ADR-259).
    if not zone.decidable:
        return PackageIntakeResponse(
            outcome="needs_dispatch", tba=tba,
            reason=zone.reason, assessment=out,
        )

    # ── 3. which route? ──
    target: Optional[UUID] = target_route_id
    if target is None:
        chosen = assessment.best_fit
        if restrict_to_own_route:
            # A walker's self-add lands on their own route unless they have
            # explicitly accepted the better-fit warning. The package is
            # already in their tote; the best fit is advice, not a gate.
            own = assessment.adders_route
            if own is not None and not payload.accept_override:
                chosen = own
        target = chosen.route_id if chosen else None

    if target is None:
        # Routes exist but none is near enough or able to take it — a dispatch
        # decision, and the only way to reach here in practice.
        #
        # There is deliberately no "the day is not sorted yet" branch. A
        # package found in the field is found by a walker who is ALREADY out,
        # which means the manifest was enriched, the sort ran and routes were
        # created hours earlier. A pre-sort find at the station is a different
        # workflow: it sorts into a TruckZone and enters that truck's manifest,
        # where the normal sort picks it up (ADR-260).
        return PackageIntakeResponse(
            outcome="needs_dispatch", tba=tba,
            reason=assessment.absorbed_reason or "no_accepting_route",
            assessment=out,
        )

    route = (
        db.query(Route)
        .filter(Route.id == target, Route.company_id == cid)
        .first()
    )
    if route is None:
        raise HTTPException(status_code=404, detail="Route not found")

    if restrict_to_own_route and route.executor_id != caller.id:
        # Field staff may only add to a route they are executing. Without this
        # the field gate would let any walker write to any route.
        raise HTTPException(
            status_code=403,
            detail="You can only add a package to your own route",
        )

    executor_name = None
    if route.executor_id:
        ex = (
            db.query(Employee)
            .filter(Employee.id == route.executor_id, Employee.company_id == cid)
            .first()
        )
        executor_name = ex.name if ex else None

    stop = attach_to_route(
        db, route, tba=tba,
        # The resolved values, not the raw payload: the stop should carry the
        # canonical address and derived block key, matching what enrichment
        # writes for a manifested package (ADR-259).
        block_key=resolved.block_key,
        normalised_address=resolved.normalised_address,
        company_id=cid,
        executor_id=route.executor_id,
        executor_name=executor_name,
        recorded_by=caller.id,
        recorded_by_name=caller.name,
    )
    db.flush()
    write_audit(
        db, company_id=str(cid), actor_id=str(caller.id),
        action_type=_ACTION, target_table="routes", target_id=str(route.id),
        detail={
            "tba": tba, "outcome": "added",
            "route_number": route.route_number,
            "route_date": when.isoformat(),
            "walker_name": executor_name,
            "stop_id": str(stop.id) if stop is not None else None,
            "absorbed_reason": assessment.absorbed_reason,
        },
    )
    if commit:
        db.commit()

    return PackageIntakeResponse(
        outcome="added", tba=tba,
        route_id=route.id, route_number=route.route_number,
        walker_name=executor_name,
        stop_id=stop.id if stop is not None else None,
        reason=assessment.absorbed_reason,
        assessment=out,
    )


@router.post("/preview", response_model=PackageIntakeResponse)
def preview_intake(
    payload: PackageIntakeRequest,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_field),
):
    """Dry run: what would happen to this package, writing nothing.

    The walker sees the destination and any better-fit warning before
    committing. Rolls back rather than committing, so a preview can never leave
    a partial write behind.
    """
    try:
        return _resolve(
            db, caller, payload,
            adder_id=caller.id, restrict_to_own_route=True, commit=False,
        )
    finally:
        db.rollback()


@router.post("", response_model=PackageIntakeResponse,
             status_code=status.HTTP_201_CREATED)
def walker_self_add(
    payload: PackageIntakeRequest,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_field),
):
    """A walker records a package found in their own tote.

    Commits immediately — no review queue. The walker is standing in front of
    the package, and a queue would either block a delivery that costs nothing or
    be rubber-stamped. Dispatch gets visibility instead, via /field-added.
    """
    return _resolve(
        db, caller, payload,
        adder_id=caller.id, restrict_to_own_route=True,
    )


@router.post("/assign", response_model=PackageIntakeResponse,
             status_code=status.HTTP_201_CREATED)
def dispatch_assign(
    payload: DispatchAssignRequest,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_dispatch),
):
    """Dispatch places a package on a route — named, or best-fit.

    The fallback for a walker reporting by radio rather than entering it, and
    the resolution path for a geocode failure that escalated here.

    Attribution splits per ADR-244: the route's executor owns the resulting
    stop, and the dispatcher is `recorded_by`.
    """
    return _resolve(db, caller, payload, target_route_id=payload.route_id)


@router.post("/assign/preview", response_model=PackageIntakeResponse)
def dispatch_assign_preview(
    payload: DispatchAssignRequest,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_dispatch),
):
    """Dry run of /assign: what would happen, writing nothing.

    Dispatch cannot use /preview — that path passes `restrict_to_own_route=True`
    and a dispatcher has no route of their own, so it can never return the
    ranked candidates a dispatcher needs to choose from.

    A separate endpoint rather than a `dry_run` flag on /assign: that route is
    201 CREATED and creates a stop, and a request that writes nothing must not
    share a status code with one that does.

    Runs the SAME `_resolve` as the real assign, so `assessment.candidates` is
    exactly the ranking the write would use — a preview that could disagree
    with the commit would be worse than none.

    Rolls back in `finally` so a preview can never leave a partial write.
    """
    try:
        return _resolve(
            db, caller, payload,
            target_route_id=payload.route_id,
            commit=False,
        )
    finally:
        db.rollback()


@router.get("/field-added", response_model=FieldAddedResponse)
def field_added_packages(
    route_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_dispatch),
):
    """What got added to today's routes, and by whom.

    ### Why this exists rather than pointing dispatch at the audit log

    `write_audit` already records every intake, but `GET /audit` is gated
    `["management", "admin"]` — **dispatch cannot read it**. Sending oversight
    there would satisfy the requirement on paper and not in practice (ADR-246).

    So this reads the same audit rows under a dispatch-readable gate, filtered
    to one action type and one day. Dispatch's question is "what got added to my
    routes today", not "what happened", so it is shaped as a day's feed rather
    than a raw event stream.
    """
    cid = caller.company_id
    when = route_date or _company_today(db, cid)

    rows = (
        db.query(AuditLog, Employee.name)
        .outerjoin(Employee, Employee.id == AuditLog.actor_id)
        .filter(
            AuditLog.company_id == cid,
            AuditLog.action_type == _ACTION,
        )
        .order_by(AuditLog.created_at.desc())
        .limit(500)
        .all()
    )

    packages: list[FieldAddedPackage] = []
    for row, actor_name in rows:
        # write_audit maps `detail=` onto `after`, so after_snapshot IS the
        # detail dict — there is no nested "detail" key to unwrap (verified
        # against services/audit.py).
        detail = row.after_snapshot or {}
        if not isinstance(detail, dict):
            continue
        # The audit row carries the operational date; created_at is when it was
        # recorded, which differs for a package entered after midnight.
        if detail.get("route_date") != when.isoformat():
            continue
        packages.append(FieldAddedPackage(
            tba=detail.get("tba", ""),
            route_id=UUID(row.target_id) if row.target_table == "routes" else None,
            route_number=detail.get("route_number"),
            walker_name=detail.get("walker_name"),
            added_by_name=actor_name,
            added_at=row.created_at,
            outcome=detail.get("outcome", "added"),
        ))

    return FieldAddedResponse(
        route_date=when, total=len(packages), packages=packages,
    )


# A phone photo is ~1-5 MB. 10 covers a high-res capture without letting an
# unbounded upload reach Textract, which bills per page.
_MAX_LABEL_BYTES = 10 * 1024 * 1024
# Deliberately NOT widened to include HEIC. Textract's DetectDocumentText reads
# JPEG, PNG, PDF and TIFF only, so accepting HEIC here would move the failure
# from a clear 415 to an opaque AWS error. The web client re-encodes to JPEG in
# the browser (see toServerReadableImage), which needs no server dependency;
# mobile never sends HEIC because react-native-image-picker converts on capture.
_ALLOWED_LABEL_TYPES = {"image/jpeg", "image/jpg", "image/png", "application/pdf"}


@router.post("/read-label", response_model=LabelReadResponse)
async def read_label(
    file: UploadFile = File(...),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_field),
):
    """OCR a label photo into a TBA and an address — a SUGGESTION, not a write.

    Nothing is persisted. The walker confirms both fields, and manual entry is
    always available: a scan that fails must never block someone standing in
    front of the package (ADR-246). That is why a failed read returns 200 with
    `needs_manual_entry=true` rather than an error status — an error would make
    the client treat a normal outcome as a fault.

    Textract is only reached through LabelIngestor's injectable client, so this
    endpoint is the only place the real AWS call is made.
    """
    from app.services.label_ingestor import LabelIngestor

    if file.content_type not in _ALLOWED_LABEL_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                "Upload a JPEG, PNG or PDF of the label. HEIC (the iPhone "
                "default) is not readable by the OCR service — the web client "
                "converts it before upload; a direct API caller must convert it."
            ),
        )

    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(payload) > _MAX_LABEL_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Label image is too large (max 10 MB)",
        )

    try:
        read = LabelIngestor(payload).read()
    except Exception:
        # OCR is best-effort. Textract being down, throttled, or handed an
        # unreadable photo all mean the same thing to the walker: type it in.
        # The exception text is deliberately not surfaced (Dimension 6).
        return LabelReadResponse(
            needs_manual_entry=True, warnings=["ocr_unavailable"],
        )

    return LabelReadResponse(
        tba=read.tba,
        address_line=read.address_line,
        confidence=read.confidence,
        needs_manual_entry=read.needs_manual_entry,
        lines=read.lines,
        warnings=read.warnings,
    )

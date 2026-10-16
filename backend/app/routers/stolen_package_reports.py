"""Stolen-package reports: filed by the DA, signed by the truck's driver or captain (ADR-512).

One theft produces one `Incident` and up to two `StolenPackageReport` versions:

    da        filed by the DA; filing and every later save is the DA's signature
    reviewer  "Verified by": the DA's version, reviewed, edited and signed by the
              truck's driver or captain that day, attributed to the signer. The
              first to sign wins; a second first-sign is a 409.

States (derived, never stored; ADR-512 D12, D18):

    submitted              da only
    verified               reviewer signed after the DA's last save
    needs_reverification   the DA saved after the reviewer signed: the SAME
                           verifier is asked again and may then edit their copy
    accepted               Incident.resolved; nobody edits. Management/admin may
                           reopen with a reason, within 7 days, before the
                           60-day clearing (D20)

Dispatch, management and admin see both, the field-by-field mismatches (computed
here at read time, never stored), and the reviewer's private comments. The
copy-out text is built here so web and mobile produce identical output.
"""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import RoleChecker, get_caller_employee
from app.database import get_db
from app.models.anchor_point import AnchorPoint
from app.models.assignment_member import AssignmentMember
from app.models.company import Company
from app.models.employee import Employee
from app.models.incident import Incident
from app.models.stolen_package_report import ReportVersion, StolenPackageReport
from app.models.truck import Truck
from app.models.truck_assignment import TruckAssignment
from app.routers.incidents import _notify_management, _resolve_assignment
from app.routers.registration import ROLE_TO_COGNITO_GROUP
from app.services.audit import write_audit
from app.services.local_date import company_datetime, company_today, company_tz
from app.services.notify import write_notification

router = APIRouter(prefix="/incidents/stolen-package", tags=["incidents"])

#: Every tenant role, from the canonical map, not a hand-typed list. The generic
#: incident endpoint's list omits captain, field_supervisor and driver_trainee,
#: the ADR-494 stale-list shape; a captain is a reviewer here.
allow_any_role = RoleChecker(sorted(ROLE_TO_COGNITO_GROUP))
OVERSIGHT = ("dispatch", "management", "admin")
#: Who may FILE: the person the report names as the DA, so a field role. An
#: office caller filing would put their own name in "DA Name" (audit D2). Filing
#: on a DA's behalf is a different feature, not built.
allow_field_filer = RoleChecker(sorted(set(ROLE_TO_COGNITO_GROUP) - set(OVERSIGHT)))
#: Roles that may review and sign (owner's amendment, 2026-10-14).
REVIEWER_ROLES = ("driver", "captain")
#: How far back a reviewer's "to sign" list looks. A report is filed the day
#: of the theft; two weeks covers a reviewer off for a week.
TO_SIGN_DAYS = 14
#: Field staff read an accepted report for this many days after acceptance (D16).
FIELD_VIEW_DAYS_AFTER_ACCEPT = 7
#: An accepted report can be reopened for this many days after acceptance (D20).
REOPEN_DAYS = 7
allow_oversight = RoleChecker(list(OVERSIGHT))
#: Only management reopens; admin included because admins have full access (D15).
allow_reopen = RoleChecker(["management", "admin"])

TBA_RE = re.compile(r"^TBA\d{12}$")

#: The fields the two versions are compared on, in the report's own order.
COMPARED = (
    "incident_date", "incident_time", "incident_address", "anchor_point_address",
    "lmet_called", "lmet_case_number", "bike_locks_used", "cart_cover_used",
    "totes_stolen", "cart_stolen", "packages_stolen", "tbas", "summary",
)


class StolenPackageIn(BaseModel):
    """Dimension 9: every field concrete and bounded; unknown keys are a 422."""

    incident_date: date
    incident_time: Optional[time] = None
    incident_address: str = Field(min_length=1, max_length=200)
    anchor_point_address: Optional[str] = Field(default=None, max_length=255)
    lmet_called: bool = False
    lmet_case_number: Optional[str] = Field(default=None, max_length=64)
    bike_locks_used: bool = True
    cart_cover_used: bool = True
    totes_stolen: int = Field(default=0, ge=0, le=50)
    cart_stolen: bool = False
    packages_stolen: int = Field(ge=0, le=500)
    tbas: list[str] = Field(default_factory=list, max_length=50)
    summary: str = Field(min_length=1, max_length=2000)

    model_config = ConfigDict(extra="forbid")

    @field_validator("tbas")
    @classmethod
    def _tbas(cls, v: list[str]) -> list[str]:
        out: list[str] = []
        for raw in v:
            t = raw.strip().upper()
            if not TBA_RE.match(t):
                raise ValueError(f"not a TBA: {raw[:20]!r} (expected TBA followed by 12 digits)")
            if t not in out:
                out.append(t)
        return out


class SignIn(StolenPackageIn):
    """The reviewer's version: every field, plus comments only oversight sees."""

    reviewer_comments: Optional[str] = Field(default=None, max_length=2000)


class ReopenIn(BaseModel):
    """Why management is reopening: shown to the authors and kept in the audit."""

    reason: str = Field(min_length=3, max_length=300)

    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------- helpers ----

def _aware(v: Optional[datetime]) -> Optional[datetime]:
    """A naive value is UTC (the columns are timestamptz; some drivers drop the zone)."""
    if v is None:
        return None
    return v if v.tzinfo is not None else v.replace(tzinfo=timezone.utc)


def _signed(r: Optional[StolenPackageReport]) -> Optional[datetime]:
    """When this version was last signed. A DA row filed before D18 has no
    signed_at; its filing time is its signature."""
    if r is None:
        return None
    return _aware(r.signed_at or r.created_at)


def _state(inc: Incident, versions: dict) -> str:
    da, rv = versions.get(ReportVersion.DA), versions.get(ReportVersion.REVIEWER)
    if inc.resolved:
        return "accepted"
    if rv is None:
        return "submitted"
    if da is not None and _signed(da) > _signed(rv):
        return "needs_reverification"
    return "verified"


def _changed(r: StolenPackageReport, body: StolenPackageIn) -> list[str]:
    """Names of the fields a save changes. Names only: values hold customer data."""
    out = []
    for f in COMPARED:
        old, new = getattr(r, f), getattr(body, f)
        if f == "tbas":
            old, new = sorted(old or []), sorted(new or [])
        if old != new:
            out.append(f)
    return out


def _within(at: Optional[datetime], days: int) -> bool:
    return at is not None and _aware(at) >= datetime.now(timezone.utc) - timedelta(days=days)


def _dsp(db: Session, company_id) -> Optional[str]:
    c = db.query(Company.amazon_dsp_code, Company.amazon_dsp_name).filter(Company.id == company_id).first()
    return (c.amazon_dsp_code or c.amazon_dsp_name) if c else None


def _anchor_at(db: Session, company_id, truck_id, d: date, t: Optional[time]) -> Optional[str]:
    """The truck's anchor point active at the incident time (ADR-512 D4).

    A truck can relocate during the day, so "the" anchor point is the most
    recent one submitted at or before the incident; without a time, or if every
    AP is later, the day's latest.
    """
    if truck_id is None:
        return None
    aps = (
        db.query(AnchorPoint)
        .filter(AnchorPoint.company_id == company_id, AnchorPoint.truck_id == truck_id,
                AnchorPoint.date == d)
        .order_by(AnchorPoint.sequence.asc())
        .all()
    )
    if not aps:
        return None
    if t is not None:
        at = company_datetime(company_tz(db, company_id), d, t)
        before = [a for a in aps if a.submitted_at is not None and _aware(a.submitted_at) <= at]
        if before:
            return before[-1].location
    return aps[-1].location


def _reviewer_ids(db: Session, company_id, truck_id, d: date) -> list:
    """Employees on the truck that day as driver or captain."""
    if truck_id is None:
        return []
    rows = (
        db.query(AssignmentMember.employee_id)
        .join(TruckAssignment, AssignmentMember.assignment_id == TruckAssignment.id)
        .filter(
            TruckAssignment.company_id == company_id,
            AssignmentMember.company_id == company_id,
            TruckAssignment.truck_id == truck_id,
            TruckAssignment.date == d,
            AssignmentMember.role.in_(REVIEWER_ROLES),
        )
        .all()
    )
    return [r.employee_id for r in rows]


def _apply(report: StolenPackageReport, body: StolenPackageIn) -> None:
    for f in COMPARED:
        setattr(report, f, getattr(body, f))


def _mirror(inc: Incident, r: StolenPackageReport) -> None:
    """The incident's summary fields follow the report of record: the signed
    version once there is one, else the DA's (audit D8: the same count lived in
    two places and signing updated only one)."""
    inc.description, inc.incident_time, inc.packages_tba = r.summary, r.incident_time, r.packages_stolen


def _load(db: Session, incident_id: UUID, caller: Employee):
    inc = (
        db.query(Incident)
        .filter(Incident.id == incident_id, Incident.company_id == caller.company_id,
                Incident.category == "stolen_packages")
        .first()
    )
    if inc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found.")
    versions = {
        r.version: r for r in db.query(StolenPackageReport)
        .filter(StolenPackageReport.incident_id == inc.id,
                StolenPackageReport.company_id == caller.company_id)
        .all()
    }
    return inc, versions


def _can_view(db: Session, inc: Incident, versions: dict, caller: Employee) -> bool:
    """Oversight always. Field staff (an author, or a driver/captain on the truck
    that day) while the report is open and for 7 days after acceptance (D16)."""
    if caller.role in OVERSIGHT:
        return True
    if inc.resolved and not _within(inc.resolved_at, FIELD_VIEW_DAYS_AFTER_ACCEPT):
        return False
    if any(r.author_id == caller.id for r in versions.values()):
        return True
    return caller.id in _reviewer_ids(db, caller.company_id, inc.truck_id, inc.date)


def _out(r: StolenPackageReport, oversight: bool, names: dict) -> dict:
    d = {f: getattr(r, f) for f in COMPARED}
    d.update({
        "version": r.version,
        "author_id": str(r.author_id), "author_name": names.get(r.author_id),
        "da_employee_id": str(r.da_employee_id) if r.da_employee_id else None,
        "da_name": names.get(r.da_employee_id),
        "signed_at": r.signed_at, "pi_cleared_at": r.pi_cleared_at,
        "updated_at": r.updated_at,
    })
    if oversight:   # ADR-512 D5: never in a field-staff response
        d["reviewer_comments"] = r.reviewer_comments
    return d


def _mismatches(versions: dict) -> list[dict]:
    """Field-by-field, computed at read time (ADR-512 D3)."""
    a, b = versions.get(ReportVersion.DA), versions.get(ReportVersion.REVIEWER)
    if a is None or b is None:
        return []
    out = []
    for f in COMPARED:
        va, vb = getattr(a, f), getattr(b, f)
        if f == "tbas":
            va, vb = sorted(va or []), sorted(vb or [])
        if va != vb:
            out.append({"field": f, "da": getattr(a, f), "reviewer": getattr(b, f)})
    return out


def _names(db: Session, company_id, ids) -> dict:
    ids = [i for i in ids if i]
    if not ids:
        return {}
    return {e.id: e.name for e in db.query(Employee.id, Employee.name)
            .filter(Employee.company_id == company_id, Employee.id.in_(ids)).all()}


# -------------------------------------------------------------- endpoints ----

@router.get("/prefill")
def prefill(
    incident_date: date = Query(...),
    incident_time: Optional[time] = Query(default=None),
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_field_filer),
):
    """What the form can fill in for the DA: DSP, DA, truck, anchor point, reviewers."""
    truck_id, _assignment = _resolve_assignment(caller.id, incident_date, caller.company_id, db)
    truck = (db.query(Truck.id, Truck.name)
             .filter(Truck.id == truck_id, Truck.company_id == caller.company_id).first()
             if truck_id else None)
    reviewers = [i for i in _reviewer_ids(db, caller.company_id, truck_id, incident_date) if i != caller.id]
    names = _names(db, caller.company_id, reviewers)
    return {
        "dsp": _dsp(db, caller.company_id),
        "da": {"id": str(caller.id), "name": caller.name},
        "truck": {"id": str(truck.id), "name": truck.name} if truck else None,
        "anchor_point_address": _anchor_at(db, caller.company_id, truck_id, incident_date, incident_time),
        "reviewers": [{"id": str(i), "name": names.get(i)} for i in reviewers],
    }


@router.post("", status_code=status.HTTP_201_CREATED)
def file_report(
    body: StolenPackageIn,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_field_filer),
):
    """The DA files their version. The truck's driver/captain is asked to sign."""
    truck_id, _assignment = _resolve_assignment(caller.id, body.incident_date, caller.company_id, db)
    inc = Incident(
        company_id=caller.company_id, reporter_id=caller.id, truck_id=truck_id,
        date=body.incident_date, category="stolen_packages", severity="warning",
        # The summary, NOT the address: the address lives on the report only,
        # where retention and erasure reach it (ADR-512 D5).
        description=body.summary, incident_time=body.incident_time,
        packages_tba=body.packages_stolen,
    )
    db.add(inc)
    db.flush()
    report = StolenPackageReport(company_id=caller.company_id, incident_id=inc.id,
                                 version=ReportVersion.DA, author_id=caller.id,
                                 da_employee_id=caller.id,
                                 # Filing is the DA's signature (D12, D18).
                                 signed_at=datetime.now(timezone.utc))
    _apply(report, body)
    db.add(report)
    db.flush()

    reviewers = [i for i in _reviewer_ids(db, caller.company_id, truck_id, body.incident_date)
                 if i != caller.id]
    for rid in reviewers:
        write_notification(
            db, company_id=caller.company_id, employee_id=rid, type="stolen_package_review",
            target_id=inc.id,   # ADR-519
            message=(f"{caller.name} filed a stolen-package report for {body.incident_date:%a, %b %d}. "
                     f"Review it, correct anything that is off, and sign."),
        )
    _notify_management(inc, caller, db)
    write_audit(db=db, company_id=caller.company_id, actor_id=caller.id,
                action_type="stolen_package.filed", target_table="incidents",
                target_id=str(inc.id),
                detail={"packages_stolen": body.packages_stolen, "tbas": len(body.tbas),
                        "reviewers_notified": len(reviewers)})
    db.commit()
    # Verification is always required (D14). No reviewer on the truck means the
    # report waits; oversight is shown why, and adding one to the truck fixes it.
    return {"incident_id": str(inc.id), "reviewers_notified": len(reviewers),
            "review_required": True}


@router.get("/to-sign")
def to_sign(
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_any_role),
):
    """Reports waiting for the caller's signature: on a truck they drove or
    captained, filed by someone else, not yet signed (the notification's target)."""
    since = company_today(db, caller.company_id) - timedelta(days=TO_SIGN_DAYS)
    shifts = {
        (r.truck_id, r.date) for r in
        db.query(TruckAssignment.truck_id, TruckAssignment.date)
        .join(AssignmentMember, AssignmentMember.assignment_id == TruckAssignment.id)
        .filter(TruckAssignment.company_id == caller.company_id,
                AssignmentMember.company_id == caller.company_id,
                AssignmentMember.employee_id == caller.id,
                AssignmentMember.role.in_(REVIEWER_ROLES),
                TruckAssignment.date >= since)
        .all()
    }
    if not shifts:
        return []
    rows = (
        db.query(Incident, StolenPackageReport)
        .join(StolenPackageReport, (StolenPackageReport.incident_id == Incident.id)
              & (StolenPackageReport.version == ReportVersion.DA))
        .filter(Incident.company_id == caller.company_id,
                StolenPackageReport.company_id == caller.company_id,
                Incident.category == "stolen_packages",
                Incident.date >= since,
                Incident.truck_id.in_({t for t, _d in shifts}),
                StolenPackageReport.author_id != caller.id)
        .order_by(Incident.date.desc())
        .all()
    )
    rows = [(i, r) for i, r in rows if (i.truck_id, i.date) in shifts]
    signed = {
        r.incident_id for r in db.query(StolenPackageReport.incident_id)
        .filter(StolenPackageReport.company_id == caller.company_id,
                StolenPackageReport.version == ReportVersion.REVIEWER,
                StolenPackageReport.incident_id.in_([i.id for i, _r in rows] or [None]))
        .all()
    }
    first = [(i, r) for i, r in rows if i.id not in signed and not i.resolved]

    # Re-verifications: only for the employee who verified, by id (D18), on any
    # truck, as long as the report is open.
    verified_by_me = (
        db.query(Incident)
        .join(StolenPackageReport, StolenPackageReport.incident_id == Incident.id)
        .filter(StolenPackageReport.company_id == caller.company_id,
                Incident.company_id == caller.company_id,
                StolenPackageReport.version == ReportVersion.REVIEWER,
                StolenPackageReport.author_id == caller.id,
                Incident.resolved.is_(False))
        .all()
    )
    allv: dict = {}
    for r in (db.query(StolenPackageReport)
              .filter(StolenPackageReport.company_id == caller.company_id,
                      StolenPackageReport.incident_id.in_([i.id for i in verified_by_me] or [None]))
              .all()):
        allv.setdefault(r.incident_id, {})[r.version] = r
    again = [(i, allv[i.id][ReportVersion.DA]) for i in verified_by_me
             if _state(i, allv.get(i.id, {})) == "needs_reverification"]

    names = _names(db, caller.company_id, [r.da_employee_id for _i, r in first + again])
    out = lambda i, r, kind: {   # noqa: E731
        "incident_id": str(i.id), "incident_date": i.date.isoformat(), "kind": kind,
        "da_name": names.get(r.da_employee_id), "packages_stolen": r.packages_stolen}
    return [out(i, r, "reverify") for i, r in again] + [out(i, r, "sign") for i, r in first]


@router.get("/{incident_id}")
def get_report(
    incident_id: UUID,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_any_role),
):
    inc, versions = _load(db, incident_id, caller)
    if not _can_view(db, inc, versions, caller):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found.")
    oversight = caller.role in OVERSIGHT
    ids = {r.author_id for r in versions.values()} | {r.da_employee_id for r in versions.values()}
    names = _names(db, caller.company_id, ids)
    reviewer_ids = _reviewer_ids(db, caller.company_id, inc.truck_id, inc.date)
    da, rv = versions.get(ReportVersion.DA), versions.get(ReportVersion.REVIEWER)
    state = _state(inc, versions)
    open_ = state != "accepted"
    return {
        "incident_id": str(inc.id),
        "dsp": _dsp(db, caller.company_id),
        "state": state,
        "resolved": inc.resolved,
        "accepted_at": _aware(inc.resolved_at).isoformat() if inc.resolved_at else None,
        "versions": {v: _out(r, oversight, names) for v, r in versions.items()},
        "mismatches": _mismatches(versions) if oversight else [],
        # Somebody can still verify: a driver/captain on the truck who did not file.
        "reviewers_available": any(i != (da.author_id if da else None) for i in reviewer_ids),
        "can_sign": (open_ and rv is None and caller.id in reviewer_ids
                     and (da is None or da.author_id != caller.id)),
        "can_reverify": state == "needs_reverification" and rv.author_id == caller.id,
        "can_edit_da": open_ and da is not None and da.author_id == caller.id,
        "can_accept": caller.role in OVERSIGHT and state == "verified",
        "can_reopen": (caller.role in ("management", "admin") and state == "accepted"
                       and _within(inc.resolved_at, REOPEN_DAYS)
                       and not any(r.pi_cleared_at for r in versions.values())),
    }


@router.put("/{incident_id}/da")
def edit_da(
    incident_id: UUID,
    body: StolenPackageIn,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_any_role),
):
    """The DA edits and re-signs their version until acceptance (D18). Nobody
    else edits it: it is their signed account."""
    inc, versions = _load(db, incident_id, caller)
    da, rv = versions.get(ReportVersion.DA), versions.get(ReportVersion.REVIEWER)
    if da is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found.")
    if da.author_id != caller.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Only the DA who filed this report can edit it.")
    if inc.resolved:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="This report has been accepted. Ask a manager to reopen it.")
    was = _state(inc, versions)
    changed = _changed(da, body)
    _apply(da, body)
    da.signed_at = datetime.now(timezone.utc)   # saving is signing
    if rv is None:   # else the verified copy stays the record until re-verified
        _mirror(inc, da)
    # The verified copy now rests on an account that changed: ask the SAME
    # verifier, by id, to look again (D18). Only on the transition, so a DA
    # saving twice does not notify twice.
    reverify = rv is not None and was == "verified"
    if reverify:
        write_notification(
            db, company_id=caller.company_id, employee_id=rv.author_id, type="stolen_package_review",
            target_id=incident_id,   # ADR-519
            message=(f"{caller.name} changed their stolen-package report for {da.incident_date:%a, %b %d}. "
                     f"Review the changes and verify it again."),
        )
    db.flush()
    write_audit(db=db, company_id=caller.company_id, actor_id=caller.id,
                action_type="stolen_package.da_signed", target_table="stolen_package_reports",
                target_id=str(da.id),
                detail={"incident_id": str(inc.id), "fields_changed": changed,
                        "reverification_requested": reverify})
    db.commit()
    return {"ok": True, "state": _state(inc, versions)}


@router.post("/{incident_id}/sign", status_code=status.HTTP_201_CREATED)
def sign(
    incident_id: UUID,
    body: SignIn,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_any_role),
):
    """The truck's driver or captain signs their (possibly edited) copy."""
    inc, versions = _load(db, incident_id, caller)
    da = versions.get(ReportVersion.DA)
    if da is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found.")
    if caller.id not in _reviewer_ids(db, caller.company_id, inc.truck_id, inc.date) or da.author_id == caller.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Only the truck's driver or captain can sign this report.")
    if ReportVersion.REVIEWER in versions:   # one-way stamp
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="This report has already been signed.")
    rv = StolenPackageReport(company_id=caller.company_id, incident_id=inc.id,
                             version=ReportVersion.REVIEWER, author_id=caller.id,
                             da_employee_id=da.da_employee_id,
                             reviewer_comments=body.reviewer_comments,
                             signed_at=datetime.now(timezone.utc))
    _apply(rv, body)
    db.add(rv)
    _mirror(inc, rv)
    try:
        db.flush()
    except IntegrityError:
        # The driver and captain signed at once: uq_stolen_report_version let
        # one through. The loser gets the same answer as a later second sign.
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="This report has already been signed.")
    write_audit(db=db, company_id=caller.company_id, actor_id=caller.id,
                action_type="stolen_package.signed", target_table="stolen_package_reports",
                target_id=str(rv.id),
                detail={"incident_id": str(inc.id), "mismatches": len(_mismatches({**versions, ReportVersion.REVIEWER: rv}))})
    db.commit()
    return {"ok": True, "signed_at": rv.signed_at.isoformat()}


@router.put("/{incident_id}/reviewer")
def reverify(
    incident_id: UUID,
    body: SignIn,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_any_role),
):
    """The verifier signs again after the DA changed their version (D18). Only
    the employee who verified, and only when re-verification is needed."""
    inc, versions = _load(db, incident_id, caller)
    rv = versions.get(ReportVersion.REVIEWER)
    if rv is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found.")
    if rv.author_id != caller.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Only the person who verified this report can verify it again.")
    if _state(inc, versions) != "needs_reverification":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="There is nothing to verify again: the DA has not changed their report.")
    changed = _changed(rv, body)
    _apply(rv, body)
    # The verifier cannot read their earlier comments (oversight only, D5), so a
    # blank box must not erase them: new comments are added, never replaced.
    new = (body.reviewer_comments or "").strip()
    if new:
        rv.reviewer_comments = f"{rv.reviewer_comments}\n\nOn re-verification: {new}" if rv.reviewer_comments else new
    rv.signed_at = datetime.now(timezone.utc)
    _mirror(inc, rv)
    db.flush()
    write_audit(db=db, company_id=caller.company_id, actor_id=caller.id,
                action_type="stolen_package.reverified", target_table="stolen_package_reports",
                target_id=str(rv.id), detail={"incident_id": str(inc.id), "fields_changed": changed})
    db.commit()
    return {"ok": True, "state": _state(inc, versions)}


@router.post("/{incident_id}/accept")
def accept(
    incident_id: UUID,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_oversight),
):
    """Dispatch/management/admin accept a verified report. Both signatures are
    required, with no exception (D14)."""
    inc, versions = _load(db, incident_id, caller)
    state = _state(inc, versions)
    if state == "accepted":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This report is already accepted.")
    if state != "verified":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=ACCEPT_BLOCKED[state])
    inc.resolved, inc.resolved_by, inc.resolved_at = True, caller.id, datetime.now(timezone.utc)
    for eid in {r.author_id for r in versions.values()}:
        write_notification(
            db, company_id=caller.company_id, employee_id=eid, type="incident_resolved",
            target_id=incident_id,   # ADR-519
            message=f"Your stolen-package report for {inc.date:%a, %b %d} was accepted.",
        )
    db.flush()
    write_audit(db=db, company_id=caller.company_id, actor_id=caller.id,
                action_type="stolen_package.accepted", target_table="incidents",
                target_id=str(inc.id), detail={"mismatches": len(_mismatches(versions))})
    db.commit()
    return {"ok": True, "state": "accepted"}


#: Why a report cannot be accepted yet, by state. Shared with the generic
#: incident resolve, which applies the same rule (D14).
ACCEPT_BLOCKED = {
    "submitted": "This report needs the driver's or captain's signature before it can be accepted.",
    "needs_reverification": "The DA changed this report after it was verified. It needs verifying again.",
}


@router.post("/{incident_id}/reopen")
def reopen(
    incident_id: UUID,
    body: ReopenIn,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_reopen),
):
    """Management/admin reopen an accepted report, with a reason, within 7 days
    of acceptance and before the 60-day clearing (D20)."""
    inc, versions = _load(db, incident_id, caller)
    if not inc.resolved:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This report is not accepted.")
    if any(r.pi_cleared_at for r in versions.values()):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="The address and TBAs have been cleared, so this report can no longer be reopened.")
    if not _within(inc.resolved_at, REOPEN_DAYS):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail=f"Reports can be reopened for {REOPEN_DAYS} days after they are accepted.")
    accepted_by, accepted_at = inc.resolved_by, inc.resolved_at
    inc.resolved, inc.resolved_by, inc.resolved_at = False, None, None
    reason = body.reason.strip()
    da, rv = versions.get(ReportVersion.DA), versions.get(ReportVersion.REVIEWER)
    when = f"{inc.date:%a, %b %d}"
    if da is not None:
        write_notification(
            db, company_id=caller.company_id, employee_id=da.author_id, type="stolen_package_reopened",
            target_id=incident_id,   # ADR-519
            message=f'Your stolen-package report for {when} was reopened ("{reason}"). Edit it and sign it again.',
        )
    if rv is not None:   # the employee who verified, by id (D18)
        write_notification(
            db, company_id=caller.company_id, employee_id=rv.author_id, type="stolen_package_reopened",
            target_id=incident_id,   # ADR-519
            message=(f'The stolen-package report you verified for {when} was reopened ("{reason}"). '
                     f"If the DA changes it, you will be asked to verify it again."),
        )
    db.flush()
    write_audit(db=db, company_id=caller.company_id, actor_id=caller.id,
                action_type="stolen_package.reopened", target_table="incidents", target_id=str(inc.id),
                detail={"reason": reason, "accepted_by": str(accepted_by) if accepted_by else None,
                        "accepted_at": _aware(accepted_at).isoformat() if accepted_at else None})
    db.commit()
    return {"ok": True, "state": _state(inc, versions)}


def report_text(dsp: Optional[str], r: StolenPackageReport, da_name: Optional[str]) -> str:
    """The owner's layout, field for field and in order (ADR-512 D6).

    Never includes reviewer_comments: that is oversight's, not the report's.
    """
    yn = lambda b: "Y" if b else "N"   # noqa: E731
    t = r.incident_time.strftime("%-I:%M %p") if r.incident_time else ""
    return "\n".join([
        f"Date of incident: {r.incident_date:%m/%d/%Y}",
        f"DSP: {dsp or ''}",
        f"DA Name: {da_name or ''}",
        f"Incident Address: {r.incident_address or ''}",
        f"Anchor Point Address: {r.anchor_point_address or ''}",
        f"Time of incident: {t}",
        f"Was LMET called (Y/N)? {yn(r.lmet_called)}",
        f"LMET Case Number (if applicable): {r.lmet_case_number or ''}",
        f"Were Bike Locks used to Anchor Totes (Y/N)? {yn(r.bike_locks_used)}",
        f"Was a cart cover being used (Y/N)? {yn(r.cart_cover_used)}",
        f"How many tote(s) were stolen? {r.totes_stolen}",
        f"Was the cart stolen (Y/N)? {yn(r.cart_stolen)}",
        f"Number of stolen packages: {r.packages_stolen}",
        f"TBAs stolen: {', '.join(r.tbas or [])}",
        f"Incident Summary: {r.summary}",
    ])


@router.get("/{incident_id}/report-text", response_class=PlainTextResponse)
def get_report_text(
    incident_id: UUID,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_any_role),
):
    """The signed version if there is one, else the DA's, in the owner's layout."""
    inc, versions = _load(db, incident_id, caller)
    if not _can_view(db, inc, versions, caller):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found.")
    r = versions.get(ReportVersion.REVIEWER) or versions.get(ReportVersion.DA)
    if r is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found.")
    names = _names(db, caller.company_id, [r.da_employee_id])
    return report_text(_dsp(db, caller.company_id), r, names.get(r.da_employee_id))

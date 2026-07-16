"""Amazon (NYCD) weekly scorecards (ADR-204 Phase B).

POST   /scorecards                 — mgmt creates/updates a week's scorecard (structured entry)
GET    /scorecards/me              — the caller's own scorecards (latest first)
GET    /scorecards/{week}          — mgmt: all scorecards for a week (individual + company)
DELETE /scorecards/{scorecard_id}  — mgmt removes one

Amazon-computed values are stored/displayed as-is. The cross-check (Phase D) compares a subset
against our DeliveryStop/RTS data. This router is public — no proprietary algorithm.
"""
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.api.deps import RoleChecker, get_caller_employee
from app.models.employee import Employee
from app.models.scorecard import Scorecard, ScorecardMetric
from app.schemas.scorecard import (
    ScorecardCreate, ScorecardOut, ScorecardDraftOut, ScorecardMetricIn,
    CrossCheckResponse, CrossCheckItem, RtsReasonEvidence,
)
from app.services.audit import write_audit

router = APIRouter(prefix="/scorecards", tags=["scorecards"])

_allow_mgmt = RoleChecker(["dispatch", "management", "admin"])


def _serialize(sc: Scorecard, emp_name: Optional[str]) -> dict:
    return {
        "id": sc.id, "week": sc.week, "scope": sc.scope,
        "employee_id": sc.employee_id, "employee_name": emp_name,
        "overall_standing": sc.overall_standing, "source_file_url": sc.source_file_url,
        "created_at": sc.created_at, "metrics": sc.metrics,
    }


@router.post("", response_model=ScorecardOut, status_code=status.HTTP_201_CREATED)
def upsert_scorecard(
    payload: ScorecardCreate,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_mgmt),
    db: Session = Depends(get_db),
):
    """Create or replace the scorecard for (week, scope, employee). Upsert on the
    unique key so re-uploading a corrected scorecard overwrites cleanly."""
    cid = caller.company_id

    if payload.scope == "individual" and payload.employee_id is None:
        raise HTTPException(status_code=400, detail="employee_id is required for an individual scorecard.")
    if payload.scope == "company" and payload.employee_id is not None:
        raise HTTPException(status_code=400, detail="A company scorecard must not name an employee.")

    emp_name = None
    if payload.employee_id is not None:
        emp = db.query(Employee).filter(
            Employee.id == payload.employee_id, Employee.company_id == cid,
        ).first()
        if not emp:
            raise HTTPException(status_code=404, detail="Employee not found.")
        emp_name = emp.name

    existing = db.query(Scorecard).filter(
        Scorecard.company_id == cid,
        Scorecard.week == payload.week,
        Scorecard.scope == payload.scope,
        Scorecard.employee_id == payload.employee_id,
    ).first()

    if existing:
        existing.overall_standing = payload.overall_standing
        existing.source_file_url = payload.source_file_url
        existing.entered_by = caller.id
        # Replace metric rows wholesale (cascade delete-orphan handles removal).
        existing.metrics.clear()
        db.flush()
        sc = existing
    else:
        sc = Scorecard(
            company_id=cid, week=payload.week, scope=payload.scope,
            employee_id=payload.employee_id, overall_standing=payload.overall_standing,
            source_file_url=payload.source_file_url, entered_by=caller.id,
        )
        db.add(sc)
        db.flush()

    for m in payload.metrics:
        sc.metrics.append(ScorecardMetric(
            key=m.key, label=m.label, value=m.value, unit=m.unit,
            tier=m.tier, flag=m.flag, sort_order=m.sort_order,
        ))

    write_audit(
        db=db, company_id=cid, actor_id=caller.id,
        action_type="scorecard.upsert", target_table="scorecards", target_id=str(sc.id),
        detail={"week": sc.week, "scope": sc.scope, "employee_id": str(sc.employee_id) if sc.employee_id else None,
                "metrics": len(payload.metrics)},
    )
    db.commit()
    db.refresh(sc)
    return _serialize(sc, emp_name)


@router.post("/parse", response_model=ScorecardDraftOut)
async def parse_scorecard(
    file: UploadFile = File(...),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_mgmt),
):
    """Auto-extract a scorecard image into a DRAFT (ADR-204 Phase C) using the
    existing AWS Textract integration. Does NOT save — the manager reviews/edits
    the draft in the entry form, then POSTs /scorecards. Falls back (503) to
    manual entry when Textract is unavailable in this environment.
    """
    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Empty file.")
    if len(contents) > 8 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Scorecard image exceeds the 8 MB limit.")

    from app.services.scorecard_ingestor import ScorecardIngestor
    try:
        draft = ScorecardIngestor(contents).parse()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Image parsing (Textract) is not available — enter the scorecard manually.",
        ) from exc

    return ScorecardDraftOut(
        week=draft.week,
        overall_standing=draft.overall_standing,
        metrics=[
            ScorecardMetricIn(
                key=m.key, label=m.label, value=m.value, flag=m.flag, sort_order=m.sort_order,
            ) for m in draft.metrics
        ],
    )


@router.get("/me", response_model=List[ScorecardOut])
def get_my_scorecards(
    caller: Employee = Depends(get_caller_employee),
    db: Session = Depends(get_db),
):
    """The caller's own individual scorecards, latest week first."""
    rows = db.query(Scorecard).filter(
        Scorecard.company_id == caller.company_id,
        Scorecard.scope == "individual",
        Scorecard.employee_id == caller.id,
    ).order_by(Scorecard.week.desc()).all()
    return [_serialize(sc, caller.name) for sc in rows]


@router.get("/{week}", response_model=List[ScorecardOut])
def get_week_scorecards(
    week: str,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_mgmt),
    db: Session = Depends(get_db),
):
    """All scorecards for a week (individual + company) — management view."""
    cid = caller.company_id
    rows = db.query(Scorecard).filter(
        Scorecard.company_id == cid, Scorecard.week == week,
    ).all()
    emp_ids = {sc.employee_id for sc in rows if sc.employee_id}
    names = {
        e.id: e.name for e in db.query(Employee).filter(
            Employee.id.in_(emp_ids), Employee.company_id == cid,
        ).all()
    } if emp_ids else {}
    return [_serialize(sc, names.get(sc.employee_id)) for sc in rows]


def _iso_week_range(week: str):
    """"2026-W28" → (monday, sunday) dates, or None if unparseable."""
    import re
    from datetime import date as _date
    m = re.match(r"^\s*(\d{4})-W(\d{1,2})\s*$", week)
    if not m:
        return None
    year, wk = int(m.group(1)), int(m.group(2))
    try:
        monday = _date.fromisocalendar(year, wk, 1)
        sunday = _date.fromisocalendar(year, wk, 7)
        return monday, sunday
    except ValueError:
        return None


def _num(value: str):
    """Pull the first number out of a scorecard value string ("203", "14492.7",
    "100.0%"). Returns None for tier words (PLATINUM)."""
    import re
    m = re.search(r"-?\d[\d,]*\.?\d*", (value or "").replace(",", ""))
    return float(m.group(0)) if m else None


@router.get("/{scorecard_id}/cross-check", response_model=CrossCheckResponse)
def cross_check_scorecard(
    scorecard_id: UUID,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_mgmt),
    db: Session = Depends(get_db),
):
    """Compare an INDIVIDUAL scorecard's Amazon numbers against our own data for
    that employee+week (ADR-204 D). Flags contestable defects and surfaces the RTS
    reasons we recorded as appeal evidence. Only Packages Delivered and Delivery
    Completion DPMO are cross-checkable — POD/DSB/CDF have no source of ours.
    """
    from sqlalchemy import func
    from app.models.delivery_stop import DeliveryStop
    from app.models.rts import RTSPackage, MissingPackage

    cid = caller.company_id
    sc = db.query(Scorecard).filter(
        Scorecard.id == scorecard_id, Scorecard.company_id == cid,
    ).first()
    if not sc:
        raise HTTPException(status_code=404, detail="Scorecard not found.")
    if sc.scope != "individual" or sc.employee_id is None:
        raise HTTPException(status_code=400, detail="Cross-check applies to individual scorecards only.")

    rng = _iso_week_range(sc.week)
    if rng is None:
        raise HTTPException(status_code=422, detail=f"Cannot parse week '{sc.week}' into a date range.")
    week_start, week_end = rng
    emp = sc.employee_id

    delivered = db.query(func.coalesce(func.sum(DeliveryStop.packages_delivered), 0)).filter(
        DeliveryStop.walker_id == emp, DeliveryStop.company_id == cid,
        DeliveryStop.status == "completed", DeliveryStop.completed_at.isnot(None),
        func.date(DeliveryStop.completed_at) >= week_start,
        func.date(DeliveryStop.completed_at) <= week_end,
    ).scalar() or 0
    our_rts = db.query(func.count(RTSPackage.id)).filter(
        RTSPackage.walker_id == emp, RTSPackage.company_id == cid,
        func.date(RTSPackage.recorded_at) >= week_start,
        func.date(RTSPackage.recorded_at) <= week_end,
    ).scalar() or 0
    our_missing = db.query(func.count(MissingPackage.id)).filter(
        MissingPackage.walker_id == emp, MissingPackage.company_id == cid,
        func.date(MissingPackage.reported_at) >= week_start,
        func.date(MissingPackage.reported_at) <= week_end,
    ).scalar() or 0

    metric_by_key = {m.key: m for m in sc.metrics}
    items: list[CrossCheckItem] = []

    # 1) Packages Delivered — direct count comparison.
    az_delivered = _num(metric_by_key["packages_delivered"].value) if "packages_delivered" in metric_by_key else None
    if az_delivered is not None:
        delta = round(az_delivered - delivered, 1)
        # Contestable if they differ by more than 5% (or >5 packages on small counts).
        thresh = max(5, 0.05 * max(az_delivered, delivered, 1))
        items.append(CrossCheckItem(
            metric="packages_delivered", amazon_value=az_delivered, our_value=float(delivered),
            delta=delta, contestable=abs(delta) > thresh,
            note=("Our completed-stop total differs from Amazon's — verify scan/completion timing."
                  if abs(delta) > thresh else "Matches our records."),
        ))

    # 2) Delivery Completion DPMO — our comparable = (rts+missing)/attempted * 1e6.
    az_dpmo = _num(metric_by_key["delivery_completion_dpmo"].value) if "delivery_completion_dpmo" in metric_by_key else None
    if az_dpmo is not None:
        attempted = delivered + our_rts + our_missing
        our_dpmo = round((our_rts + our_missing) / attempted * 1_000_000, 1) if attempted > 0 else None
        delta = round(az_dpmo - our_dpmo, 1) if our_dpmo is not None else None
        # Contestable if Amazon's DPMO is materially HIGHER than ours (they charged
        # more defects than our RTS/missing record supports).
        contestable = our_dpmo is not None and az_dpmo > our_dpmo * 1.25
        items.append(CrossCheckItem(
            metric="delivery_completion_dpmo", amazon_value=az_dpmo, our_value=our_dpmo,
            delta=delta, contestable=contestable,
            note=("Amazon's completion DPMO exceeds what our RTS/missing record supports — "
                  "the RTS reasons below are appeal evidence." if contestable
                  else "Consistent with our RTS/missing record."),
        ))

    # RTS reasons that week — the evidence for a completion-defect appeal.
    evidence = [
        RtsReasonEvidence(rts_type=rt, count=int(c))
        for rt, c in db.query(RTSPackage.rts_type, func.count(RTSPackage.id))
        .filter(
            RTSPackage.walker_id == emp, RTSPackage.company_id == cid,
            func.date(RTSPackage.recorded_at) >= week_start,
            func.date(RTSPackage.recorded_at) <= week_end,
        ).group_by(RTSPackage.rts_type)
        .order_by(func.count(RTSPackage.id).desc()).all()
    ]

    return CrossCheckResponse(
        scorecard_id=sc.id, week=sc.week, week_start=week_start, week_end=week_end,
        our_delivered=int(delivered), our_rts=int(our_rts), our_missing=int(our_missing),
        items=items, rts_evidence=evidence,
    )


@router.delete("/{scorecard_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_scorecard(
    scorecard_id: UUID,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_mgmt),
    db: Session = Depends(get_db),
):
    sc = db.query(Scorecard).filter(
        Scorecard.id == scorecard_id, Scorecard.company_id == caller.company_id,
    ).first()
    if not sc:
        raise HTTPException(status_code=404, detail="Scorecard not found.")
    db.delete(sc)
    write_audit(
        db=db, company_id=caller.company_id, actor_id=caller.id,
        action_type="scorecard.delete", target_table="scorecards", target_id=str(scorecard_id),
        detail={"week": sc.week, "scope": sc.scope},
    )
    db.commit()

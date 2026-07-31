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

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.api.deps import RoleChecker, get_caller_employee
from app.models.employee import Employee
from app.models.scorecard import Scorecard, ScorecardMetric
from app.schemas.scorecard import (
    CompanyStandingCard, IndividualTrendResponse, IndividualMetricTrend,
    IndividualMetricPoint, IndividualRosterResponse, IndividualRosterRow,
    ScorecardTrendResponse, MetricTrend, MetricTrendPoint, StandingPoint,
    ScorecardCreate, ScorecardOut, ScorecardDraftOut, ScorecardMetricIn,
    PackageRecord, PackageSearchResponse,
    CrossCheckResponse, CrossCheckItem, RtsReasonEvidence,
)
from app.services.audit import write_audit

router = APIRouter(prefix="/scorecards", tags=["scorecards"])

# Access tiers — see docs/SCORECARD_ACCESS_MODEL.md.
#
# Dispatch and management are NOT the same role. The former single _allow_mgmt
# gate conflated them and sat on endpoints returning individual scorecards, so
# dispatch could read every driver's personal Amazon metrics. Dispatch assigns
# tomorrow's crew; per-person performance review is not their function.
_ALL_ROLES = ["driver", "walker", "trainer", "trainee", "dispatch", "management", "admin"]

# Tier 1 — company standing only. A shared fact about the operation, no per-person data.
_allow_company_read = RoleChecker(_ALL_ROLES)
# Tier 2 — company detail + trend. Dispatch included: company-level context, still no PII.
_allow_company_detail = RoleChecker(["dispatch", "management", "admin"])
# Tier 3/4 — individual scorecards, entry, deletion, appeals. Management owns these.
_allow_individual = RoleChecker(["management", "admin"])


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
    _: dict = Depends(_allow_individual),
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
        # company_id is stamped explicitly, not inherited via the relationship —
        # it is nullable=False, so an unset value fails the insert outright.
        sc.metrics.append(ScorecardMetric(
            company_id=cid,
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
    _: dict = Depends(_allow_individual),
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


@router.get("/{scorecard_id}/cross-check", response_model=CrossCheckResponse)
def cross_check_scorecard(
    scorecard_id: UUID,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_individual),
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
    _: dict = Depends(_allow_individual),
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


# ── Company trend ────────────────────────────────────────────────────────────

# Metrics where a HIGHER number is worse, so an increase is a regression.
# DPMO (defects per million opportunities) and driver-behaviour counts all
# invert. Getting this wrong would paint a worsening week as an improvement.
_LOWER_IS_BETTER = {
    "dnr_dpmo", "dpmo", "seatbelt_off_rate", "speeding_event_rate",
    "distractions_rate", "following_distance_rate", "sign_signal_violations_rate",
    "harsh_braking", "harsh_acceleration", "harsh_cornering",
    "customer_escalation_dpmo", "cdf_dpmo", "ced",
}


# Amazon's standing ladder, best first. Index order matters: a LOWER index is a
# BETTER tier, so improvement means the index decreased.
_STANDING_LADDER = ["FANTASTIC", "GREAT", "FAIR", "POOR", "AT RISK"]


def _standing_rank(standing: Optional[str]) -> Optional[int]:
    """Ladder position, or None for an unrecognised label.

    None is deliberate: an unknown tier word must not be silently treated as
    best or worst, which would fabricate a direction.
    """
    if not standing:
        return None
    u = standing.strip().upper()
    for i, tier in enumerate(_STANDING_LADDER):
        if tier in u:
            return i
    return None


def _numeric(raw: str) -> Optional[float]:
    """Parse Amazon's value strings to a number, or None.

    Values arrive as display strings: "100.0%", "14492.7", "203", "PLATINUM",
    "1,234". Tier words are legitimately non-numeric — they chart as standings,
    not as a line — so None is a real answer here, not a failure.
    """
    if raw is None:
        return None
    cleaned = raw.strip().replace(",", "").replace("%", "").replace("$", "")
    try:
        return float(cleaned)
    except (TypeError, ValueError):
        return None


def _iter_weeks(start: str, end: str) -> list[str]:
    """Every ISO week label from start to end inclusive, e.g. 2026-W01.

    Used to surface GAPS: a missing week is operationally meaningful (nobody
    entered the scorecard) and must not silently close up in the chart.
    """
    try:
        sy, sw = int(start[:4]), int(start.split("W")[1])
        ey, ew = int(end[:4]), int(end.split("W")[1])
    except (IndexError, ValueError):
        return []
    out, y, w = [], sy, sw
    # ISO years have 52 or 53 weeks; step conservatively and stop on overrun.
    for _ in range(400):
        out.append(f"{y}-W{w:02d}")
        if (y, w) == (ey, ew):
            break
        w += 1
        if w > 53:
            y, w = y + 1, 1
    return out


@router.get("/company/trend", response_model=ScorecardTrendResponse)
def get_company_trend(
    weeks: int = 12,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_company_detail),
):
    """Company scorecard trend over the last N weeks.

    Company-scope rows only — individual scorecards are per-driver performance
    and belong on the walker/driver surfaces, not in a company trend.

    Returns per-metric series with week-over-week deltas, direction corrected
    for lower-is-better metrics, and the metrics Amazon flagged needs_focus in
    the newest week.
    """
    weeks = max(2, min(weeks, 52))

    cards = (
        db.query(Scorecard)
        .filter(Scorecard.company_id == caller.company_id,
                Scorecard.scope == "company")
        .order_by(Scorecard.week.desc())
        .limit(weeks)
        .all()
    )
    cards.reverse()                      # oldest -> newest for charting

    if not cards:
        return ScorecardTrendResponse(
            weeks=[], standings=[], metrics=[], focus_now=[], missing_weeks=[],
        )

    week_labels = [c.week for c in cards]
    card_ids = [c.id for c in cards]

    metric_rows = (
        db.query(ScorecardMetric)
        .filter(ScorecardMetric.company_id == caller.company_id,
                ScorecardMetric.scorecard_id.in_(card_ids))
        .all()
    )
    by_card: dict = {}
    for m in metric_rows:
        by_card.setdefault(m.scorecard_id, []).append(m)

    # key -> {label, unit, sort_order, week -> metric}
    series: dict = {}
    for card in cards:
        for m in by_card.get(card.id, []):
            s = series.setdefault(m.key, {
                "label": m.label, "unit": m.unit,
                "sort_order": m.sort_order, "weeks": {},
            })
            s["weeks"][card.week] = m

    trends: list[MetricTrend] = []
    for key, s in series.items():
        points, numeric_seen = [], []
        for wk in week_labels:
            m = s["weeks"].get(wk)
            if m is None:
                # Absent week for this metric — hold the slot so the series
                # stays aligned with week_labels rather than shifting.
                points.append(MetricTrendPoint(week=wk, value=None, raw=""))
                continue
            val = _numeric(m.value)
            if val is not None:
                numeric_seen.append(val)
            points.append(MetricTrendPoint(
                week=wk, value=val, raw=m.value, tier=m.tier, flag=m.flag,
            ))

        latest = numeric_seen[-1] if numeric_seen else None
        previous = numeric_seen[-2] if len(numeric_seen) > 1 else None
        delta = round(latest - previous, 3) if (latest is not None and previous is not None) else None

        direction = None
        if delta is not None and previous:
            improved = delta < 0 if key in _LOWER_IS_BETTER else delta > 0
            worsened = delta > 0 if key in _LOWER_IS_BETTER else delta < 0
            # 0.5% band: Amazon's numbers jitter, and calling that a trend is noise.
            if abs(delta) / abs(previous) < 0.005:
                direction = "flat"
            elif improved:
                direction = "up"
            elif worsened:
                direction = "down"

        trends.append(MetricTrend(
            key=key, label=s["label"], unit=s["unit"], points=points,
            latest=latest, previous=previous, delta=delta, direction=direction,
            weeks_flagged=sum(1 for p in points if p.flag == "needs_focus"),
        ))

    trends.sort(key=lambda t: series[t.key]["sort_order"])

    newest = week_labels[-1]
    focus_now = [
        t.label for t in trends
        if any(p.week == newest and p.flag == "needs_focus" for p in t.points)
    ]

    expected = _iter_weeks(week_labels[0], week_labels[-1])
    missing = [w for w in expected if w not in set(week_labels)]

    return ScorecardTrendResponse(
        weeks=week_labels,
        standings=[StandingPoint(week=c.week, standing=c.overall_standing) for c in cards],
        current_standing=cards[-1].overall_standing,
        previous_standing=cards[-2].overall_standing if len(cards) > 1 else None,
        metrics=trends,
        focus_now=focus_now,
        missing_weeks=missing,
    )


# ── Tier 1: company standing card (all roles) ────────────────────────────────

@router.get("/company/current", response_model=CompanyStandingCard)
def get_company_standing(
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_company_read),
):
    """The company's current standing — visible to EVERY role.

    Tier 1 (docs/SCORECARD_ACCESS_MODEL.md): a shared fact about the operation
    with no per-person data in it. A driver knowing the DSP is at PLATINUM is the
    same class of information as a company announcement.

    Returns the streak of consecutive weeks at the current standing, because
    "PLATINUM, 6 weeks running" carries information that "PLATINUM" alone does not.
    """
    cards = (
        db.query(Scorecard)
        .filter(Scorecard.company_id == caller.company_id,
                Scorecard.scope == "company")
        .order_by(Scorecard.week.desc())
        .limit(52)
        .all()
    )
    if not cards:
        return CompanyStandingCard(has_data=False)

    current = cards[0]
    previous = cards[1] if len(cards) > 1 else None

    direction = None
    if previous and current.overall_standing and previous.overall_standing:
        cur_i = _standing_rank(current.overall_standing)
        prev_i = _standing_rank(previous.overall_standing)
        if cur_i is None or prev_i is None:
            direction = None
        elif cur_i < prev_i:
            direction = "improved"        # lower index = better tier
        elif cur_i > prev_i:
            direction = "declined"
        else:
            direction = "unchanged"

    # Walk back while the standing matches — the streak at the CURRENT tier.
    streak = 0
    for c in cards:
        if c.overall_standing == current.overall_standing:
            streak += 1
        else:
            break

    return CompanyStandingCard(
        week=current.week,
        standing=current.overall_standing,
        previous_standing=previous.overall_standing if previous else None,
        direction=direction,
        consecutive_weeks=streak,
        has_data=True,
    )


# ── Tier 3: individual trends ────────────────────────────────────────────────

def _individual_trend(db: Session, company_id, employee_id, name: Optional[str],
                      weeks: int) -> IndividualTrendResponse:
    """Shared trend builder for one person.

    Reuses _numeric, _LOWER_IS_BETTER and the same 0.5% dead band as the company
    trend, so self-serve and management views cannot drift from each other or
    from the company page.
    """
    cards = (
        db.query(Scorecard)
        .filter(Scorecard.company_id == company_id,
                Scorecard.scope == "individual",
                Scorecard.employee_id == employee_id)
        .order_by(Scorecard.week.desc())
        .limit(max(2, min(weeks, 52)))
        .all()
    )
    cards.reverse()
    if not cards:
        return IndividualTrendResponse(
            employee_id=str(employee_id) if employee_id else None,
            employee_name=name, weeks=[], standings=[], metrics=[], focus_now=[],
        )

    week_labels = [c.week for c in cards]
    metric_rows = (
        db.query(ScorecardMetric)
        .filter(ScorecardMetric.company_id == company_id,
                ScorecardMetric.scorecard_id.in_([c.id for c in cards]))
        .all()
    )
    by_card: dict = {}
    for m in metric_rows:
        by_card.setdefault(m.scorecard_id, []).append(m)

    series: dict = {}
    for card in cards:
        for m in by_card.get(card.id, []):
            s = series.setdefault(m.key, {
                "label": m.label, "unit": m.unit,
                "sort_order": m.sort_order, "weeks": {},
            })
            s["weeks"][card.week] = m

    trends = []
    for key, s in series.items():
        points, numeric_seen = [], []
        for wk in week_labels:
            m = s["weeks"].get(wk)
            if m is None:
                points.append(IndividualMetricPoint(week=wk, value=None, raw=""))
                continue
            val = _numeric(m.value)
            if val is not None:
                numeric_seen.append(val)
            points.append(IndividualMetricPoint(
                week=wk, value=val, raw=m.value, flag=m.flag))

        latest = numeric_seen[-1] if numeric_seen else None
        prev = numeric_seen[-2] if len(numeric_seen) > 1 else None
        delta = round(latest - prev, 3) if (latest is not None and prev is not None) else None

        direction = None
        if delta is not None and prev:
            improved = delta < 0 if key in _LOWER_IS_BETTER else delta > 0
            if abs(delta) / abs(prev) < 0.005:
                direction = "flat"
            else:
                direction = "up" if improved else "down"

        trends.append(IndividualMetricTrend(
            key=key, label=s["label"], unit=s["unit"], points=points,
            latest=latest, previous=prev, delta=delta, direction=direction))

    trends.sort(key=lambda t: series[t.key]["sort_order"])
    newest = week_labels[-1]
    focus = [t.label for t in trends
             if any(p.week == newest and p.flag == "needs_focus" for p in t.points)]

    return IndividualTrendResponse(
        employee_id=str(employee_id) if employee_id else None,
        employee_name=name,
        weeks=week_labels,
        standings=[StandingPoint(week=c.week, standing=c.overall_standing) for c in cards],
        current_standing=cards[-1].overall_standing,
        metrics=trends,
        focus_now=focus,
    )


@router.get("/me/trend", response_model=IndividualTrendResponse)
def get_my_trend(
    weeks: int = 12,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
):
    """The caller's OWN scorecard trend.

    Self-access is an ownership filter (employee_id == caller.id), not a role
    gate — which is why this needs nothing beyond authentication. Field staff see
    the numbers they are judged by; they see no peer's data.
    """
    return _individual_trend(db, caller.company_id, caller.id, caller.name, weeks)


@router.get("/individual/{employee_id}/trend", response_model=IndividualTrendResponse)
def get_employee_trend(
    employee_id: UUID,
    weeks: int = 12,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_individual),
):
    """Any employee's scorecard trend — management and admin only (Tier 3).

    Dispatch is denied by the gate: per-person performance review is not a
    dispatch function.
    """
    target = (
        db.query(Employee)
        .filter(Employee.id == employee_id,
                Employee.company_id == caller.company_id)
        .first()
    )
    if target is None:
        # 404 rather than leaking whether the id exists in another tenant.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Employee not found.")
    return _individual_trend(db, caller.company_id, target.id, target.name, weeks)


@router.get("/individual/roster", response_model=IndividualRosterResponse)
def get_individual_roster(
    weeks: int = 4,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_individual),
):
    """Named roster of individual scorecard status — management and admin only.

    Named deliberately, matching /field-ops/walker-leaderboard which already
    shows named performance to this same audience. Anonymising it would make it
    unactionable for the people whose job is to act on it.

    Reports employees_without_scorecards so a thin roster reads as missing data
    rather than as a small team.
    """
    weeks = max(1, min(weeks, 26))

    cards = (
        db.query(Scorecard)
        .filter(Scorecard.company_id == caller.company_id,
                Scorecard.scope == "individual")
        .order_by(Scorecard.week.desc())
        .all()
    )
    if not cards:
        return IndividualRosterResponse(weeks_considered=[], rows=[])

    recent_weeks = sorted({c.week for c in cards}, reverse=True)[:weeks]
    in_scope = [c for c in cards if c.week in set(recent_weeks)]

    emp_ids = {c.employee_id for c in in_scope if c.employee_id}
    employees = {
        e.id: e for e in
        db.query(Employee).filter(Employee.id.in_(emp_ids),
                                  Employee.company_id == caller.company_id).all()
    }

    flagged = {}
    for m in (db.query(ScorecardMetric)
              .filter(ScorecardMetric.company_id == caller.company_id,
                      ScorecardMetric.scorecard_id.in_([c.id for c in in_scope]),
                      ScorecardMetric.flag == "needs_focus").all()):
        flagged[m.scorecard_id] = flagged.get(m.scorecard_id, 0) + 1

    per_emp: dict = {}
    for c in sorted(in_scope, key=lambda x: x.week):
        if c.employee_id:
            per_emp.setdefault(c.employee_id, []).append(c)

    rows = []
    for eid, ecards in per_emp.items():
        emp = employees.get(eid)
        if emp is None:
            continue
        newest = ecards[-1]
        prior = ecards[-2] if len(ecards) > 1 else None
        direction = None
        if prior and newest.overall_standing and prior.overall_standing:
            n_i, p_i = _standing_rank(newest.overall_standing), _standing_rank(prior.overall_standing)
            if n_i is not None and p_i is not None:
                direction = "improved" if n_i < p_i else "declined" if n_i > p_i else "unchanged"
        rows.append(IndividualRosterRow(
            employee_id=str(eid),
            employee_name=emp.name,
            employee_role=emp.role,
            latest_week=newest.week,
            standing=newest.overall_standing,
            weeks_recorded=len(ecards),
            flagged_metric_count=flagged.get(newest.id, 0),
            trend_direction=direction,
        ))

    # Worst first: flagged count, then declining standing. The point of a roster
    # is finding who needs attention, not alphabetical browsing.
    rows.sort(key=lambda r: (-r.flagged_metric_count, r.trend_direction != "declined"))

    active_field = (
        db.query(func.count(Employee.id))
        .filter(Employee.company_id == caller.company_id,
                Employee.is_active == True,   # noqa: E712
                Employee.role.in_(["driver", "walker", "trainer", "trainee"]))
        .scalar()
    ) or 0

    return IndividualRosterResponse(
        weeks_considered=sorted(recent_weeks),
        rows=rows,
        employees_without_scorecards=max(0, int(active_field) - len(rows)),
    )


# ── Package lookup for appeal evidence ───────────────────────────────────────

# A short suffix could collide across tenants' TBAs, so a minimum length keeps
# "4" from matching every package ending in 4.
_MIN_SUFFIX = 4


@router.get("/packages/search", response_model=PackageSearchResponse)
def search_packages(
    tba: str = Query(..., min_length=_MIN_SUFFIX, max_length=50,
                     description="Full TBA or its last 4+ digits"),
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_individual),
):
    """Find our record of a package by TBA, across all three package tables.

    Amazon cites a TBA on the scorecard; this finds what WE logged, so the
    disagreement can be evidenced on an appeal. Searching all three matters
    because "no record" and "logged as damaged at station sort" are very
    different appeal positions.

    Matching: SUFFIX first, since a manager is usually reading the last digits
    off Amazon's portal. Falls back to EXACT when the suffix finds nothing.
    A suffix hitting several rows is reported as ambiguous with all matches
    returned, rather than silently picking one — the caller re-queries with the
    full TBA.

    Tier 3 gate: package-level records are per-employee data.
    """
    from app.models.rts import RTSPackage, MissingPackage, DamagedPackage
    from app.models.walker_route import Route

    cid = caller.company_id
    needle = tba.strip().upper()

    def _collect(pattern: str, exact: bool) -> list[PackageRecord]:
        out: list[PackageRecord] = []

        # Route supplies the date for RTS/missing; damaged carries its own.
        rts_q = (
            db.query(RTSPackage, Route.route_date)
            .outerjoin(Route, Route.id == RTSPackage.route_id)
            .filter(RTSPackage.company_id == cid)
        )
        rts_q = rts_q.filter(RTSPackage.tba_number == pattern) if exact \
            else rts_q.filter(RTSPackage.tba_number.ilike(f"%{pattern}"))
        for pkg, rdate in rts_q.limit(25).all():
            out.append(PackageRecord(
                source="rts", tba_number=pkg.tba_number,
                recorded_at=pkg.recorded_at, route_date=rdate,
                walker_name=pkg.walker_name, rts_type=pkg.rts_type,
                rts_explanation=pkg.rts_explanation,
                is_reattemptable=pkg.is_reattemptable,
            ))

        miss_q = (
            db.query(MissingPackage, Route.route_date)
            .outerjoin(Route, Route.id == MissingPackage.route_id)
            .filter(MissingPackage.company_id == cid)
        )
        miss_q = miss_q.filter(MissingPackage.tba_number == pattern) if exact \
            else miss_q.filter(MissingPackage.tba_number.ilike(f"%{pattern}"))
        for pkg, rdate in miss_q.limit(25).all():
            out.append(PackageRecord(
                source="missing", tba_number=pkg.tba_number,
                recorded_at=pkg.reported_at, route_date=rdate,
                walker_name=pkg.walker_name,
                resolution_status=pkg.resolution_status,
                notes=pkg.resolution_notes,
            ))

        dmg_q = db.query(DamagedPackage).filter(DamagedPackage.company_id == cid)
        dmg_q = dmg_q.filter(DamagedPackage.tba_number == pattern) if exact \
            else dmg_q.filter(DamagedPackage.tba_number.ilike(f"%{pattern}"))
        for pkg in dmg_q.limit(25).all():
            out.append(PackageRecord(
                source="damaged", tba_number=pkg.tba_number,
                recorded_at=pkg.reported_at, route_date=pkg.route_date,
                walker_name=pkg.reported_by_name,
                resolution_status=pkg.resolution_status,
                damage_stage=pkg.stage, notes=pkg.damage_notes,
            ))

        # Newest first — the most recent record is the one being disputed.
        out.sort(key=lambda r: (r.recorded_at is None, r.recorded_at), reverse=True)
        return out

    results = _collect(needle, exact=False)
    matched_on = "suffix"

    # Empty suffix search: the input may BE a full TBA that stores differently
    # (padding, case), so try exact before giving up.
    if not results:
        results = _collect(needle, exact=True)
        matched_on = "exact" if results else "none"

    # Several suffix hits: return them all and say so. Picking one silently
    # would attach the wrong package to a financial record.
    ambiguous = matched_on == "suffix" and len({r.tba_number for r in results}) > 1

    return PackageSearchResponse(
        query=needle, matched_on=matched_on, results=results, ambiguous=ambiguous,
    )


# NOTE ON ORDERING: /{week} is a catch-all single-segment path, so it MUST be
# declared after every literal route under /scorecards. Declared earlier, a
# request to /scorecards/company/current matched here with week="company" and hit
# the management-only gate — surfacing as an inexplicable 403 for field staff
# rather than as a routing bug. FastAPI matches in declaration order.

@router.get("/{week}", response_model=List[ScorecardOut])
def get_week_scorecards(
    week: str,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_individual),
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

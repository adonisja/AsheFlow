"""Scorecard appeals (ADR-243).

  GET    /scorecard-appeals              list (filterable by status/week)
  GET    /scorecard-appeals/stats        win rate + which metrics are worth appealing
  POST   /scorecard-appeals              create a draft
  GET    /scorecard-appeals/{id}         one appeal with its line items
  PATCH  /scorecard-appeals/{id}         edit a DRAFT only
  POST   /scorecard-appeals/{id}/submit  mark as filed with Amazon
  POST   /scorecard-appeals/{id}/resolve record Amazon's decision
  PATCH  /scorecard-appeals/{id}/items/{item_id}  per-metric outcome
  DELETE /scorecard-appeals/{id}         delete a DRAFT only

Tier 4 (docs/SCORECARD_ACCESS_MODEL.md): appeals reach individual scorecard data,
so they inherit Tier 3's gate — management and admin only. Dispatch is excluded.

AsheFlow never files with Amazon. `submit` records that a human did.
"""
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.api.deps import RoleChecker, get_caller_employee
from app.models.employee import Employee
from app.models.scorecard import Scorecard
from app.models.scorecard_appeal import (
    APPEAL_TERMINAL_STATUSES, ScorecardAppeal, ScorecardAppealItem,
)
from app.schemas.scorecard_appeal import (
    AppealCreate, AppealListItem, AppealOut, AppealResolve, AppealStats,
    AppealItemResolve, AppealSubmit, AppealUpdate,
)
from app.services.audit import write_audit

router = APIRouter(prefix="/scorecard-appeals", tags=["scorecard-appeals"])

# Tier 4 — appeals reach individual data. Dispatch excluded (ADR-242).
_allow_appeals = RoleChecker(["management", "admin"])


def _get_owned(db: Session, appeal_id: UUID, company_id: UUID) -> ScorecardAppeal:
    """Fetch an appeal within the caller's tenant, or 404.

    404 rather than 403 for another tenant's id: 403 would confirm it exists.
    """
    appeal = (
        db.query(ScorecardAppeal)
        .options(selectinload(ScorecardAppeal.items))
        .filter(ScorecardAppeal.id == appeal_id,
                ScorecardAppeal.company_id == company_id)
        .first()
    )
    if appeal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Appeal not found.")
    return appeal


@router.get("", response_model=List[AppealListItem])
def list_appeals(
    status_filter: Optional[str] = Query(None, alias="status"),
    week: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_appeals),
):
    """Appeals index. Newest first; no line items so the list stays cheap."""
    q = db.query(ScorecardAppeal).filter(
        ScorecardAppeal.company_id == caller.company_id)
    if status_filter:
        q = q.filter(ScorecardAppeal.status == status_filter)
    if week:
        q = q.filter(ScorecardAppeal.week == week)
    appeals = q.order_by(ScorecardAppeal.created_at.desc()).limit(200).all()

    ids = [a.id for a in appeals]
    counts, accepted = {}, {}
    if ids:
        for aid, n in (db.query(ScorecardAppealItem.appeal_id, func.count(ScorecardAppealItem.id))
                       .filter(ScorecardAppealItem.company_id == caller.company_id,
                               ScorecardAppealItem.appeal_id.in_(ids))
                       .group_by(ScorecardAppealItem.appeal_id).all()):
            counts[aid] = int(n)
        for aid, n in (db.query(ScorecardAppealItem.appeal_id, func.count(ScorecardAppealItem.id))
                       .filter(ScorecardAppealItem.company_id == caller.company_id,
                               ScorecardAppealItem.appeal_id.in_(ids),
                               ScorecardAppealItem.outcome == "accepted")
                       .group_by(ScorecardAppealItem.appeal_id).all()):
            accepted[aid] = int(n)

    return [
        AppealListItem(
            id=a.id, scorecard_id=a.scorecard_id, week=a.week, scope=a.scope,
            employee_name=a.employee_name, status=a.status, title=a.title,
            item_count=counts.get(a.id, 0), items_accepted=accepted.get(a.id, 0),
            submitted_at=a.submitted_at, resolved_at=a.resolved_at,
            created_at=a.created_at,
        )
        for a in appeals
    ]


@router.get("/stats", response_model=AppealStats)
def get_appeal_stats(
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_appeals),
):
    """Win rate and which metrics are worth contesting.

    This is why line items exist: "we win DNR appeals and lose CDF appeals" is
    only answerable per-metric, and it tells a manager where to spend the effort.
    """
    by_status = dict(
        db.query(ScorecardAppeal.status, func.count(ScorecardAppeal.id))
        .filter(ScorecardAppeal.company_id == caller.company_id)
        .group_by(ScorecardAppeal.status).all()
    )
    won, lost = int(by_status.get("won", 0)), int(by_status.get("lost", 0))
    decided = won + lost
    # None, not 0.0 — "nothing resolved yet" is not "we lose everything".
    win_rate = round(won / decided * 100, 1) if decided else None

    appealed = (
        db.query(ScorecardAppealItem.metric_label, func.count(ScorecardAppealItem.id))
        .filter(ScorecardAppealItem.company_id == caller.company_id)
        .group_by(ScorecardAppealItem.metric_label)
        .order_by(func.count(ScorecardAppealItem.id).desc()).limit(5).all()
    )
    won_metrics = (
        db.query(ScorecardAppealItem.metric_label, func.count(ScorecardAppealItem.id))
        .filter(ScorecardAppealItem.company_id == caller.company_id,
                ScorecardAppealItem.outcome == "accepted")
        .group_by(ScorecardAppealItem.metric_label)
        .order_by(func.count(ScorecardAppealItem.id).desc()).limit(5).all()
    )

    return AppealStats(
        total=sum(int(v) for v in by_status.values()),
        draft=int(by_status.get("draft", 0)),
        submitted=int(by_status.get("submitted", 0)),
        won=won, lost=lost, withdrawn=int(by_status.get("withdrawn", 0)),
        win_rate_pct=win_rate,
        most_appealed_metrics=[{"metric": m, "count": int(n)} for m, n in appealed],
        most_won_metrics=[{"metric": m, "count": int(n)} for m, n in won_metrics],
    )


@router.post("", response_model=AppealOut, status_code=status.HTTP_201_CREATED)
def create_appeal(
    payload: AppealCreate,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_appeals),
):
    """Open a draft appeal against a scorecard."""
    cid = caller.company_id

    scorecard = (
        db.query(Scorecard)
        .filter(Scorecard.id == payload.scorecard_id, Scorecard.company_id == cid)
        .first()
    )
    if scorecard is None:
        raise HTTPException(status_code=404, detail="Scorecard not found.")

    # One OPEN appeal per scorecard. Not a DB unique constraint: a withdrawn
    # appeal may legitimately be followed by a second attempt.
    existing = (
        db.query(ScorecardAppeal)
        .filter(ScorecardAppeal.company_id == cid,
                ScorecardAppeal.scorecard_id == payload.scorecard_id,
                ScorecardAppeal.status.notin_(APPEAL_TERMINAL_STATUSES))
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An open appeal already exists for this scorecard.",
        )

    emp_name = None
    if scorecard.employee_id:
        emp = db.query(Employee).filter(
            Employee.id == scorecard.employee_id, Employee.company_id == cid).first()
        emp_name = emp.name if emp else None

    appeal = ScorecardAppeal(
        company_id=cid, scorecard_id=scorecard.id, week=scorecard.week,
        scope=scorecard.scope, employee_id=scorecard.employee_id,
        employee_name=emp_name, status="draft",
        title=payload.title, rationale=payload.rationale,
        created_by=caller.id, created_by_name=caller.name,
    )
    db.add(appeal)
    db.flush()                      # assigns appeal.id for the child rows

    for it in payload.items:
        appeal.items.append(ScorecardAppealItem(
            company_id=cid,         # stamped, not inherited (Dimension 1)
            metric_key=it.metric_key, metric_label=it.metric_label,
            amazon_value=it.amazon_value, our_value=it.our_value, delta=it.delta,
            evidence=it.evidence, claim=it.claim, sort_order=it.sort_order,
        ))

    write_audit(
        db=db, company_id=cid, actor_id=caller.id,
        action_type="scorecard_appeal.create",
        target_table="scorecard_appeals", target_id=str(appeal.id),
        detail={"week": appeal.week, "scope": appeal.scope,
                "items": len(payload.items)},
    )
    db.commit()
    db.refresh(appeal)
    return appeal


@router.get("/{appeal_id}", response_model=AppealOut)
def get_appeal(
    appeal_id: UUID,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_appeals),
):
    return _get_owned(db, appeal_id, caller.company_id)


@router.patch("/{appeal_id}", response_model=AppealOut)
def update_appeal(
    appeal_id: UUID,
    payload: AppealUpdate,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_appeals),
):
    """Edit a DRAFT.

    Filed appeals are immutable: once submitted, the contents are the record of
    what was actually put to Amazon, and editing it would falsify that.
    """
    appeal = _get_owned(db, appeal_id, caller.company_id)
    if appeal.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Only a draft can be edited; this appeal is '{appeal.status}'.",
        )

    if payload.title is not None:
        appeal.title = payload.title
    if payload.rationale is not None:
        appeal.rationale = payload.rationale
    if payload.items is not None:
        appeal.items.clear()
        db.flush()
        for it in payload.items:
            appeal.items.append(ScorecardAppealItem(
                company_id=caller.company_id,
                metric_key=it.metric_key, metric_label=it.metric_label,
                amazon_value=it.amazon_value, our_value=it.our_value,
                delta=it.delta, evidence=it.evidence, claim=it.claim,
                sort_order=it.sort_order,
            ))

    db.flush()
    write_audit(
        db=db, company_id=caller.company_id, actor_id=caller.id,
        action_type="scorecard_appeal.update",
        target_table="scorecard_appeals", target_id=str(appeal.id),
        detail={"items": len(appeal.items)},
    )
    db.commit()
    db.refresh(appeal)
    return appeal


@router.post("/{appeal_id}/submit", response_model=AppealOut)
def submit_appeal(
    appeal_id: UUID,
    payload: AppealSubmit,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_appeals),
):
    """Record that a human filed this with Amazon.

    One-way stamp: submitted_at is set once, so re-submitting is a 409 rather
    than silently overwriting the filing date.
    """
    appeal = _get_owned(db, appeal_id, caller.company_id)

    if appeal.submitted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This appeal has already been submitted.",
        )
    if appeal.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Only a draft can be submitted; this appeal is '{appeal.status}'.",
        )
    if not appeal.items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An appeal must contest at least one metric before submission.",
        )

    appeal.status = "submitted"
    appeal.submitted_at = datetime.now(timezone.utc)
    appeal.submitted_by = caller.id
    appeal.submitted_by_name = caller.name
    appeal.amazon_reference = payload.amazon_reference

    db.flush()
    write_audit(
        db=db, company_id=caller.company_id, actor_id=caller.id,
        action_type="scorecard_appeal.submit",
        target_table="scorecard_appeals", target_id=str(appeal.id),
        detail={"week": appeal.week, "amazon_reference": payload.amazon_reference,
                "items": len(appeal.items)},
    )
    db.commit()
    db.refresh(appeal)
    return appeal


@router.post("/{appeal_id}/resolve", response_model=AppealOut)
def resolve_appeal(
    appeal_id: UUID,
    payload: AppealResolve,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_appeals),
):
    """Record Amazon's decision, or withdraw.

    One-way stamp: resolved_at guards re-resolution (409).
    """
    appeal = _get_owned(db, appeal_id, caller.company_id)

    if appeal.resolved_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This appeal is already resolved as '{appeal.status}'.",
        )
    # Withdrawing a draft is legitimate; won/lost require it to have been filed.
    if payload.outcome in ("won", "lost") and appeal.status != "submitted":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only a submitted appeal can be won or lost.",
        )

    appeal.status = payload.outcome
    appeal.resolved_at = datetime.now(timezone.utc)
    appeal.resolved_by = caller.id
    appeal.resolved_by_name = caller.name
    appeal.outcome_notes = payload.outcome_notes

    db.flush()
    write_audit(
        db=db, company_id=caller.company_id, actor_id=caller.id,
        action_type="scorecard_appeal.resolve",
        target_table="scorecard_appeals", target_id=str(appeal.id),
        detail={"outcome": payload.outcome, "week": appeal.week},
    )
    db.commit()
    db.refresh(appeal)
    return appeal


@router.patch("/{appeal_id}/items/{item_id}", response_model=AppealOut)
def resolve_item(
    appeal_id: UUID,
    item_id: UUID,
    payload: AppealItemResolve,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_appeals),
):
    """Record Amazon's decision on ONE contested metric.

    Amazon can accept one metric and reject another in the same appeal, which is
    the reason line items exist at all.
    """
    appeal = _get_owned(db, appeal_id, caller.company_id)

    item = next((i for i in appeal.items if i.id == item_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="Appeal item not found.")
    if item.outcome != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This metric is already resolved as '{item.outcome}'.",
        )

    item.outcome = payload.outcome
    item.corrected_value = payload.corrected_value
    item.outcome_notes = payload.outcome_notes

    db.flush()
    write_audit(
        db=db, company_id=caller.company_id, actor_id=caller.id,
        action_type="scorecard_appeal.item_resolve",
        target_table="scorecard_appeal_items", target_id=str(item.id),
        detail={"appeal_id": str(appeal.id), "metric": item.metric_key,
                "outcome": payload.outcome},
    )
    db.commit()
    db.refresh(appeal)
    return appeal


@router.delete("/{appeal_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_appeal(
    appeal_id: UUID,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_appeals),
):
    """Delete a DRAFT. Filed appeals are a financial record — withdraw instead."""
    appeal = _get_owned(db, appeal_id, caller.company_id)
    if appeal.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only a draft can be deleted; withdraw a filed appeal instead.",
        )

    write_audit(
        db=db, company_id=caller.company_id, actor_id=caller.id,
        action_type="scorecard_appeal.delete",
        target_table="scorecard_appeals", target_id=str(appeal.id),
        detail={"week": appeal.week},
    )
    db.delete(appeal)
    db.commit()
    return None

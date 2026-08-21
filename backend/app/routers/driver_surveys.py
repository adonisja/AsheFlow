"""driver_surveys.py — Driver Survey feature.

Management activates a survey for a dispatch date; all assigned trainers and walkers
receive a notification and can submit one yes/no response per question.

Endpoints:
  POST   /driver-surveys                        management/admin — activate survey for a date
  GET    /driver-surveys                        management/admin — list surveys with counts
  GET    /driver-surveys/{date}                 management/admin — full detail + per-question stats
  POST   /driver-surveys/{survey_id}/respond    trainer/walker   — submit response
  GET    /driver-surveys/{survey_id}/my-response trainer/walker  — check own response
"""

import os
import threading
from datetime import date, datetime, timezone, timedelta
from typing import List
from uuid import UUID

import requests as http_requests
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.api.deps import RoleChecker, get_caller_employee, Pagination
from app.database import get_db
from app.models.assignment_member import AssignmentMember
from app.models.driver_survey import DriverSurvey, DriverSurveyResponse
from app.models.employee import Employee
from app.models.notification import Notification
from app.models.truck import Truck
from app.models.truck_assignment import TruckAssignment
from app.schemas.driver_survey import (
    DriverSurveyCreate,
    DriverSurveyDetail,
    DriverSurveyListItem,
    DriverSurveyResponseCreate,
    DriverSurveyResponseItem,
    MyResponseStatus,
    SurveyStats,
)
from app.services.audit import write_audit
from app.services.company_config import get_company_config

router = APIRouter(prefix="/driver-surveys", tags=["driver-surveys"])

allow_management = RoleChecker(["management", "admin"])
allow_field      = RoleChecker(["trainer", "walker"])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _fire_discord_dm(discord_id: str, message: str) -> None:
    bot_url = os.environ.get("BOT_INTERNAL_URL", "http://bot:8001")
    secret  = os.environ.get("INTERNAL_SECRET", "")

    def _run():
        try:
            http_requests.post(
                f"{bot_url}/internal/dm",
                json={"discord_id": discord_id, "message": message},
                headers={"X-Internal-Secret": secret},
                timeout=5,
            )
        except Exception:
            pass

    threading.Thread(target=_run, daemon=True).start()


def _midnight_utc(d: date) -> datetime:
    """Return midnight at the end of date d in UTC (i.e. start of the next day)."""
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc) + timedelta(days=1)


def _resolve_assignment_for_respondent(
    respondent_id: UUID,
    survey_date: date,
    company_id: UUID,
    db: Session,
) -> "tuple[TruckAssignment | None, AssignmentMember | None]":
    """Return (TruckAssignment, AssignmentMember) for this respondent on survey_date."""
    member = (
        db.query(AssignmentMember)
        .join(TruckAssignment, TruckAssignment.id == AssignmentMember.assignment_id)
        .filter(
            AssignmentMember.employee_id == respondent_id,
            AssignmentMember.company_id  == company_id,
            TruckAssignment.date         == survey_date,
            TruckAssignment.company_id   == company_id,
        )
        .first()
    )
    if member is None:
        return None, None
    assignment = db.query(TruckAssignment).filter(TruckAssignment.id == member.assignment_id).first()
    return assignment, member


def _build_response_item(
    resp: DriverSurveyResponse,
    survey_date: date,
    db: Session,
    company_id: UUID = None,
) -> DriverSurveyResponseItem:
    """Resolve display fields (name, email, driver, truck) and build the response schema."""
    cid = company_id or resp.company_id
    respondent = db.query(Employee).filter(
        Employee.id == resp.respondent_id,
        Employee.company_id == cid,
    ).first()
    respondent_name  = respondent.name  if respondent else str(resp.respondent_id)
    respondent_email = respondent.email if respondent else None
    respondent_role  = respondent.role  if respondent else "unknown"

    truck_name  = None
    driver_name = None
    if resp.truck_assignment_id:
        assignment = db.query(TruckAssignment).filter(
            TruckAssignment.id == resp.truck_assignment_id,
            TruckAssignment.company_id == cid,
        ).first()
        if assignment:
            truck = db.query(Truck).filter(Truck.id == assignment.truck_id).first()
            truck_name = truck.name if truck else None
            driver_member = (
                db.query(AssignmentMember)
                .filter(
                    AssignmentMember.assignment_id == assignment.id,
                    AssignmentMember.company_id    == cid,
                    AssignmentMember.role          == "driver",
                )
                .first()
            )
            if driver_member:
                driver_emp  = db.query(Employee).filter(
                    Employee.id == driver_member.employee_id,
                    Employee.company_id == cid,
                ).first()
                driver_name = driver_emp.name if driver_emp else None

    return DriverSurveyResponseItem(
        id                    = resp.id,
        respondent_id         = resp.respondent_id,
        respondent_name       = respondent_name,
        respondent_email      = respondent_email,
        respondent_role       = respondent_role,
        truck_name            = truck_name,
        driver_name           = driver_name,
        routes_organized      = resp.routes_organized,
        anchor_point_location = resp.anchor_point_location,
        supplies_ready        = resp.supplies_ready,
        driver_support        = resp.driver_support,
        notes                 = resp.notes,
        submitted_at          = resp.submitted_at,
    )


# ---------------------------------------------------------------------------
# POST /driver-surveys — activate survey for a date
# ---------------------------------------------------------------------------

@router.post("/", status_code=status.HTTP_201_CREATED, response_model=DriverSurveyListItem)
def activate_survey(
    body: DriverSurveyCreate,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_management),
    db: Session = Depends(get_db),
):
    """Activate a driver survey for a dispatch date.

    Blocked if fewer than 3 hours have elapsed since shift_start on that date.
    Fans out a notification and Discord DM to all assigned trainers and walkers.
    One survey per company per date — returns 409 if one already exists.
    """
    # Uniqueness check
    existing = db.query(DriverSurvey).filter(
        DriverSurvey.company_id == caller.company_id,
        DriverSurvey.date       == body.date,
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A driver survey already exists for {body.date}.",
        )

    # 3-hour shift rule
    cfg = get_company_config(db, caller.company_id)
    if cfg and cfg.shift_start:
        earliest_send = datetime.combine(body.date, cfg.shift_start).replace(tzinfo=timezone.utc) + timedelta(hours=3)
        if datetime.now(timezone.utc) < earliest_send:
            earliest_local = earliest_send.strftime("%-I:%M %p")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Driver surveys can only be sent at least 3 hours after shift start. "
                    f"Earliest send time for {body.date}: {earliest_local}."
                ),
            )

    survey = DriverSurvey(
        company_id = caller.company_id,
        date       = body.date,
        created_by = caller.id,
    )
    db.add(survey)
    db.flush()

    # Find all trainers and walkers assigned on this date
    members = (
        db.query(AssignmentMember, Employee, TruckAssignment, Truck)
        .join(TruckAssignment, TruckAssignment.id == AssignmentMember.assignment_id)
        .join(Employee,         Employee.id        == AssignmentMember.employee_id)
        .join(Truck,            Truck.id           == TruckAssignment.truck_id)
        .filter(
            AssignmentMember.company_id  == caller.company_id,
            TruckAssignment.company_id   == caller.company_id,
            TruckAssignment.date         == body.date,
            AssignmentMember.role.in_(["trainer", "walker"]),
        )
        .all()
    )

    expires = _midnight_utc(body.date)

    for am, emp, assignment, truck in members:
        notif_msg = (
            f"A driver survey is available for your shift today ({truck.name}). "
            f"Please complete it before end of day."
        )
        db.add(Notification(
            company_id    = caller.company_id,
            employee_id   = emp.id,
            type          = "driver_survey",
            message       = notif_msg,
            expires_at    = expires,
        ))
        if emp.discord_id:
            _fire_discord_dm(str(emp.discord_id), notif_msg)

    db.commit()

    response_count = db.query(DriverSurveyResponse).filter(
        DriverSurveyResponse.survey_id == survey.id
    ).count()

    return DriverSurveyListItem(
        id             = survey.id,
        date           = survey.date,
        created_at     = survey.created_at,
        expected_count = len(members),
        response_count = response_count,
    )


# ---------------------------------------------------------------------------
# GET /driver-surveys — list surveys
# ---------------------------------------------------------------------------

@router.get("/", response_model=List[DriverSurveyListItem])
def list_surveys(
    response: Response,
    pg: Pagination = Depends(),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_management),
    db: Session = Depends(get_db),
):
    """List all driver surveys for this company, newest first.

    Sets X-Total-Count header with the unfiltered total for client-side pagination.
    """
    base_q = (
        db.query(DriverSurvey)
        .filter(DriverSurvey.company_id == caller.company_id)
        .order_by(DriverSurvey.date.desc())
    )
    total = base_q.count()
    surveys = pg.apply(base_q).all()

    response.headers["X-Total-Count"] = str(total)

    result = []
    for survey in surveys:
        expected_count = (
            db.query(AssignmentMember)
            .join(TruckAssignment, TruckAssignment.id == AssignmentMember.assignment_id)
            .filter(
                TruckAssignment.company_id  == caller.company_id,
                TruckAssignment.date        == survey.date,
                AssignmentMember.role.in_(["trainer", "walker"]),
            )
            .count()
        )
        response_count = db.query(DriverSurveyResponse).filter(
            DriverSurveyResponse.survey_id == survey.id
        ).count()
        result.append(DriverSurveyListItem(
            id             = survey.id,
            date           = survey.date,
            created_at     = survey.created_at,
            expected_count = expected_count,
            response_count = response_count,
        ))
    return result


# ---------------------------------------------------------------------------
# GET /driver-surveys/{date} — full detail
# ---------------------------------------------------------------------------

@router.get("/{survey_date}", response_model=DriverSurveyDetail)
def get_survey(
    survey_date: date,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_management),
    db: Session = Depends(get_db),
):
    """Return a survey with all responses and per-question statistics."""
    survey = db.query(DriverSurvey).filter(
        DriverSurvey.company_id == caller.company_id,
        DriverSurvey.date       == survey_date,
    ).first()
    if not survey:
        raise HTTPException(status_code=404, detail="No survey found for this date.")

    expected_count = (
        db.query(AssignmentMember)
        .join(TruckAssignment, TruckAssignment.id == AssignmentMember.assignment_id)
        .filter(
            TruckAssignment.company_id == caller.company_id,
            TruckAssignment.date       == survey_date,
            AssignmentMember.role.in_(["trainer", "walker"]),
        )
        .count()
    )

    raw_responses = db.query(DriverSurveyResponse).filter(
        DriverSurveyResponse.survey_id == survey.id
    ).order_by(DriverSurveyResponse.submitted_at.asc()).all()

    n = len(raw_responses)

    def _pct(field: str) -> float:
        if n == 0:
            return 0.0
        yes_count = sum(1 for r in raw_responses if getattr(r, field))
        return round(yes_count / n * 100, 1)

    stats = SurveyStats(
        expected_count       = expected_count,
        response_count       = n,
        routes_organized_pct = _pct("routes_organized"),
        anchor_location_pct  = _pct("anchor_point_location"),
        supplies_ready_pct   = _pct("supplies_ready"),
        driver_support_pct   = _pct("driver_support"),
    )

    responses = [_build_response_item(r, survey_date, db, caller.company_id) for r in raw_responses]

    return DriverSurveyDetail(
        id         = survey.id,
        date       = survey.date,
        created_at = survey.created_at,
        stats      = stats,
        responses  = responses,
    )


# ---------------------------------------------------------------------------
# POST /driver-surveys/{survey_id}/respond — submit response
# ---------------------------------------------------------------------------

@router.post("/{survey_id}/respond", status_code=status.HTTP_201_CREATED,
             response_model=DriverSurveyResponseItem)
def submit_response(
    survey_id: UUID,
    body: DriverSurveyResponseCreate,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_field),
    db: Session = Depends(get_db),
):
    """Submit a driver survey response. One response per person per survey.

    The respondent's truck and driver are auto-resolved from their dispatch assignment
    for the survey date. They are notified which truck their response is for.
    """
    survey = db.query(DriverSurvey).filter(
        DriverSurvey.id         == survey_id,
        DriverSurvey.company_id == caller.company_id,
    ).first()
    if not survey:
        raise HTTPException(status_code=404, detail="Survey not found.")

    if datetime.now(timezone.utc) >= _midnight_utc(survey.date):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"This survey closed at midnight on {survey.date}. Responses are no longer accepted.",
        )

    existing = db.query(DriverSurveyResponse).filter(
        DriverSurveyResponse.survey_id     == survey_id,
        DriverSurveyResponse.respondent_id == caller.id,
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You have already submitted a response for this survey.",
        )

    # Resolve primary assignment for the survey date
    assignment, _ = _resolve_assignment_for_respondent(
        caller.id, survey.date, caller.company_id, db
    )

    response = DriverSurveyResponse(
        company_id            = caller.company_id,
        survey_id             = survey_id,
        respondent_id         = caller.id,
        truck_assignment_id   = assignment.id if assignment else None,
        routes_organized      = body.routes_organized,
        anchor_point_location = body.anchor_point_location,
        supplies_ready        = body.supplies_ready,
        driver_support        = body.driver_support,
        notes                 = body.notes,
    )
    db.add(response)
    db.commit()
    db.refresh(response)

    return _build_response_item(response, survey.date, db, caller.company_id)


# ---------------------------------------------------------------------------
# GET /driver-surveys/{survey_id}/my-response — check own response
# ---------------------------------------------------------------------------

@router.get("/{survey_id}/my-response", response_model=MyResponseStatus)
def get_my_response(
    survey_id: UUID,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_field),
    db: Session = Depends(get_db),
):
    """Return whether the caller has already responded and the response if so."""
    survey = db.query(DriverSurvey).filter(
        DriverSurvey.id         == survey_id,
        DriverSurvey.company_id == caller.company_id,
    ).first()
    if not survey:
        raise HTTPException(status_code=404, detail="Survey not found.")

    existing = db.query(DriverSurveyResponse).filter(
        DriverSurveyResponse.survey_id     == survey_id,
        DriverSurveyResponse.respondent_id == caller.id,
    ).first()

    if not existing:
        return MyResponseStatus(responded=False)

    return MyResponseStatus(
        responded = True,
        response  = _build_response_item(existing, survey.date, db, caller.company_id),
    )

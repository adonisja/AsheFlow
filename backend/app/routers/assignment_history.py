"""Past assignment history and day replay (ADR-268).

  GET /assignment-history/me            any employee — own days only
  GET /assignment-history/me/stats      any employee — own slim series
  GET /assignment-history/day/{date}    dispatch+   — a whole past day
  GET /assignment-history/{employee_id} dispatch+   — anyone's days

Public router: the whole feature is a read-only aggregation over completed
records, so nothing here belongs in the proprietary sync.

The two endpoints exist because the two reads are different questions with
different audiences, and collapsing them into one with an optional
`employee_id` would make the authorisation depend on whether a query parameter
was supplied — the exact shape that left /dispatch/confirmations/history
ungated (ADR-268).
"""
from datetime import date, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import RoleChecker, get_caller_employee
from app.database import get_db
from app.models.employee import Employee
from app.schemas.assignment_history import AssignmentHistoryResponse
from app.schemas.dispatch_replay import DayReplayOut
from app.schemas.stats_series import (
    LifetimeTotalsOut, MyStatsOut, StatsSeriesOut, YearStatOut,
)
from app.services.assignment_history import get_assignment_history
from app.services.dispatch_replay import get_day_replay
from app.services.stats_series import (
    MAX_LOOKBACK_MONTHS, get_lifetime_totals, get_stats_series, get_year_stats,
)

router = APIRouter(prefix="/assignment-history", tags=["assignment-history"])

# Reading ANOTHER person's history is an oversight action.
_allow_dispatch = RoleChecker(["dispatch", "management", "admin"])

# A year of days is already more than any screen shows, and an unbounded range
# lets one request walk the whole table.
_MAX_RANGE_DAYS = 366


def _check_range(start_date: date, end_date: date) -> None:
    if end_date < start_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="end_date must not be before start_date.",
        )
    if (end_date - start_date).days > _MAX_RANGE_DAYS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Date range must be {_MAX_RANGE_DAYS} days or fewer.",
        )


@router.get("/me", response_model=AssignmentHistoryResponse)
def get_my_assignment_history(
    start_date: date = Query(..., description="Start of range (inclusive)"),
    end_date: date = Query(..., description="End of range (inclusive)"),
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
):
    """The caller's own past assignments — any authenticated employee.

    Ungated by role and scoped to `caller.id`. That filter IS the
    authorisation: the signature takes no employee parameter, so there is
    nothing a caller could pass to widen it.

    Declared BEFORE /{employee_id} so the literal path wins — "me" is not a
    UUID, so it would 422 rather than match, but relying on that would be
    relying on a parse failure.
    """
    _check_range(start_date, end_date)
    days = get_assignment_history(
        db, caller.company_id, caller.id, start_date, end_date)
    return AssignmentHistoryResponse(
        employee_id=str(caller.id),
        start_date=start_date,
        end_date=end_date,
        days=days,
    )


@router.get("/{employee_id}", response_model=AssignmentHistoryResponse)
def get_employee_assignment_history(
    employee_id: UUID,
    start_date: date = Query(..., description="Start of range (inclusive)"),
    end_date: date = Query(..., description="End of range (inclusive)"),
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_dispatch),
):
    """Another employee's past assignments — dispatch, management, admin.

    The employee is re-fetched under the caller's company_id rather than
    trusted from the path: without it, a dispatcher could read a history from
    another tenant by pasting a UUID (Dimension 1).
    """
    _check_range(start_date, end_date)

    target = (
        db.query(Employee)
        .filter(Employee.id == employee_id, Employee.company_id == caller.company_id)
        .first()
    )
    if target is None:
        # Same 404 whether the employee does not exist or belongs to another
        # company — distinguishing them would confirm the id is real elsewhere.
        raise HTTPException(status_code=404, detail="Employee not found")

    days = get_assignment_history(
        db, caller.company_id, target.id, start_date, end_date)
    return AssignmentHistoryResponse(
        employee_id=str(target.id),
        start_date=start_date,
        end_date=end_date,
        days=days,
    )


@router.get("/day/{day}", response_model=DayReplayOut)
def get_day_replay_endpoint(
    day: date,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_dispatch),
):
    """What a past day actually ran — dispatch, management, admin.

    `GET /dispatch/{date}` already returns the board for any date, but only the
    PLAN: crews, zones, package_count. This adds the outcome half — delivered
    vs total, RTS by reason, per truck AND per crew member.

    Declared with a literal `/day/` prefix so it cannot be confused with
    `/{employee_id}`, which takes a UUID. A date would fail that parse rather
    than match, but relying on a parse failure to route a request is not a
    design.

    Future dates are allowed rather than rejected: "the day has not run yet"
    is a legitimate answer, and it renders as zeros without a special case.
    """
    return get_day_replay(db, caller.company_id, day)


@router.get("/me/stats", response_model=MyStatsOut)
def get_my_stats(
    months: int = Query(
        MAX_LOOKBACK_MONTHS, ge=1, le=MAX_LOOKBACK_MONTHS,
        description="Lookback in months. Capped — an unbounded window lets one "
                    "request walk the whole table.",
    ),
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
):
    """The caller's own lifetime totals plus a slim daily series (ADR-271).

    ONE request serves the whole drill-down. Year, month and week are all
    groupings of the same daily rows, so the client aggregates on device rather
    than asking the server four times for four views of one dataset. Measured:
    54 bytes per day here against 1,978 for the full history payload, because
    the crew roster — not the numbers — is what makes that one heavy.

    THE SERIES ENDS YESTERDAY. Today is in flight, so including it would make
    the payload change under a reader who cached it. Excluding it is what makes
    the cache safe: nothing here can change after it is served.

    Self-scoped exactly like /me above — the signature takes no employee
    parameter, so there is nothing a caller could pass to widen it. Ungated by
    role: everyone may read their own stats, and `role` is echoed back only so
    the client knows which damage figures apply (ADR-271 F).

    Day DETAIL (truck, crew, RTS explanations) is deliberately NOT here. It is
    fetched from /assignment-history/me when a day is opened, which is the only
    level that needs it.
    """
    lifetime = get_lifetime_totals(db, caller.company_id, caller.id, caller.role)
    years = get_year_stats(db, caller.company_id, caller.id, caller.role)
    series = get_stats_series(
        db, caller.company_id, caller.id, caller.role, months=months
    )
    return MyStatsOut(
        lifetime=LifetimeTotalsOut.model_validate(lifetime, from_attributes=True),
        years=[YearStatOut.model_validate(y, from_attributes=True) for y in years],
        series=StatsSeriesOut.model_validate(series, from_attributes=True),
    )

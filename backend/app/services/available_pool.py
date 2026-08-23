from datetime import date
from uuid import UUID

from sqlalchemy import or_
from sqlalchemy.orm import Session
from app.models.employee import Employee
from app.models.employee_off_day import EmployeeOffDay
from app.models.time_off_request import TimeOffRequest
from app.services.local_date import company_today


def get_available_pool(db: Session, target_date: date = None, company_id: UUID = None) -> dict:
    """Return active employees grouped by role who are available on target_date, scoped to company."""
    if company_id is None:
        raise ValueError("company_id is required for get_available_pool")
    target_date = target_date or company_today(db, company_id)

    # Both EXISTS subqueries below are CORRELATED to the outer Employee query
    # (employee_id == Employee.id), and that outer query is company-scoped, so
    # a foreign-tenant row cannot correlate to an in-tenant employee. The
    # explicit company_id is belt-and-braces: it states the boundary locally
    # instead of making a reader trace the correlation to establish it, and it
    # keeps every query in this module scoped the same way.
    has_off_day_today = (
        db.query(EmployeeOffDay)
        .filter(
            EmployeeOffDay.company_id == company_id,
            EmployeeOffDay.employee_id == Employee.id,
            # ilike, not ==: the /schedule/available endpoint and
            # get_emergency_pool both compare case-insensitively, and an exact
            # match here would disagree with them on mixed-case data — the same
            # person excluded from one pool and present in another. Nothing
            # normalises day_of_week on write, so the readers must agree.
            EmployeeOffDay.day_of_week.ilike(target_date.strftime("%A")),
            EmployeeOffDay.status == "approved",
        )
        .exists()
    )

    has_pto_today = (
        db.query(TimeOffRequest)
        .filter(
            TimeOffRequest.company_id == company_id,
            TimeOffRequest.employee_id == Employee.id,
            TimeOffRequest.date == target_date,
            TimeOffRequest.status == "approved",
        )
        .exists()
    )

    available_employees = (
        db.query(Employee)
        .filter(
            Employee.company_id == company_id,
            # ADR-256: captain is dispatchable crew. field_supervisor is NOT — they
            # oversee the road rather than filling a seat on one truck.
            #
            # ADR-264: driver_trainee is dispatchable — they DRIVE and are the
            # main worker for the day, with a supervising driver assisting.
            # Omitting them here dropped them before the bucketing below ever
            # ran: an active, scheduled driver trainee was invisible to dispatch
            # with no warning, which is how someone works a whole program with
            # no training records and nobody finds out.
            Employee.role.in_([
                "driver", "trainer", "trainee", "walker", "captain", "driver_trainee",
            ]),
            Employee.is_active == True,
            ~or_(has_off_day_today, has_pto_today),
        )
        .all()
    )

    # `driver_trainees` is its own bucket, never folded into "drivers" (ADR-264
    # D2/D6): they consume a truck seat AND require a second driver, so a caller
    # counting drivers against trucks must be able to tell them apart.
    available_pool = {
        "drivers": [], "trainers": [], "trainees": [], "walkers": [],
        "captains": [], "driver_trainees": [],
    }
    for employee in available_employees:
        if employee.role == "driver":
            available_pool["drivers"].append(employee)
        elif employee.role == "trainer":
            available_pool["trainers"].append(employee)
        elif employee.role == "trainee":
            available_pool["trainees"].append(employee)
        elif employee.role == "walker":
            available_pool["walkers"].append(employee)
        elif employee.role == "captain":
            available_pool["captains"].append(employee)
        elif employee.role == "driver_trainee":
            available_pool["driver_trainees"].append(employee)

    return available_pool


def get_unavailable_staff(db: Session, target_date: date = None, roles: list = None, company_id: UUID = None) -> list:
    """Return active employees excluded from the pool on target_date, with reason, scoped to company.

    The inverse of get_available_pool for a given set of roles. Used by dispatch
    to surface a call-in list when understaffed warnings fire.

    Trainees are always excluded — their assignment flow is managed through the
    training system, not manual dispatch phone calls.
    """
    if company_id is None:
        raise ValueError("company_id is required for get_unavailable_staff")
    target_date = target_date or company_today(db, company_id)
    day_name = target_date.strftime("%A")

    # Captain in the default (ADR-256): a captain excluded by PTO belongs in the
    # call-in list like any other truck role. The endpoint passes roles
    # explicitly, but a direct caller relying on this default would silently
    # miss them.
    allowed_roles = [
        r for r in (roles or ["driver", "captain", "trainer", "walker"])
        if r != "trainee"
    ]

    employees = (
        db.query(Employee)
        .filter(
            Employee.company_id == company_id,
            Employee.role.in_(allowed_roles),
            Employee.is_active == True,
        )
        .all()
    )

    employee_ids = [e.id for e in employees]

    # These carry their own company_id even though employee_ids already comes
    # from a company-scoped query. The .in_() bound makes them safe only
    # TRANSITIVELY — it depends on an invariant established several statements
    # earlier, and a later edit that widens employee_ids turns them into
    # cross-tenant reads with no visible change here. ADR-115 D1 requires every
    # inner query to carry its own scope for that reason.
    time_off_ids = {
        row.employee_id
        for row in db.query(TimeOffRequest).filter(
            TimeOffRequest.company_id == company_id,
            TimeOffRequest.date == target_date,
            TimeOffRequest.status == "approved",
            TimeOffRequest.employee_id.in_(employee_ids),
        ).all()
    } if employee_ids else set()

    off_day_ids = {
        row.employee_id
        for row in db.query(EmployeeOffDay).filter(
            EmployeeOffDay.company_id == company_id,
            EmployeeOffDay.day_of_week == day_name,
            EmployeeOffDay.status == "approved",
            EmployeeOffDay.employee_id.in_(employee_ids),
        ).all()
    } if employee_ids else set()

    excluded_ids = time_off_ids | off_day_ids

    result = []
    for emp in employees:
        if emp.id not in excluded_ids:
            continue
        reason = "time_off_request" if emp.id in time_off_ids else "recurring_off_day"
        result.append({
            "id": str(emp.id),
            "name": emp.name,
            "role": emp.role,
            "discord_id": emp.discord_id,
            "phone_number": emp.phone_number,
            "reason": reason,
        })

    role_order = {"driver": 0, "trainer": 1, "walker": 2}
    result.sort(key=lambda e: (role_order.get(e["role"], 9), e["name"]))
    return result


def get_unavailable_drivers(db: Session, target_date: date = None, company_id: UUID = None) -> list:
    """Convenience wrapper — returns unavailable drivers only."""
    return get_unavailable_staff(db, target_date, roles=["driver"], company_id=company_id)


def get_emergency_pool(db: Session, target_date: date = None, company_id: UUID = None) -> list:
    """Everyone dispatch can still phone for target_date, with why they are free.

    Three groups, each labelled so nobody is called blind (ADR-267):

      scheduled_off  approved recurring day off — not working by default, askable
      declined       said no to THIS dispatch; often circumstantial, so dispatch
                     may negotiate
      unassigned     active and available, simply not on a truck

    Two hard exclusions:

      approved PTO   they asked for the day and it was granted. Listing them
                     invites a call that should not happen — this is the one
                     group the previous call-in list got backwards.
      trainees       their assignment runs through the training system, not a
                     dispatch phone call (matches get_unavailable_staff).

    Ordered driver → captain → trainer → walker, because a missing driver or
    captain strands a whole truck and is what dispatch reaches for first.
    """
    from app.models.assignment_member import AssignmentMember
    from app.models.dispatch_confirmation import DispatchConfirmation
    from app.models.truck_assignment import TruckAssignment

    if company_id is None:
        raise ValueError("company_id is required for get_emergency_pool")
    target_date = target_date or company_today(db, company_id)
    day_name = target_date.strftime("%A")

    employees = (
        db.query(Employee)
        .filter(
            Employee.company_id == company_id,
            Employee.is_active == True,
            # field_supervisor oversees the road rather than filling a seat
            # (ADR-256); trainee is excluded per above.
            Employee.role.in_(["driver", "captain", "trainer", "walker"]),
        )
        .all()
    )
    if not employees:
        return []
    employee_ids = [e.id for e in employees]

    # ── hard exclusion: approved PTO ─────────────────────────────────────────
    pto_ids = {
        row.employee_id
        for row in db.query(TimeOffRequest).filter(
            TimeOffRequest.company_id == company_id,
            TimeOffRequest.date == target_date,
            TimeOffRequest.status == "approved",
            TimeOffRequest.employee_id.in_(employee_ids),
        ).all()
    }

    # ── group 1: approved recurring day off ──────────────────────────────────
    # ilike, not ==: get_available_pool compares exactly while the availability
    # endpoint uses ilike, so mixed-case data would put someone in BOTH the
    # dispatch pool and this one. Matching the looser comparison keeps the two
    # consistent; the underlying inconsistency is noted in the journal.
    off_ids = {
        row.employee_id
        for row in db.query(EmployeeOffDay).filter(
            EmployeeOffDay.company_id == company_id,
            EmployeeOffDay.day_of_week.ilike(day_name),
            EmployeeOffDay.status == "approved",
            EmployeeOffDay.employee_id.in_(employee_ids),
        ).all()
    }

    # ── group 2: declined this dispatch ──────────────────────────────────────
    declined_ids = {
        row.employee_id
        for row in db.query(DispatchConfirmation).filter(
            DispatchConfirmation.company_id == company_id,
            DispatchConfirmation.date == target_date,
            DispatchConfirmation.status == "declined",
            DispatchConfirmation.employee_id.in_(employee_ids),
        ).all()
    }

    # ── group 3: not on a truck ──────────────────────────────────────────────
    assigned_ids = {
        row.employee_id
        for row in db.query(AssignmentMember)
        .join(TruckAssignment, AssignmentMember.assignment_id == TruckAssignment.id)
        .filter(
            TruckAssignment.company_id == company_id,
            TruckAssignment.date == target_date,
            AssignmentMember.employee_id.in_(employee_ids),
        ).all()
    }

    # driver/captain first: their absence strands a truck, not just a route.
    role_order = {"driver": 0, "captain": 1, "trainer": 2, "walker": 3}
    result = []
    for emp in employees:
        if emp.id in pto_ids:
            continue
        # Most actionable reason wins where several apply: a decline is a fresh
        # signal dispatch must react to, an off-day is a standing fact, and
        # "unassigned" is merely the absence of both.
        if emp.id in declined_ids:
            reason = "declined"
        elif emp.id in off_ids:
            reason = "scheduled_off"
        elif emp.id not in assigned_ids:
            reason = "unassigned"
        else:
            continue                      # on a truck and hasn't declined
        result.append({
            "id": str(emp.id),
            "name": emp.name,
            "role": emp.role,
            "reason": reason,
            "phone_number": emp.phone_number,
            "email": emp.email,
            "discord_id": emp.discord_id,
        })

    result.sort(key=lambda e: (role_order.get(e["role"], 9), e["name"]))
    return result

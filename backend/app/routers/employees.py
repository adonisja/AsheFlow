import boto3
import logging
import secrets
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Union
from uuid import UUID
from botocore.exceptions import ClientError

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.api.deps import (RoleChecker, Pagination, get_caller_employee,
                          get_caller_employee_optional, get_current_user)
from app.core.config import settings
from app.core.security import _get_redis
from app.database import get_db
from app.models.employee import Employee
from app.models.employee import VALID_ROLES as Employee_VALID_ROLES
from app.services import account_security
from app.services import device_fleet, discord_invite, mfa_status
from app.models.invite_token import InviteToken
from app.schemas.employee import (
    _validate_discord_id, EmployeeCreate, EmployeeUpdate, EmployeeResponse,
    EmployeePublicResponse, EmployeeOfficeResponse, EmployeeEscalationResponse, EmployeeRecordResponse,
    EmployeeMfaEnrolmentResponse, EmployeeMfaDeadlineResponse,
    BulkImportRow, BulkImportResult, InjuryStatusPatch, RoleTransitionRequest,
)
from app.services.audit import write_audit
from app.api.ratelimit import limiter
from app.services import mfa_containment
from app.services.company_onboarding import is_onboarding, setup_window
from app.services.email import send_invite_email
from app.services.integration_alerts import (
    raise_platform_alert, EMAIL_DELIVERY_FAILED, EMAIL_DOWN_MESSAGE,
    IDENTITY_REVOCATION_FAILED, IDENTITY_REVOCATION_MESSAGE,
)
from app.services.notify import write_notification
from app.tasks.discord_delivery import send_discord

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/employees", tags=["employees"])

# ADR-464 D1. Endpoints that answer "who am I", mounted WITHOUT
# require_configured.
#
# `router` above is gated on the company being configured, which is right for a
# roster (meaningless before setup) and wrong for identity: AuthContext calls
# /employees/me and /me/mfa-status on EVERY authenticated load, including the
# setup page whose whole purpose is to clear that condition. Gating them made
# setup unreachable -- 503 "Company setup is not complete" on the page that
# completes setup.
#
# The rule: a gate that tests COMPANY state must not cover an endpoint that
# answers WHO THE CALLER IS. Identity is what the client needs to decide
# whether this user may fix the state.
identity_router = APIRouter(prefix="/employees", tags=["employees"])


def _fire_discord_dm(discord_id: str, message: str) -> None:
    # ADR-487 D7: the send is a Celery task, not a daemon thread. Retry,
    # backoff, jitter and response classification live there; this builds
    # the payload and hands it over.
    send_discord.delay("dm", {"discord_id": discord_id, "message": message})


def _fire_role_sync(discord_id: str, company_id: str, action: str) -> None:
    """Fire-and-forget: tell the bot to grant or revoke the trainer Discord role.

    action: "grant_trainer" | "revoke_trainer"
    """
    # ADR-487 D7: a Celery task, not a daemon thread — retry, backoff and
    # response classification live there.
    #
    # An access change, not a notification: a role-sync that silently failed
    # leaves a trainer without the Discord role that gates their commands, so a
    # terminal failure records an audit row rather than a delivery_failed_at.
    send_discord.delay(
        "role-sync",
        {"discord_id": discord_id, "company_id": company_id, "action": action},
        company_id=str(company_id),
    )

# Cognito group name per role — must match your User Pool group names exactly
# ADR-256/264 added captain, field_supervisor and driver_trainee. A role missing
# here resolves to None via .get() and the Cognito group silently never syncs —
# the user keeps their OLD group and its permissions after a role change.
# Mirrored in routers/registration.py; the two copies must stay in sync.
ROLE_TO_COGNITO_GROUP: dict[str, str] = {
    "driver":           "driver",
    "walker":           "walker",
    "trainer":          "trainer",
    "trainee":          "trainee",
    "dispatch":         "dispatch",
    "management":       "management",
    "admin":            "admin",
    "captain":          "captain",
    "field_supervisor": "field_supervisor",
    "driver_trainee":   "driver_trainee",
}


def _cognito_client():
    return boto3.client("cognito-idp", region_name=settings.aws_region)


def _refuse_if_owner(employee, action: str) -> None:
    """The Owner cannot be removed or demoted by anyone (ADR-452 D2).

    INCLUDING THEMSELVES. A company with no Owner has nobody who can appoint
    one, so the mistake is unrecoverable from inside the tenant -- refusing
    costs a support conversation, allowing it costs the tenant.

    Before this, every one of these endpoints scoped by company_id and stopped,
    so any admin could delete the founder. ADR-451 D3 protected that row from
    the BOOTSTRAP endpoint while the ordinary employee endpoints stayed open.
    """
    if getattr(employee, "is_owner", False):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"This is the company Owner and cannot be {action}. "
                "Transfer ownership to another admin first."
            ),
        )


def cognito_username_for(employee) -> str | None:
    """The Username this employee's Cognito account actually has (ADR-380 F7).

    NOT a guess, and not the email. Which identifier is correct depends on how
    far through onboarding they are:

      pre-registration   AdminCreateUser used the EMAIL as the Username
      post-registration  complete_registration derived firstname.lastname and
                         stamped it on Employee.username

    So `username or email` -- in that order -- is the only correct resolution,
    and it is what cleanup.py and the deactivate/delete paths already use.

    Three sites deviated, and each was a silent no-op on a REGISTERED employee:
    Cognito raises UserNotFoundException and every one of them swallowed it into
    a log line.

    cognito_sub is deliberately NOT a fallback: it is a valid Username for admin
    APIs, but reaching for it hides the real problem, which is that neither
    identifier was stamped.
    """
    return getattr(employee, "username", None) or getattr(employee, "email", None)


def _cognito_revoke_access(cognito_username: str | None) -> bool:
    """Disable the Cognito user and revoke all their tokens.

    AdminDisableUser blocks new token issuance immediately.
    AdminUserGlobalSignOut invalidates all existing refresh tokens so the
    current access token (max 15 min TTL) cannot be silently renewed.

    Returns True only if BOTH calls succeeded (ADR-336 D2).

    It used to return None and swallow the failure, while its call site said
    "blocks token refresh immediately" — a claim that is false when Cognito is
    unreachable. The result: an offboarded employee keeps working credentials
    while the UI reports them deactivated. Returning the outcome lets the caller
    tell the truth; the caller raises the alert, because this helper has no
    session.
    """
    if not cognito_username:
        # No Cognito identity to revoke — nothing failed.
        return True
    cognito = _cognito_client()
    for action in ("admin_disable_user", "admin_user_global_sign_out"):
        try:
            getattr(cognito, action)(
                UserPoolId=settings.aws_cognito_user_pool_id,
                Username=cognito_username,
            )
        except ClientError as e:
            logger.warning("Cognito %s failed for %s: %s", action, cognito_username, e)
            return False
    return True


@router.post("/", response_model=EmployeeRecordResponse, status_code=status.HTTP_201_CREATED)
def create_employee(
    employee: EmployeeCreate,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(RoleChecker(["management", "admin"])),
    db: Session = Depends(get_db),
):
    """Create an employee record and send them a registration invite email.

    No Cognito user is created here — the employee sets their own username and
    password by following the link in the invite email (POST /registration/complete).
    """
    # ADR-285 — the rule above is for HIRING. A company migrating its existing
    # staff is not hiring: their drivers have driven for years, and
    # `trainee -> walker` is not even a promotion (it happens only by passing the
    # graduation quiz), so experienced walkers would sit through a five-phase
    # program before they could work.
    #
    # While a company has no active field staff, real roles are accepted. The
    # first import is what closes the window.
    onboarding = is_onboarding(db, caller.company_id)
    # ADR-532: the one rule for who may grant which role. It used to be two
    # checks here, and the manager one ended `and not onboarding` -- so during
    # a new company's onboarding window a manager could create an admin.
    refusal = _grant_refusal(caller.role, employee.role, onboarding)
    if refusal:
        raise HTTPException(status_code=refusal[0], detail=refusal[1])
    # ADR-538 D4: a role allowed only because the setup window is open needs the
    # caller's sign-off that every role was reviewed.
    if onboarding and employee.role in EARNED_ROLES and not employee.roles_reviewed:
        raise HTTPException(status_code=400, detail=WINDOW_SIGNOFF_REQUIRED)

    if employee.email and db.query(Employee).filter(
        Employee.company_id == caller.company_id,
        Employee.email == employee.email,
    ).first():
        raise HTTPException(status_code=400, detail="An employee with this email already exists.")

    now = datetime.now(timezone.utc)
    db_employee = Employee(
        **employee.model_dump(exclude={"roles_reviewed"}),
        company_id=caller.company_id,
        is_active=False,
        account_status="pending_verification",
        invited_at=now,
    )
    db.add(db_employee)
    db.flush()  # get db_employee.id before creating the token

    # ADR-490. Called inside BOTH branches below, above each commit, because the
    # audit row has to join the same transaction as the employee row: `get_db`
    # only closes the session, so a row added after the last commit is silently
    # discarded. The previous version had one `write_audit` AFTER both branches
    # and therefore audited neither — 22 employees existed locally with zero
    # `employee.create` rows.
    #
    # A closure rather than two copies so the two arms cannot drift.
    def _audit_created() -> None:
        write_audit(
            db=db,
            company_id=caller.company_id,
            actor_id=caller.id,
            action_type="employee.create",
            target_table="employees",
            target_id=str(db_employee.id),
            detail={
                "name": db_employee.name, "role": db_employee.role,
                "email": db_employee.email,
                # ADR-285: without this, a later reader sees a captain who never
                # earned it and no record of why they were allowed.
                **({"onboarding_window": True, "window_signoff": True}
                   if onboarding and db_employee.role in EARNED_ROLES else {}),
            },
        )

    if employee.email:
        token_str = secrets.token_urlsafe(48)
        expires_at = now + timedelta(days=settings.invite_expiry_days)
        db.add(InviteToken(
            token=token_str,
            company_id=caller.company_id,
            employee_id=db_employee.id,
            expires_at=expires_at,
        ))
        _audit_created()
        db.commit()
        db.refresh(db_employee)
        try:
            send_invite_email(
                to_email=employee.email,
                employee_name=employee.name,
                token=token_str,
            )
        except ClientError as e:
            logger.error("Invite email failed for %s: %s", employee.email, e)
            # Don't fail the request — manager can resend from the Assets UI,
            # PROVIDED they know to. ADR-336 D1 raises the platform alert so
            # somebody learns SES is down rather than each manager discovering
            # it one bounced invite at a time.
            raise_platform_alert(
                db, alert_type=EMAIL_DELIVERY_FAILED,
                company_id=caller.company_id, message=EMAIL_DOWN_MESSAGE,
            )
            # The alert is a ROW and the commit above has already run, so without
            # this it is discarded by get_db's close() exactly as the audit row
            # was (ADR-490). The ADR-336 D1 alert this path exists to raise would
            # never have reached the board — a second silent loss on the same
            # line of code, found while fixing the first.
            db.commit()
            # Re-refresh so both branches leave `db_employee` in the same state.
            # Not load-bearing — a commit expires the instance and the attribute
            # re-fetches lazily while the session is open, and FastAPI serialises
            # before get_db closes it (checked, not assumed). Symmetry so the
            # next reader does not have to work that out.
            db.refresh(db_employee)
    else:
        _audit_created()
        db.commit()
        db.refresh(db_employee)

    return db_employee


@router.post("/bulk", response_model=List[BulkImportResult], status_code=status.HTTP_200_OK)
def bulk_import_employees(
    rows: List[BulkImportRow],
    roles_reviewed: bool = Query(False, description="ADR-538 D4: the caller's sign-off that every role was reviewed"),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(RoleChecker(["management", "admin"])),
    db: Session = Depends(get_db),
):
    """Import multiple employees in one request.

    Each row is processed independently:
    - Duplicate email or discord_id check → skipped
    - Employee record created + invite token minted + SES email sent → created
    - Email send failure is logged but does not fail the row (manager can resend)

    Returns a per-row result list. Rows are capped at 200 per request.
    """
    if len(rows) > 200:
        raise HTTPException(
            status_code=400,
            detail="Maximum 200 rows per import. Split your file into smaller batches.",
        )

    now = datetime.now(timezone.utc)

    # ADR-285 — evaluated ONCE, before the loop. Per-row it would close mid-import
    # the moment the first row landed, so a 40-person migration would import one
    # employee and reject the other 39. The rows are one migration, not forty
    # independent hires.
    onboarding = is_onboarding(db, caller.company_id)
    results: List[BulkImportResult] = []

    for i, row in enumerate(rows, start=1):
        if db.query(Employee).filter(
            Employee.company_id == caller.company_id,
            Employee.email == row.email,
        ).first():
            results.append(BulkImportResult(
                row=i, status="skipped", name=row.name, email=row.email,
                reason="Email already exists.",
            ))
            continue

        # ADR-538 D7: only when the row HAS one. `Employee.discord_id == None`
        # compiles to `IS NULL`, so a row without a Discord ID "matched" every
        # employee without one -- the first such row imported and every later one
        # was skipped as "Discord ID already exists", while the invite form calls
        # the field optional.
        if row.discord_id and db.query(Employee).filter(
            Employee.company_id == caller.company_id,
            Employee.discord_id == row.discord_id,
        ).first():
            results.append(BulkImportResult(
                row=i, status="skipped", name=row.name, email=row.email,
                reason="Discord ID already exists.",
            ))
            continue

        # The SAME earned-role rule create_employee enforces. Without it this
        # endpoint was a bypass: BulkImportRow.role accepts every value in
        # RoleStr, so a CSV could create the driver, walker, trainer and captain
        # accounts the single-create path refuses — silently, one row at a time.
        #
        # Skipped rather than failing the whole import: one bad row in a
        # hundred-row CSV should not discard the ninety-nine good ones, and the
        # result row names the reason.
        # ADR-532. This only checked earned roles, with no limit on WHO was
        # granting -- a manager's CSV row with role=admin was created, and that
        # person was an admin the moment they registered.
        refusal = _grant_refusal(caller.role, row.role, onboarding)
        if not refusal and onboarding and row.role in EARNED_ROLES and not roles_reviewed:
            refusal = (400, WINDOW_SIGNOFF_REQUIRED)   # ADR-538 D4
        if refusal:
            results.append(BulkImportResult(
                row=i, status="skipped", name=row.name, email=row.email,
                reason=refusal[1],
            ))
            continue

        db_employee = Employee(
            **row.model_dump(exclude={"hr_system_id_adp"}, exclude_none=True),
            company_id=caller.company_id,
            is_active=False,
            account_status="pending_verification",
            invited_at=now,
            **({"hr_system_id_adp": row.hr_system_id_adp} if row.hr_system_id_adp else {}),
        )
        db.add(db_employee)
        try:
            db.flush()
        except Exception as e:
            db.rollback()
            logger.error("bulk import flush failed for row %d: %s", i, e)   # ADR-221: no name in logs
            results.append(BulkImportResult(
                row=i, status="failed", name=row.name, email=row.email,
                reason="Database error saving employee.",
            ))
            continue

        if row.email:
            token_str = secrets.token_urlsafe(48)
            db.add(InviteToken(
                token=token_str,
                company_id=caller.company_id,
                employee_id=db_employee.id,
                expires_at=now + timedelta(days=settings.invite_expiry_days),
            ))

        # ADR-490: ABOVE the commit, so the audit row joins the same transaction
        # as the employee it describes. It used to sit after the commit AND after
        # the invite-email block, in a session nothing committed again — so every
        # bulk-imported employee was created with no audit entry at all.
        #
        # A first version of this comment claimed the old code "would have left
        # an audit row claiming a failed import had succeeded". That is backwards:
        # the old `write_audit` sat below the `continue`, so a failed row never
        # reached it. Checked against git rather than asserted — the old defect
        # was total absence, not a false positive.
        write_audit(
            db=db,
            company_id=caller.company_id,
            actor_id=caller.id,
            action_type="employee.bulk_create",
            target_table="employees",
            target_id=str(db_employee.id),
            detail={
                "name": row.name, "role": row.role, "email": str(row.email), "row": i,
                # ADR-285 — same trace as the single-create path. A migrated
                # captain and a wrongly-created one look identical without it.
                **({"onboarding_window": True, "window_signoff": True}
                   if onboarding and row.role in EARNED_ROLES else {}),
            },
        )

        try:
            db.commit()
        except Exception as e:
            db.rollback()   # discards the audit row too, which is correct:
                            # the employee did not land, so nothing created one
            logger.error("bulk import commit failed for row %d: %s", i, e)   # ADR-221: no name in logs
            results.append(BulkImportResult(
                row=i, status="failed", name=row.name, email=row.email,
                reason="Database error saving employee.",
            ))
            continue

        if row.email:
            try:
                send_invite_email(
                    to_email=row.email,
                    employee_name=row.name,
                    token=token_str,
                )
            except ClientError as e:
                logger.error("Invite email failed for %s: %s", row.email, e)
                # ADR-336 D1/D5 — one alert type for the integration, so a bulk
                # invite that fails for 40 rows collapses to ONE incident with
                # occurrence_count=40 rather than 40 board entries.
                raise_platform_alert(
                    db, alert_type=EMAIL_DELIVERY_FAILED,
                    company_id=caller.company_id, message=EMAIL_DOWN_MESSAGE,
                )
                # ADR-490: the alert is a row and the commit above has run, so
                # without this it is discarded on teardown. On a 40-row bulk
                # import the whole point of the ADR-336 dedup is that ONE
                # incident appears — and zero appeared.
                db.commit()

        results.append(BulkImportResult(
            row=i, status="created", name=row.name, email=row.email,
        ))

    return results


PRIVILEGED_ROLES  = {"management", "admin", "dispatch"}
FIELD_ROLES       = {"driver", "walker", "trainer", "trainee"}
# Roles that only admins may create, edit, deactivate, or view
PROTECTED_ROLES   = {"management", "admin"}

# ADR-458 D2. Who appears on the escalation list. field_supervisor is in
# OVERSIGHT_ROLES but not here: it oversees the road, not the company.
ESCALATION_ROLES  = ("admin", "management")


# ADR-538 D4. The refusal when a setup-window grant arrives without the sign-off.
WINDOW_SIGNOFF_REQUIRED = (
    "This company is in its setup window, so this role can be granted directly -- but "
    "only after you review and sign off on every role: new hires start as Trainee or "
    "Driver Trainee; experienced staff keep their current role."
)

# ADR-532. Who may GRANT which role, on every path that sets one (create, bulk
# import, edit). Owner's rule, 2026-10-17: admins hire any hiring role; managers
# hire trainees, driver trainees and dispatchers; nobody else hires at all
# (RoleChecker on each route). Earned roles (EARNED_ROLES) are not in either
# list: they are reached by training or promotion, and only the onboarding
# window (ADR-285) admits them directly.
#
# Mirrored by CREATABLE_ROLES / MANAGEMENT_CREATABLE_ROLES in
# frontend/src/pages/Assets.tsx; tests/routers/test_adr532_role_grants.py holds
# the two equal.
ROLE_GRANTS: dict[str, frozenset[str]] = {
    # ADR-538 D2: field_supervisor moved to EARNED_ROLES (promoted from driver).
    "admin": frozenset({"trainee", "driver_trainee", "dispatch", "management", "admin"}),
    "management": frozenset({"trainee", "driver_trainee", "dispatch"}),
}

# What management may never grant, on any path, onboarding or not.
# ADR-538 D2: field_supervisor is a field role now (one notch below manager),
# granted by a manager inside the setup window, by promotion outside it.
_MANAGEMENT_NEVER_GRANTS = frozenset({"management", "admin"})


def _grant_refusal(caller_role: str, role: str, onboarding: bool):
    """(status, detail) if `caller_role` may not CREATE someone as `role`, else None.

    Returned rather than raised so bulk import can skip one row with the reason
    instead of failing the batch (the ADR-285 shape).
    """
    if caller_role == "management" and role in _MANAGEMENT_NEVER_GRANTS:
        return (status.HTTP_403_FORBIDDEN,
                "Managers cannot invite managers or admins.")
    if role in EARNED_ROLES:
        if onboarding:
            return None  # ADR-285: migrating existing staff is not hiring
        return (status.HTTP_400_BAD_REQUEST, EARNED_ROLES[role])
    if role not in ROLE_GRANTS.get(caller_role, frozenset()):
        return (status.HTTP_403_FORBIDDEN,
                "Managers can invite trainees, driver trainees and dispatchers."
                if caller_role == "management"
                else "You cannot invite someone with that role.")
    return None


def _edit_grant_refusal(caller_role: str, new_role: str, onboarding: bool = False):
    """(status, detail) if `caller_role` may not CHANGE someone to `new_role`.

    Wider than create on purpose (ADR-532 D3): edit is where an existing
    employee's role is corrected, so earned roles stay settable here. What it
    must never allow is a manager granting a role at or above their own.
    """
    if caller_role == "admin":
        return None
    # ADR-537 D1: training is an Amazon requirement. A manager cannot edit someone
    # straight into an earned role (walker/trainer/driver/captain); those are
    # reached by the graduation quiz, the driver promotion, or the promote buttons.
    # Admins keep it for genuine corrections (owner, 2026-10-18).
    # ADR-538 D3: inside the setup window a manager may set them (existing staff).
    if caller_role == "management" and new_role in EARNED_ROLES and not onboarding:
        return (status.HTTP_403_FORBIDDEN,
                "Only admins can set walker, trainer, driver, captain or field supervisor "
                "directly. Use the promote buttons, or let training and the graduation quiz do it.")
    if caller_role == "management" and new_role not in _MANAGEMENT_NEVER_GRANTS:
        return None
    return (status.HTTP_403_FORBIDDEN,
            "Only admins can give someone a management or admin role.")


def _assert_not_protected(caller_groups: set, target_role: str) -> None:
    """Raise 403 if target has a protected role and caller is not admin."""
    if target_role in PROTECTED_ROLES and "admin" not in caller_groups:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can modify management or admin accounts.",
        )


@router.get("/setup-window")
def get_setup_window(
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(RoleChecker(["management", "admin"])),
    db: Session = Depends(get_db),
):
    """The company's setup window (ADR-538): open while 10 or fewer people have a
    sign-in account and the company is within 30 days of creation. Feeds the
    People page banner, the widened role lists and the sign-off dialog. The
    server re-checks on every grant; this only decides what to show."""
    w = setup_window(db, caller.company_id)
    return {**w, "closes_at": w["closes_at"].isoformat() if w["closes_at"] else None}


def _adp_connected(db: Session, company_id) -> bool:
    """ADR-567: the company's legal names come from ADP (an enabled integration)."""
    from app.models.adp_integration import ADPIntegration
    return db.query(ADPIntegration.id).filter(
        ADPIntegration.company_id == company_id, ADPIntegration.is_enabled.is_(True)).first() is not None


def _for_dispatch(e: Employee) -> EmployeeResponse:
    """ADR-567 D8: dispatch sees the shown name, never the username (built from
    the legal name)."""
    return EmployeeResponse.model_validate(e).model_copy(update={"username": None})


@router.get(
    "/",
    response_model=list[
        Union[EmployeeRecordResponse, EmployeeResponse, EmployeeOfficeResponse, EmployeePublicResponse]
    ],
    # ADR-458 D1. Three shapes by caller role and row role. Declared as a
    # union because a single response_model makes FastAPI coerce every row to
    # it, which would undo the redaction the handler just applied.
)
def get_all_employees(
    caller: Employee = Depends(get_caller_employee),
    pg: Pagination = Depends(),
    include_inactive: bool = False,
    db: Session = Depends(get_db),
):
    """Return employees scoped to the caller's company.

    Active-only by default; pass ?include_inactive=true for admin/management.
    Management/admin/dispatch receive the full record; field staff receive a
    redacted response with phone, email, and cognito_sub removed.
    """
    is_privileged = caller.role in PRIVILEGED_ROLES

    q = db.query(Employee).filter(Employee.company_id == caller.company_id)
    if include_inactive:
        if caller.role not in {"management", "admin"}:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
    else:
        q = q.filter(Employee.is_active == True)

    employees = pg.apply(q).all()

    if not is_privileged:
        return [EmployeePublicResponse.model_validate(e) for e in employees]

    # ADR-458 D1. Office rows appear on the roster but WITHOUT contact details.
    #
    # Two things changed here and they pull in opposite directions. Management
    # used to be filtered away from these rows entirely (`role.notin_(
    # PROTECTED_ROLES)`), so a manager could not see that an owner existed --
    # the role most likely to need to escalate could not find anyone to
    # escalate to. They now see the row.
    #
    # And dispatch used to receive the full record, so an owner's personal
    # mobile sat behind a click-to-copy button on a routine screen. It no
    # longer does. Reaching an owner is GET /employees/escalation: deliberate,
    # role-gated and audited.
    #
    # An admin still sees everything: they are the role the escalation list
    # exists to reach, and hiding peers from them buys nothing.
    # ADR-567 D5/D8: management and admin get the legal name (ADP and scorecard
    # checks compare against it); dispatch gets the shown name only, and no
    # username (it is built from the legal name). Null for every row, so its
    # absence marks nobody.
    if caller.role == "admin":
        return [EmployeeRecordResponse.model_validate(e) for e in employees]
    if caller.role == "dispatch":
        return [
            EmployeeOfficeResponse.model_validate(e)
            if e.role in PROTECTED_ROLES
            else _for_dispatch(e)
            for e in employees
        ]

    return [
        EmployeeOfficeResponse.model_validate(e)
        if e.role in PROTECTED_ROLES
        else EmployeeRecordResponse.model_validate(e)
        for e in employees
    ]


@router.get("/escalation", response_model=List[EmployeeEscalationResponse])
@limiter.limit("20/minute")
def get_escalation_contacts(
    request: Request,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(RoleChecker(["dispatch", "management", "admin"])),
    db: Session = Depends(get_db),
):
    """Who to call when something is wrong (ADR-458 D2).

    The roster answers "who works here". This answers "who do I escalate to",
    and they are different artifacts with different audiences -- which is why
    the contact details live here rather than on a screen people read all day.

    Gate is broad on purpose. Dispatch is who is on shift at 4am when a truck
    is stranded, and a list they cannot open is useless exactly when it is
    needed. Management is included because the previous arrangement filtered
    admin rows away from them entirely: the role most likely to need to
    escalate could not see anyone to escalate to.

    Ordered admin first: an ordered list is the useful form of "who do I call",
    and alphabetical within a role keeps it stable between calls.
    """
    contacts = (
        db.query(Employee)
        .filter(
            Employee.company_id == caller.company_id,
            Employee.is_active == True,
            Employee.role.in_(ESCALATION_ROLES),
        )
        .all()
    )
    # admin before management, then by name. Done in Python because the
    # ordering is a two-key rule over a small list, not a query concern.
    rank = {"admin": 0, "management": 1}
    contacts.sort(key=lambda e: (rank.get(e.role, 9), (e.name or "").lower()))

    # ADR-458 D3. The first READ this codebase audits, and the reason the
    # endpoint is defensible: a gate that leaves no trace cannot answer "who
    # looked at the owner's mobile, and when".
    #
    # The row records the actor and how many rows were returned -- NOT the
    # numbers. Logging those would copy the PII being protected into a second
    # store, which is the Dimension 7 failure this decision exists to avoid.
    write_audit(
        db=db,
        company_id=caller.company_id,
        actor_id=caller.id,
        action_type="employee.escalation_viewed",
        target_table="employees",
        target_id=str(caller.company_id),
        detail={"returned": len(contacts)},
    )
    db.commit()

    return [EmployeeEscalationResponse.model_validate(e) for e in contacts]


@router.get("/mfa-deadline", response_model=List[EmployeeMfaDeadlineResponse])
@limiter.limit("20/minute")
def get_mfa_deadline(
    request: Request,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(RoleChecker(["dispatch", "management", "admin"])),
    db: Session = Depends(get_db),
):
    """Which field staff are about to be walled (ADR-470 D2).

    ADR-377 gives field roles 14 days; ADR-465 makes the wall unskippable when
    that window shuts. Nobody could see it coming: the countdown renders only
    inside the app, and ADR-467's panel is scoped to privileged roles because
    those are the accounts that can be locked OUT. So the first signal that six
    walkers are blocked on Monday was routes not starting.

    Gate is BROADER than ADR-467's admin-only enrolment view, on ADR-458 D2's
    reasoning: dispatch is who is on shift at 04:00 when somebody cannot start,
    and a list they cannot open is useless exactly when it is needed. Widening
    costs nothing here because this endpoint makes NO Cognito call -- see below.

    Not audited, unlike the escalation list (ADR-458 D3) and the enrolment panel
    (ADR-467 D1). Both of those expose something about a person: a personal
    mobile number, or whether their account is unprotected. This exposes a
    deadline. Auditing it would add a write to a read that reveals nothing worth
    recording, and bury the rows that do matter.

    CHEAP BY CONSTRUCTION. `days_remaining` derives entirely from
    `mfa_grace_started_at`, so the whole answer is one indexed query. A clock
    that never started is excluded by the NOT NULL term rather than evaluated
    and discarded -- and as of ADR-470 that is most of the roster, because the
    clock only starts when someone first opens a client.
    """
    now = datetime.now(timezone.utc)
    grace = mfa_status.DEFAULT_MFA_GRACE_DAYS
    # Mirrors the task's bands (ADR-470 D1). Anything sooner than this is not
    # yet actionable for dispatch; anything past it is already blocked.
    horizon_days = 3

    window_opens = now - timedelta(days=grace - horizon_days)
    deadline_at = now - timedelta(days=grace)

    rows = (
        db.query(Employee)
        .filter(
            Employee.company_id == caller.company_id,
            Employee.is_active == True,  # noqa: E712
            Employee.mfa_grace_started_at.isnot(None),
            Employee.mfa_grace_started_at <= window_opens,
            # Already past it: blocked NOW, not "about to be". They belong on
            # ADR-467's panel, and listing them here would read as a warning
            # about something that has already happened.
            Employee.mfa_grace_started_at > deadline_at,
        )
        .all()
    )

    out: list[EmployeeMfaDeadlineResponse] = []
    for emp in rows:
        # Role-tier, not the Cognito group: this is a DB row, not a token.
        if mfa_status.tier_for(emp.role, {emp.role}) != "field":
            continue
        status_obj = mfa_status.evaluate(
            role=emp.role, enrolled=False,
            grace_started_at=emp.mfa_grace_started_at,
            grace_days=grace, groups={emp.role},
        )
        if status_obj.days_remaining is None:
            continue
        out.append(EmployeeMfaDeadlineResponse(
            id=emp.id, name=emp.name, role=emp.role,
            days_remaining=status_obj.days_remaining,
        ))

    # Soonest first: this is a worklist, and the person with one day left is the
    # one to call.
    out.sort(key=lambda r: (r.days_remaining, r.name.lower()))
    return out


class MfaResetRequestRow(BaseModel):
    """One employee waiting for a two-factor reset (ADR-551 D3)."""
    employee_id: UUID
    name: str
    role: str
    requested_at: datetime


@router.get("/mfa-reset-requests", response_model=List[MfaResetRequestRow])
def list_mfa_reset_requests(
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(RoleChecker(["admin", "management"])),
    db: Session = Depends(get_db),
):
    """Who in this company asked for a two-factor reset (ADR-551 D3).

    The same people who can do the reset (the /{id}/mfa/reset gate). The
    ADR-467 list covers only privileged roles; a walker who lost their phone
    needs to be seen too, so this lists any role. Company-scoped (D1).
    """
    from app.services import mfa_reset_requests
    cutoff = datetime.now(timezone.utc) - mfa_reset_requests.SHOWN_FOR
    from app.models.mfa_reset_request import MfaResetRequest
    rows = (db.query(MfaResetRequest, Employee)
            .join(Employee, Employee.cognito_sub == MfaResetRequest.cognito_sub)
            .filter(MfaResetRequest.company_id == caller.company_id,
                    Employee.company_id == caller.company_id,
                    MfaResetRequest.status == "pending",
                    MfaResetRequest.requested_at >= cutoff)
            .order_by(MfaResetRequest.requested_at).all())
    return [MfaResetRequestRow(employee_id=e.id, name=e.name, role=e.role, requested_at=r.requested_at)
            for r, e in rows]


@router.get("/mfa-enrolment", response_model=List[EmployeeMfaEnrolmentResponse])
@limiter.limit("20/minute")
def get_mfa_enrolment(
    request: Request,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(RoleChecker(["admin"])),
    db: Session = Depends(get_db),
):
    """Which privileged accounts can actually sign in (ADR-467 D1).

    The roster cannot answer this. A privileged account that spent ADR-459's
    one-time enrolment pass without enrolling is refused by PreAuthentication on
    every later attempt, and because a refused sign-in issues no token, no
    request reaches get_caller_employee and `account_status` never leaves
    'pending_verification'. The row reads "Registered" forever -- which looks
    like "waiting on the user", the one state an admin correctly ignores.

    ADMIN ONLY, deliberately. Enrolment state is a security property of another
    person's account, and dispatch has no action to take on it.

    WHY THIS IS AN ENDPOINT AND NOT A ROSTER FIELD. Probed against the live pool
    before designing it: `list_users` returns Attributes, Enabled,
    UserCreateDate, UserLastModifiedDate, UserStatus, Username -- and NO
    UserMFASettingList. It does not return custom:mfa_first_seen either (the
    custom: list came back empty for an account that is certainly enrolled).
    So neither signal is bulk-readable, enrolment is one admin_get_user per
    user, and the roster loads ?limit=500. Inlining it would be 500 sequential
    AWS round-trips on a page admins open daily.

    Scoping is what makes it affordable: only MFA_PRIVILEGED_ROLES can be locked
    out this way, which is a handful of rows.
    """
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError

    from app.services import mfa_status

    # Company-scoped (Dimension 1) AND role-scoped: the field roster is not just
    # unaffordable to check, it is not at risk -- field accounts have a grace
    # window and are never refused for holding no factor.
    rows = (
        db.query(Employee)
        .filter(
            Employee.company_id == caller.company_id,
            Employee.role.in_(mfa_status.MFA_PRIVILEGED_ROLES),
        )
        .all()
    )

    try:
        client = boto3.client("cognito-idp", region_name=settings.aws_region)
    except (ClientError, BotoCoreError) as exc:
        # No client: report every row as unknown rather than 500ing. An admin
        # opening this during an incident needs the list of accounts even when
        # the state beside them cannot be read.
        logger.warning("mfa enrolment: no cognito client: %s", type(exc).__name__)
        client = None

    # ADR-551 D3: who on this list asked for a two-factor reset.
    from app.services import mfa_reset_requests
    requested = mfa_reset_requests.pending_since(db, [e.cognito_sub for e in rows if e.cognito_sub])

    rank = {"admin": 0, "management": 1, "dispatch": 2}
    rows.sort(key=lambda e: (rank.get(e.role, 9), (e.name or "").lower()))

    out: list[EmployeeMfaEnrolmentResponse] = []
    for emp in rows:
        enrolled: bool | None = None
        pass_spent = False
        username = cognito_username_for(emp)
        if client is not None and username:
            try:
                # ONE call per user carries both signals: UserMFASettingList for
                # the factor, UserAttributes for the pass. Reading them
                # separately would double the round-trips for nothing.
                resp = client.admin_get_user(
                    UserPoolId=settings.aws_cognito_user_pool_id,
                    Username=username,
                )
                # Mirrors mfa_status.is_enrolled rather than re-deriving it, so
                # the two surfaces cannot disagree about who is enrolled.
                enrolled = bool(resp.get("UserMFASettingList"))
                attrs = {a["Name"]: a.get("Value")
                         for a in resp.get("UserAttributes", [])}
                # ADR-548 D3: "spent" now means the 24-hour window has CLOSED.
                # Stamped-but-open is someone mid-setup, not a lockout, and
                # the Assets page must not tell an admin otherwise.
                window, _ends = mfa_status.setup_window_ends_at(
                    attrs.get(mfa_status.FIRST_SEEN_ATTR))
                pass_spent = window == "closed"
            except (ClientError, BotoCoreError) as exc:
                # Per-row, so one unreadable account does not blank the others.
                # Stays None -- "could not tell", never "not enrolled".
                logger.warning(
                    "mfa enrolment: could not read %s: %s",
                    emp.id, type(exc).__name__,
                )

        out.append(EmployeeMfaEnrolmentResponse(
            id=emp.id, name=emp.name, role=emp.role,
            pass_spent=pass_spent, enrolled=enrolled,
            account_status=emp.account_status,
            reset_requested_at=requested.get(emp.cognito_sub) if emp.cognito_sub else None,
        ))

    # Audited for the same reason ADR-458 D3 audits the escalation list: this
    # reads a security property of other people's accounts, and a gate that
    # leaves no trace cannot answer "who looked, and when". Counts only -- never
    # which accounts are unprotected, which would put a target list in a second
    # store.
    write_audit(
        db=db,
        company_id=caller.company_id,
        actor_id=caller.id,
        action_type="employee.mfa_enrolment_viewed",
        target_table="employees",
        target_id=str(caller.company_id),
        detail={
            "returned": len(out),
            "unenrolled": sum(1 for r in out if r.enrolled is False),
            "unknown": sum(1 for r in out if r.enrolled is None),
        },
    )
    db.commit()

    return out


@identity_router.get("/me", response_model=EmployeeRecordResponse)
def get_my_employee(
    caller: Employee = Depends(get_caller_employee),
):
    """Return the Employee record for the currently authenticated user."""
    return EmployeeRecordResponse.model_validate(caller)   # ADR-567: the person sees both names


def _with_setup_window(out: dict, username: str | None) -> dict:
    """Add `setup_window_ends_at` (ADR-548 D3): when an unenrolled privileged
    account's enrolment window closes, so the wall can say so instead of
    promising a sign-out is free. Null for everyone else, or when unreadable --
    the page then shows no deadline rather than a wrong one."""
    out["setup_window_ends_at"] = None
    if out.get("tier") == "privileged" and out.get("enrolled") is False:
        state, ends = mfa_status.read_setup_window(username)
        if state == "open" and ends is not None:
            out["setup_window_ends_at"] = ends.isoformat()
    return out


@identity_router.get("/me/mfa-status")
def get_my_mfa_status(
    db: Session = Depends(get_db),
    # OPTIONAL, not get_caller_employee: a platform account (super_admin,
    # platform_support) has no Employee row BY DESIGN -- it is not staff and
    # must not appear in the roster or headcount. Requiring one 403s exactly the
    # accounts the privileged tier exists to protect. Measured on prod: deleting
    # `adon`'s stray roster row made this endpoint refuse the platform owner.
    caller: Employee | None = Depends(get_caller_employee_optional),
    current_user: dict = Depends(get_current_user),
):
    """This user's MFA obligation, and how long they have left (ADR-377 D2).

    Also STARTS the grace clock. It is stamped here rather than at account
    creation because anchoring the deadline to creation would put every existing
    employee instantly past it -- the staging accounts date from 2026-05-07 --
    which is a day-one mass lockout.

    Stamped ONCE. A later call must not extend the window, so the write is
    guarded on the column still being NULL rather than overwritten each time.
    """
    groups = set(current_user.get("cognito_groups", []))

    # A platform account with no Employee row. Its tier comes entirely from the
    # Cognito group, and it has no row on which to stamp a grace clock -- which
    # is correct, because the privileged tier has no grace period to track.
    if caller is None:
        if not (groups & mfa_status.MFA_PRIVILEGED_ROLES):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No employee record found for your account. Contact your manager.",
            )
        enrolled = mfa_status.is_enrolled(
            current_user.get("id"), current_user.get("username"),
        )
        return _with_setup_window(mfa_status.evaluate(
            role="", enrolled=True if enrolled is None else enrolled,
            grace_started_at=None, groups=groups,
        ).as_dict(), current_user.get("username"))

    # ADR-374 — a MachineCaller has no role, no cognito_sub and no grace column.
    # Reaching for any of them here is the exact AttributeError that 500'd the
    # bot's morning fetch. A machine authenticates by scope and never enrols, so
    # the question does not apply to it.
    if getattr(caller, "role", None) is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="MFA status applies to user accounts, not machine clients.",
        )

    # ADR-380 F7, missed here. This passed the caller's DISCORD id as the USERNAME
    # argument -- a Discord snowflake, not a Cognito username, and None for every
    # employee who has not linked Discord. It then fell back to cognito_sub,
    # which is not a valid Username in this pool either:
    #
    #     admin_get_user --username <sub>          -> UserNotFoundException
    #     admin_get_user --username walker.test    -> the user
    #
    # So is_enrolled returned None for EVERY field employee, and the banner
    # renders nothing on None by design (null means "could not read", never "not
    # enrolled"). The countdown was invisible for the entire population it
    # exists to warn -- the same silence ADR-381 D1 was written to end.
    #
    # cognito_username_for is the resolver the F7 sweep introduced; this call
    # site predates it and was not converted.
    enrolled = mfa_status.is_enrolled(
        caller.cognito_sub, cognito_username_for(caller),
    )

    # None means Cognito could not be reached. Treat as enrolled for gating
    # purposes: an AWS hiccup must never block a shift. The banner simply does
    # not appear that request.
    if enrolled is None:
        status_obj = mfa_status.evaluate(
            role=caller.role, enrolled=True, grace_started_at=caller.mfa_grace_started_at,
            groups=groups,
        )
        out = status_obj.as_dict()
        out["enrolled"] = None      # honest: unknown, not confirmed
        out["setup_window_ends_at"] = None
        return out

    if not enrolled and caller.mfa_grace_started_at is None:
        # First sign-in after enforcement shipped: the window opens now.
        caller.mfa_grace_started_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(caller)

    # ADR-377 D3 — trim the remembered-device fleet on the way past.
    #
    # Here rather than in a Cognito trigger because no trigger fires on
    # ConfirmDevice: PreAuthentication runs BEFORE the device is confirmed, so
    # it cannot see the device that just pushed the user over the cap. This
    # endpoint is called by both clients right after sign-in, which is the first
    # moment the new device exists.
    #
    # Never raises (see enforce_cap): an AWS hiccup must degrade to one extra
    # remembered device, not to a failed sign-in.
    device_fleet.enforce_cap(
        # Same bug as the enrolment lookup above, same fix. This passed a
        # Discord id as the Cognito Username, so AdminListDevices raised
        # UserNotFoundException -- and enforce_cap fails SOFT by design, so it
        # returned 0 and logged a warning nobody reads. Device eviction has
        # therefore never trimmed anything in production.
        username=cognito_username_for(caller) or str(caller.cognito_sub),
        pool_id=settings.aws_cognito_user_pool_id,
        region=settings.aws_region,
    )

    grace_days = mfa_status.DEFAULT_MFA_GRACE_DAYS
    status_obj = mfa_status.evaluate(
        role=caller.role,
        enrolled=enrolled,
        grace_started_at=caller.mfa_grace_started_at,
        grace_days=grace_days,
        # Groups, not just the role: `super_admin` and `platform_support` are
        # rejected by Employee.VALID_ROLES, so they arrive ONLY as Cognito
        # groups. Prod's `adon` is super_admin in Cognito and `trainee` on its
        # Employee row -- role alone put it on the field tier.
        groups=groups,
    )
    return _with_setup_window(status_obj.as_dict(), cognito_username_for(caller))


@router.get("/by-discord/{discord_id}", response_model=EmployeePublicResponse)
def get_employee_by_discord(
    discord_id: str,
    caller: Employee = Depends(get_caller_employee),
    # ADR-363 — the bot resolves a Discord id to an employee on every command.
    current_user: dict = Depends(RoleChecker(
        list(PRIVILEGED_ROLES | FIELD_ROLES),
        machine_scopes=["asheflow.bot/employees.read"],
    )),
    db: Session = Depends(get_db),
):
    """Fetch an employee by Discord ID. Used by the bot on member-join to assign roles."""
    employee = db.query(Employee).filter(
        Employee.discord_id == discord_id,
        Employee.company_id == caller.company_id,
    ).first()
    if not employee:
        raise HTTPException(status_code=404, detail="No employee found with that Discord ID.")
    caller_groups = set(current_user.get("cognito_groups", []))
    if caller_groups & PRIVILEGED_ROLES:
        return EmployeeResponse.model_validate(employee)
    return EmployeePublicResponse.model_validate(employee)


@router.get("/{employee_id}", response_model=Union[EmployeeRecordResponse, EmployeeResponse, EmployeePublicResponse])
def get_employee(
    employee_id: UUID,
    caller: Employee = Depends(get_caller_employee),
    current_user: dict = Depends(RoleChecker(list(PRIVILEGED_ROLES | FIELD_ROLES))),
    db: Session = Depends(get_db),
):
    """Fetch a single employee by ID.

    Management/admin/dispatch receive the full record. Field staff receive the
    redacted version without phone, email, and cognito_sub.
    """
    employee = db.query(Employee).filter(
        Employee.id == employee_id,
        Employee.company_id == caller.company_id,
    ).first()
    if not employee:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")

    caller_groups = set(current_user.get("cognito_groups", []))

    # Management callers cannot retrieve management or admin records
    if "management" in caller_groups and "admin" not in caller_groups:
        _assert_not_protected(caller_groups, employee.role)

    # ADR-567 D5: the legal name only to management and admin.
    if caller_groups & {"management", "admin"}:
        return EmployeeRecordResponse.model_validate(employee)
    if caller_groups & PRIVILEGED_ROLES:
        return _for_dispatch(employee)
    return EmployeePublicResponse.model_validate(employee)


@router.put("/{employee_id}", response_model=EmployeeRecordResponse)
def update_employee(
    employee_id: UUID,
    employee: EmployeeUpdate,
    caller: Employee = Depends(get_caller_employee),
    current_user: dict = Depends(RoleChecker(["management", "admin"])),
    db: Session = Depends(get_db),
):
    """Update an existing employee's fields.

    When the role changes, the employee is removed from their old Cognito group
    and added to the new one so permissions take effect on their next token refresh.
    """
    db_employee = db.query(Employee).filter(
        Employee.id == employee_id,
        Employee.company_id == caller.company_id,
    ).first()
    if not db_employee:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")

    caller_groups = set(current_user.get("cognito_groups", []))
    _assert_not_protected(caller_groups, db_employee.role)

    updates = employee.model_dump(exclude_unset=True)
    new_role  = updates.get("role")
    new_email = updates.get("email")
    old_role  = db_employee.role
    old_email = db_employee.email

    # ADR-532. The check above is on the CURRENT role only. Nothing checked the
    # role being granted, so a manager could edit any driver to role=admin and
    # the Cognito group sync below made it real.
    if new_role and new_role != old_role:
        refusal = _edit_grant_refusal(caller.role, new_role,
                                      onboarding=is_onboarding(db, caller.company_id))
        if refusal:
            raise HTTPException(status_code=refusal[0], detail=refusal[1])

    # ADR-563 D4: on an active account this edit only ever changed the database
    # copy -- Cognito kept the old address, so codes went to one inbox while the
    # app showed another (staging walker.test). Active accounts change email
    # through the confirmed flow; pending/registered keep the correction path.
    if (new_email and (new_email or "").lower() != (old_email or "").lower()
            and db_employee.account_status == "active"):
        raise HTTPException(
            status_code=409,
            detail="Use Change email for this person. It sends a confirmation link to the new address.",
        )

    # ADR-567: `name` here is the LEGAL name of record.
    legal_before = None
    if "name" in updates:
        new_name = (updates.get("name") or "").strip()
        if (db_employee.chosen_name and new_name == db_employee.chosen_name
                and new_name != db_employee.legal_name):
            # A client that loaded the shown name (the chosen one) and sent it
            # back unchanged. Writing it would replace the legal name with the
            # chosen one; an older web or mobile build does exactly this.
            updates.pop("name")
        elif new_name != db_employee.legal_name:
            # Owner, 2026-10-22: where ADP is connected it is the only source
            # of the legal name; AsheFlow never edits it.
            if _adp_connected(db, caller.company_id):
                raise HTTPException(
                    status_code=409,
                    detail="This company's legal names come from ADP. Change it in ADP; the next sync updates it here.",
                )
            legal_before = db_employee.legal_name

    for key, value in updates.items():
        setattr(db_employee, key, value)

    # ADR-445 D4. The flag describes the address that bounced, so a NEW address
    # starts clean. Cleared on the change rather than on the next successful
    # send: there are eight send call sites and one place the address changes,
    # and a flag that outlives its cause is one admins learn to ignore.
    if new_email and new_email != old_email:
        db_employee.email_bounced_at = None
        db_employee.email_bounce_type = None

    # ADR-490: above the commit that lands the field changes this row DESCRIBES.
    # It used to sit at the end of the function, after both commits and after the
    # Cognito group sync — so the row was added to a session that nothing
    # committed again, and `get_db`'s close() discarded it. Every employee edit
    # since this code shipped has gone unrecorded.
    #
    # Deliberately NOT at the end: the later commit (the invite-token re-issue)
    # lands a different thing, and an audit row placed above THAT would describe
    # the field changes while riding a transaction that may not include them.
    write_audit(
        db=db,
        company_id=caller.company_id,
        actor_id=caller.id,
        action_type="employee.update",
        target_table="employees",
        target_id=str(db_employee.id),
        detail={**{k: str(v) if v is not None else None for k, v in updates.items()},
                # ADR-567: a correction to the legal name records what it was.
                **({"legal_name_before": legal_before} if legal_before is not None else {})},
    )

    db.commit()
    db.refresh(db_employee)

    cognito = _cognito_client()

    # Wrong-email recovery — only valid while the account is still pending.
    # Delete the old Cognito user and recreate with the corrected email so a
    # fresh invite is sent. Active accounts must use the Cognito console.
    # ADR-468 D2. This arm is FOR the registered case (its own comment says
    # "ADR-380 F7 -- REGISTERED"), and it reached it via pending_verification +
    # username because that WAS how a registered row looked. Under ADR-468 D1 the
    # status is 'registered', so the old test matched nothing and every wrong-email
    # recovery on a registered employee fell through to the shell-account arm
    # below -- which deletes by email, a Username that registered account does not
    # have.
    if (new_email and new_email != old_email
            and db_employee.account_status in ("pending_verification", "registered")
            and db_employee.username):
        # ADR-380 F7 — REGISTERED. Their Cognito Username is the derived
        # firstname.lastname and does not change with their email, so this is an
        # attribute update on the account they already have.
        #
        # The old code deleted by `Username=old_email`, which raised
        # UserNotFoundException into a warning, then created a SECOND Cognito
        # user named after the new email. The real account stayed live under the
        # old address and nothing pointed at the new one.
        #
        # No re-invite: they already registered and hold credentials. Use
        # resend-credentials if they need new ones.
        try:
            cognito.admin_update_user_attributes(
                UserPoolId=settings.aws_cognito_user_pool_id,
                Username=db_employee.username,
                UserAttributes=[
                    {"Name": "email", "Value": new_email},
                    # ADR-564: NOT verified by an admin typing it. They haven't
                    # signed in yet; resending their credentials to this
                    # address and their signing in with them verifies it (the
                    # sign-in Lambda). Forgot-password isn't needed meanwhile:
                    # they have a temporary password.
                    {"Name": "email_verified", "Value": "false"},
                ],
            )
        except ClientError as e:
            logger.error(
                "Cognito email update failed for employee %s: %s",
                db_employee.id, e.response["Error"]["Code"],
            )
            raise HTTPException(
                status_code=502,
                detail="Email updated in DB but Cognito update failed. Contact support.",
            )

    # ADR-468 D2. Stays on pending_verification alone, and that is now EXACT
    # rather than incidental: this arm is the shell account with no username, and
    # 'registered' by definition has one. The arm above takes the other case.
    elif new_email and new_email != old_email and db_employee.account_status == "pending_verification":
        # NOT registered: no Employee.username, so the Cognito Username IS the
        # email. The account is a shell, and recreating it is what sends a fresh
        # invite to the corrected address.
        try:
            if old_email:
                cognito.admin_delete_user(
                    UserPoolId=settings.aws_cognito_user_pool_id,
                    Username=old_email,
                )
        except ClientError as e:
            logger.warning("Could not delete old Cognito user %s: %s", old_email, e)

        try:
            response = cognito.admin_create_user(
                UserPoolId=settings.aws_cognito_user_pool_id,
                Username=new_email,
                UserAttributes=[
                    {"Name": "email", "Value": new_email},
                    {"Name": "name",  "Value": db_employee.name},
                ],
                # ADR-444 D2. Cognito's stock invite is a bare one-liner from an
                # address nobody recognises. We send the same branded invite a
                # new hire gets — this person is unregistered, so an invite is
                # exactly the artefact they should have had the first time.
                MessageAction="SUPPRESS",
            )
            new_sub = next(
                (a["Value"] for a in response["User"]["Attributes"] if a["Name"] == "sub"),
                None,
            )
            db_employee.cognito_sub = new_sub
            db_employee.invited_at = datetime.now(timezone.utc)

            # The old address's token must die with the old address, or a
            # correction made because the first address was WRONG leaves the
            # wrong recipient holding a live registration link.
            db.query(InviteToken).filter(
                InviteToken.employee_id == db_employee.id,
                # Redundant — db_employee was already fetched scoped to
                # caller.company_id — and kept anyway: a delete is the wrong
                # place to rely on a guarantee established 500 lines earlier.
                InviteToken.company_id == caller.company_id,
            ).delete()
            token_str = secrets.token_urlsafe(48)
            db.add(InviteToken(
                token=token_str,
                company_id=db_employee.company_id,
                employee_id=db_employee.id,
                expires_at=datetime.now(timezone.utc)
                + timedelta(days=settings.invite_expiry_days),
            ))
            db.commit()
            db.refresh(db_employee)

            group = ROLE_TO_COGNITO_GROUP.get(db_employee.role)
            if group:
                cognito.admin_add_user_to_group(
                    UserPoolId=settings.aws_cognito_user_pool_id,
                    Username=new_email,
                    GroupName=group,
                )
        except ClientError as e:
            logger.error("Cognito re-invite for corrected email %s failed: %s", new_email, e.response["Error"]["Code"])
            raise HTTPException(
                status_code=502,
                detail="Email updated in DB but Cognito re-invite failed. Contact support.",
            )

        # Outside the Cognito try: a send failure is not a 502. The shell and
        # the token are correct, so the operator's remedy is Resend Invite
        # (ADR-442), not redoing the correction.
        try:
            send_invite_email(
                to_email=new_email,
                employee_name=db_employee.name,
                token=token_str,
            )
        except ClientError as e:
            logger.error(
                "Invite email for corrected address failed (employee %s): %s",
                db_employee.id, e.response.get("Error", {}).get("Code", "Unknown"),
            )

    # Sync Cognito group when role changes on an account that HAS one.
    #
    # ADR-468 D2. Was `!= "pending_verification"`, which happened to be true only
    # for 'active' -- so a REGISTERED employee (Cognito account created, not yet
    # signed in) never had their group synced, and their very first token carried
    # the old role. The condition means "a Cognito account exists to sync", which
    # is `username`, and cognito_username_for on the next line already relies on
    # exactly that.
    elif new_role and new_role != old_role and db_employee.email and db_employee.username:
        # ADR-380 F7 — was `db_employee.email`, which is only the Cognito
        # Username BEFORE registration. On a registered employee this raised
        # UserNotFoundException into the log below and the group never synced,
        # so their token claims kept the old role indefinitely.
        cognito_username = cognito_username_for(db_employee)
        old_group = ROLE_TO_COGNITO_GROUP.get(old_role)
        new_group = ROLE_TO_COGNITO_GROUP.get(new_role)
        try:
            if old_group:
                cognito.admin_remove_user_from_group(
                    UserPoolId=settings.aws_cognito_user_pool_id,
                    Username=cognito_username,
                    GroupName=old_group,
                )
            if new_group:
                cognito.admin_add_user_to_group(
                    UserPoolId=settings.aws_cognito_user_pool_id,
                    Username=cognito_username,
                    GroupName=new_group,
                )
        except ClientError as e:
            logger.error(
                "Cognito group sync failed for employee %s (old=%s new=%s): %s",
                db_employee.id, old_group, new_group, e,
            )

    return db_employee


@router.post("/{employee_id}/discord-invite", status_code=status.HTTP_200_OK)
def resend_discord_invite(
    employee_id: UUID,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(RoleChecker(["management", "admin"])),
):
    """Send this employee their Discord invite again (ADR-443).

    THE ONE SENDER WITH NO RECOVERY PATH. The invite fires once, inside the
    block that flips an employee from pending_verification to active on first
    login — so the condition guarding it is false forever after. It runs on a
    daemon thread where every failure is swallowed, and nothing records the
    outcome. An employee whose invite failed is `active`, looks entirely
    normal, and is simply absent from Discord, with no badge to prompt the
    question.

    Synchronous, unlike the login path: an operator pressed this and is looking
    at the result. The stage is named because the remedies differ — a bot
    failure sends them to Discord settings, an email failure to the address or
    the SES sandbox.

    No "did it fail before?" gate: nothing records that (see ADR-443 D4).
    Sending a second invite to someone who already has one is harmless.
    """
    target = db.query(Employee).filter(
        Employee.id == employee_id,
        Employee.company_id == caller.company_id,
    ).first()
    if not target:
        raise HTTPException(status_code=404, detail="Employee not found")

    if not target.email:
        raise HTTPException(
            status_code=400,
            detail="This employee has no email address on file.",
        )

    try:
        result = discord_invite.fetch_and_send(target)
    except discord_invite.DiscordInviteError as exc:
        # 400 for the one the operator can fix on this page; 502 for the two
        # that are a service failing behind us.
        status_code = 400 if exc.stage == "email" and "No email" in exc.detail else 502
        raise HTTPException(status_code=status_code, detail=exc.detail)

    write_audit(
        db=db,
        company_id=caller.company_id,
        actor_id=caller.id,
        action_type="employee.discord_invite_resent",
        target_table="employees",
        target_id=str(target.id),
        # Dim 7: the address is NOT recorded. ADR-336 D1 made the same call for
        # the delivery alert — it is the payload of the thing that was sent,
        # not something the audit needs to identify the action.
        detail={"stage": "sent"},
    )
    db.commit()

    return {"detail": f"Discord invite sent to {result.email}.", "sent": True}


class MfaResetIn(BaseModel):
    """ADR-561 D3: an optional reason, shown to the employee in the reset notice."""
    model_config = ConfigDict(extra="forbid")
    reason: Optional[str] = Field(default=None, min_length=10, max_length=200)


@router.post("/{employee_id}/mfa/reset", status_code=status.HTTP_200_OK)
def reset_employee_mfa(
    employee_id: UUID,
    body: Optional[MfaResetIn] = None,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(RoleChecker(["management", "admin"])),
):
    """Clear an employee's remembered devices and end every session (ADR-386).

    SecurityPanel has promised this since it shipped -- "Lost your phone? An admin
    can reset your second factor" -- with no endpoint behind it.

    Three actions: clear the MFA preference, end every session, forget every
    remembered device.

    ADR-386 originally argued the factor could stay, because re-enrolment
    overwrites the single software token Cognito holds (ADR-377 D3). That was
    wrong in the case this endpoint exists for. A user who has LOST their
    authenticator cannot reach enrolment: it lives at /account, behind the
    sign-in the factor is blocking. Corrected in ADR-389 after a real lockout.

    Note a privileged user is still refused by the PreAuthentication trigger for
    having NO factor, so for them this is necessary and not sufficient -- see the
    break-glass runbook.

    This is a privilege-escalation surface: it operates on ANOTHER user's account
    protection, so it is gated to management/admin and every call is audited with
    both the actor and the target.
    """
    target = db.query(Employee).filter(
        Employee.id == employee_id,
        Employee.company_id == caller.company_id,
    ).first()
    if not target:
        raise HTTPException(status_code=404, detail="Employee not found")

    username = cognito_username_for(target)
    if not username:
        # No resolvable Cognito Username: invited but never registered. There is
        # no account to contain, and a 409 says that rather than reporting a
        # containment that did nothing.
        raise HTTPException(
            status_code=409,
            detail="This employee has not completed registration yet.",
        )

    result = mfa_containment.contain(
        username=username,
        pool_id=settings.aws_cognito_user_pool_id,
        region=settings.aws_region,
        # THE fix for the lockout this endpoint was supposed to solve (ADR-389).
        # Clearing devices and sessions does nothing for someone who LOST their
        # authenticator: the factor is what they cannot satisfy, and enrolment
        # lives at /account behind the sign-in it blocks.
        clear_factor=True,
    )
    # ADR-550 D4: Cognito's sign-out leaves access tokens working here for up
    # to an hour; the stamp ends them now. Written whatever Cognito said.
    target.tokens_valid_after = datetime.now(timezone.utc)
    # ADR-551 D4: closes the employee's reset request, if any.
    if target.cognito_sub:
        from app.services import mfa_reset_requests
        mfa_reset_requests.resolve_for(db, target.cognito_sub, by_kind="employee", by_ref=str(caller.id))

    from app.services.note_scrub import scrub_note
    reason = (scrub_note(body.reason.strip())[0] or "").strip() or None if body and body.reason else None

    write_audit(
        db=db,
        company_id=caller.company_id,
        actor_id=caller.id,
        action_type="employee.mfa_reset",
        target_table="employees",
        target_id=str(target.id),
        detail={
            "reason": reason,
            "devices_forgotten": result.devices_forgotten,
            "signed_out": result.signed_out,
            "factor_cleared": result.factor_cleared,
            # Error TYPES only -- never the message, which can carry identifiers.
            "errors": result.errors,
        },
    )
    db.commit()

    # ADR-561: tell them, at the account's verified address. Never fails the reset.
    emailed = account_security.notify_mfa_reset(
        username, reset_by="An admin at your company", account="your AsheFlow account",
        if_not_you="tell your manager straight away", account_ref=str(target.id), reason=reason)

    if not result.fully_contained:
        # 502, not 500: the failure is downstream at Cognito, and the caller
        # needs to know the reset did NOT fully take rather than assume it did.
        raise HTTPException(
            status_code=502,
            detail="The reset did not fully complete. Please try again.",
        )

    return {
        "employee_id": str(target.id),
        "emailed": emailed,
        "devices_forgotten": result.devices_forgotten,
        "signed_out": result.signed_out,
        "factor_cleared": result.factor_cleared,
    }


class AdminEmailChangeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    new_email: EmailStr


def _email_change_target(employee_id: UUID, caller: Employee, current_user: dict, db: Session) -> tuple[Employee, str]:
    target = db.query(Employee).filter(Employee.id == employee_id,
                                       Employee.company_id == caller.company_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Employee not found")
    if target.id == caller.id:
        raise HTTPException(status_code=400, detail="Change your own email from My account.")
    _assert_not_protected(set(current_user.get("cognito_groups", [])), target.role)
    username = cognito_username_for(target)
    if not username:
        raise HTTPException(status_code=409, detail="This employee has not completed registration yet.")
    return target, username


@router.post("/{employee_id}/email/change", status_code=status.HTTP_200_OK)
def admin_start_email_change(
    employee_id: UUID,
    body: AdminEmailChangeIn,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    current_user: dict = Depends(RoleChecker(["management", "admin"])),
):
    """ADR-563 D3: for an employee who lost access to their inbox.

    Nothing changes until the link sent to the NEW address is used; then the
    address is written to Cognito and here, every session ends, and the old
    address is told. Company-scoped; management can't change an admin's or a
    manager's email (same rule as every other edit).
    """
    from app.services import email_change
    target, username = _email_change_target(employee_id, caller, current_user, db)
    new_email = body.new_email.strip().lower()
    clash = db.query(Employee).filter(Employee.email == new_email, Employee.company_id == caller.company_id,
                                      Employee.id != target.id).first()
    if clash:
        raise HTTPException(status_code=409, detail="That email is already in use by another account.")
    try:
        expires = email_change.start_admin_change(
            db, username=username, kind="employee", company_id=caller.company_id, new_email=new_email,
            by_kind="tenant_admin", by_ref=str(caller.id), by_label="An admin at your company")
    except email_change.EmailChangeError as e:
        raise HTTPException(status_code=e.status, detail=e.detail)
    return {"detail": "Confirmation sent to the new address.",
            "pending_email_masked": account_security.mask_email(new_email),
            "expires_at": expires.isoformat()}


@router.delete("/{employee_id}/email/change", status_code=status.HTTP_200_OK)
def admin_cancel_email_change(
    employee_id: UUID,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    current_user: dict = Depends(RoleChecker(["management", "admin"])),
):
    from app.services import email_change
    _target, username = _email_change_target(employee_id, caller, current_user, db)
    # The pending row is keyed on the Cognito sub; the Employee may not hold it
    # yet (never signed in), so read it from Cognito.
    acct = email_change.cognito_account(username)
    if not acct or not acct["sub"]:
        return {"cancelled": False}
    return {"cancelled": email_change.cancel_admin_change(db, sub=acct["sub"], by_kind="tenant_admin",
                                                          by_ref=str(caller.id))}


@router.put("/{employee_id}/deactivate", response_model=EmployeeRecordResponse)
def deactivate_employee(
    employee_id: UUID,
    caller: Employee = Depends(get_caller_employee),
    current_user: dict = Depends(RoleChecker(["management", "admin"])),
    db: Session = Depends(get_db),
):
    """Set an employee's active status to False."""
    db_employee = db.query(Employee).filter(
        Employee.id == employee_id,
        Employee.company_id == caller.company_id,
    ).first()
    if not db_employee:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")
    _refuse_if_owner(db_employee, "deactivated")

    caller_groups = set(current_user.get("cognito_groups", []))
    _assert_not_protected(caller_groups, db_employee.role)

    from datetime import datetime, timezone
    db_employee.is_active = False
    # ADR-221: stamp departure so the 6-month name-redaction clock has a
    # reference. The row survives as a tombstone (name still resolvable during
    # the grace window); the nightly job redacts once deactivated_at + 6mo passes.
    db_employee.deactivated_at = datetime.now(timezone.utc)
    write_audit(
        db,
        actor_id=str(caller.id),
        company_id=str(caller.company_id),
        action_type="employee.deactivated",
        target_table="employees",
        target_id=str(employee_id),
        before={"is_active": True},
        after={"is_active": False},
    )
    db.commit()
    db.refresh(db_employee)

    # Revoke Cognito session — blocks token refresh immediately WHEN IT
    # SUCCEEDS. ADR-336 D2: when Cognito is unreachable this silently did not
    # happen, leaving an offboarded employee with working credentials while the
    # UI reported them deactivated. That is the only security exposure the
    # ADR-336 sweep found, as opposed to a visibility gap.
    #
    # The DB write is already committed, so the request must not fail — but
    # somebody has to learn the revocation did not take. severity="critical":
    # unlike a missed email, this one leaves access open.
    if not _cognito_revoke_access(db_employee.email or db_employee.username):
        raise_platform_alert(
            db,
            alert_type=IDENTITY_REVOCATION_FAILED,
            company_id=db_employee.company_id,
            message=IDENTITY_REVOCATION_MESSAGE,
            severity="critical",
        )
        db.commit()

    return db_employee


@router.put("/{employee_id}/reactivate", response_model=EmployeeRecordResponse)
def reactivate_employee(
    employee_id: UUID,
    caller: Employee = Depends(get_caller_employee),
    current_user: dict = Depends(RoleChecker(["management", "admin"])),
    db: Session = Depends(get_db),
):
    """Set an employee's active status back to True."""
    db_employee = db.query(Employee).filter(
        Employee.id == employee_id,
        Employee.company_id == caller.company_id,
    ).first()
    if not db_employee:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")

    caller_groups = set(current_user.get("cognito_groups", []))
    _assert_not_protected(caller_groups, db_employee.role)

    db_employee.is_active = True
    write_audit(
        db,
        actor_id=str(caller.id),
        company_id=str(caller.company_id),
        action_type="employee.reactivated",
        target_table="employees",
        target_id=str(employee_id),
        before={"is_active": False},
        after={"is_active": True},
    )
    db.commit()
    db.refresh(db_employee)

    # Re-enable the Cognito user and restore their role group so permissions
    # take effect on next token refresh.
    cognito_username = cognito_username_for(db_employee)
    if cognito_username:
        cognito = _cognito_client()
        try:
            cognito.admin_enable_user(
                UserPoolId=settings.aws_cognito_user_pool_id,
                Username=cognito_username,
            )
        except ClientError as e:
            logger.warning("Cognito admin_enable_user failed for %s: %s", cognito_username, e)

        group = ROLE_TO_COGNITO_GROUP.get(db_employee.role)
        if group:
            try:
                # Idempotent — adding a user to a group they already belong to is a no-op in Cognito
                cognito.admin_add_user_to_group(
                    UserPoolId=settings.aws_cognito_user_pool_id,
                    Username=cognito_username,
                    GroupName=group,
                )
            except ClientError as e:
                logger.warning(
                    "Cognito group restore failed for %s (group=%s): %s",
                    cognito_username, group, e,
                )

    return db_employee


@router.delete("/{employee_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_employee(
    employee_id: UUID,
    current_user: dict = Depends(RoleChecker(["admin"])),
    caller: Employee = Depends(get_caller_employee),
    db: Session = Depends(get_db),
):
    """Permanently delete an employee record. Admin only.

    Revokes the Cognito session and deletes the Cognito user before removing
    the DB record so the employee loses access immediately.
    """
    db_employee = db.query(Employee).filter(
        Employee.id == employee_id,
        Employee.company_id == caller.company_id,
    ).first()
    if not db_employee:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")
    _refuse_if_owner(db_employee, "deleted")

    # ADR-492 D3. Scorecard.employee_id is ON DELETE CASCADE, so a hard delete
    # would silently destroy a scorecard held for a personnel decision or an open
    # charge — the exact record the hold exists to keep. Refuse BEFORE the Cognito
    # deletion below, or a refused delete would leave a login-less employee.
    from datetime import date as _date
    from sqlalchemy import or_
    from app.models.scorecard import Scorecard
    held = db.query(Scorecard.id).filter(
        Scorecard.company_id == caller.company_id,
        Scorecard.employee_id == employee_id,
        or_(Scorecard.retention_hold_indefinite.is_(True),
            Scorecard.retention_hold_until >= _date.today()),
    ).first()
    if held:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This employee has scorecards under a retention hold. Release the hold "
                   "on the Scorecard Roster, or deactivate the employee instead of deleting.",
        )

    # Prefer username — Cognito accounts are created under the derived username.
    # Fall back to email only for legacy accounts predating the username column.
    cognito_username = cognito_username_for(db_employee)

    # Revoke session first, then delete the Cognito user
    _cognito_revoke_access(cognito_username)
    if cognito_username:
        try:
            _cognito_client().admin_delete_user(
                UserPoolId=settings.aws_cognito_user_pool_id,
                Username=cognito_username,
            )
        except ClientError as e:
            logger.warning("Cognito admin_delete_user failed for %s: %s", cognito_username, e)

    logger.info(
        "Employee %s (%s) deleted by admin %s",
        db_employee.name, employee_id, current_user.get("username") or current_user.get("id"),
    )
    # ADR-221: hard delete = on-demand erasure. Redact all denormalized _by_name
    # copies NOW, while the paired FK still resolves (SET NULL fires on delete,
    # after which the copies can't be matched back). The audit `before` records
    # role/status only — not the raw name/email (which would re-persist the PII
    # we're erasing).
    from app.services.employee_redaction import redact_employee_names
    redact_employee_names(db, employee_id)

    write_audit(
        db,
        actor_id=str(caller.id),
        company_id=str(caller.company_id),
        action_type="employee.deleted",
        target_table="employees",
        target_id=str(employee_id),
        before={
            "role":           db_employee.role,
            "account_status": db_employee.account_status,
            "is_active":      db_employee.is_active,
            "company_id":     str(db_employee.company_id),
        },
    )
    db.delete(db_employee)
    db.commit()


# ── Field-role transitions (ADR-256) ─────────────────────────────────────────
#
# Who may become what. An ALLOW-list, not a deny-list: a role absent from a value
# tuple cannot be reached, and a role absent from the keys cannot transition at all.
# Deny-lists silently admit every role added later (ADR-256 audit, `rebalance_crews`).
#
# dispatch / management / admin / field_supervisor are deliberately absent — those
# are hiring decisions, not field promotions, and are set at creation or by an admin
# editing the employee directly.
# Roles that are EARNED, never assigned at hire. Each has an entry path:
# walker <- trainee, trainer <- walker (promotion), driver <- driver_trainee.
#
# ADR-264 adds `driver`. Before it there was no driver training track, so a
# direct driver hire was the only option; now it would silently skip the
# program this codebase just built, and the skip is invisible — the employee
# simply never appears in any training view.
EARNED_ROLES: dict[str, str] = {
    "walker": "Walkers must start as trainees and be assigned the walker role by dispatch.",
    "trainer": "Trainers can only be promoted from existing walkers by a manager or admin.",
    "driver": (
        "Drivers must start as driver trainees (ADR-264) and be promoted after "
        "completing the training program. Create them as driver_trainee."
    ),
    # ADR-256 treats captaincy as EARNED THROUGH EVIDENCE — "this trainer has
    # run a truck 14 times" beats a manager's judgement, and familiarisation
    # history is kept precisely as promotion evidence. Captain being
    # creatable at hire was an omission, not a decision: it let a new hire
    # hold a truck's route lead with no record of having run one.
    #
    # field_supervisor WAS deliberately not here ("nothing promotes into it").
    # ADR-538 D2: drivers are now promoted to it (ROLE_TRANSITIONS below), so it
    # is earned like the others -- reachable, and not hireable outside the
    # setup window.
    "captain": (
        "Captains are promoted from walkers or trainers once they have run a "
        "truck (ADR-256). Create them as a trainee, or promote an existing "
        "walker or trainer."
    ),
    "field_supervisor": (
        "Field supervisors are promoted from drivers (ADR-538). Create them as a "
        "driver trainee, or promote an existing driver."
    ),
}


ROLE_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "walker":  ("trainer", "captain"),
    "trainer": ("captain", "walker"),
    "captain": ("trainer", "walker"),
    # ADR-264 D10 (revised 2026-08-22) — the driver track's only promotion.
    # There is no driver graduation quiz: a driver trainee completes their
    # phases and dispatch/management approves the promotion explicitly.
    #
    # ONE-WAY on this page. A driver is not demoted back to driver_trainee
    # here: an unsuccessful observation keeps the driver role and gets a
    # supervising driver assigned to observe again, which is a dispatch action,
    # not a role change.
    "driver_trainee": ("driver",),
    # ADR-538 D2: field supervisor sits one notch above driver.
    "driver": ("field_supervisor",),
    "field_supervisor": ("driver",),
}

# Which direction the change is, for the audit trail and the wording of the notice.
# Captain outranks trainer outranks walker (ADR-256 hierarchy).
# driver_trainee -> driver is a promotion; the driver track is parallel to the
# walker ladder (ADR-264 D2), so the ranks do not interleave with it.
_ROLE_RANK: dict[str, int] = {
    "walker": 0, "trainer": 1, "captain": 2,
    "driver_trainee": 0, "driver": 1, "field_supervisor": 2,
}


def _clear_captain_pins(db: Session, employee_id: UUID, company_id: UUID) -> int:
    """Clear a departing captain's truck pins. Returns how many were cleared.

    Familiarity ROWS are kept — `days_held` is real history and survives a
    round-trip out of and back into the captain role. Only `pinned` is cleared: a
    pin left behind would steer `assign_captains` toward someone who is no longer a
    captain, and the partial unique index would hold a truck's pin slot hostage.
    """
    from app.models.captain_truck_familiarity import CaptainTruckFamiliarity

    rows = db.query(CaptainTruckFamiliarity).filter(
        CaptainTruckFamiliarity.company_id == company_id,
        CaptainTruckFamiliarity.employee_id == employee_id,
        CaptainTruckFamiliarity.pinned == True,  # noqa: E712
    ).all()
    for row in rows:
        row.pinned = False
    return len(rows)


def _apply_role_transition(
    db: Session,
    db_employee: Employee,
    new_role: str,
    caller: Employee,
    confirm_incomplete: bool = False,
) -> Employee:
    """Move an employee between field roles, with every side effect that implies.

    Cognito group, in-app notification, audit row, Discord DM and Discord role sync.
    Shared by /promote, /demote and /transition so the three cannot drift apart —
    the original pair duplicated all of it and only covered walker<->trainer.
    """
    old_role = db_employee.role

    allowed = ROLE_TRANSITIONS.get(old_role)
    if allowed is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"A {old_role} cannot be promoted or demoted from this page.",
        )
    if new_role not in allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Cannot change a {old_role} to {new_role}. "
                f"Allowed: {', '.join(allowed)}."
            ),
        )

    # ADR-537 D3: a driver promotion with training phases left warns -- 409 with the
    # phases -- and goes ahead only when the caller confirms. Server-side, so no
    # client can skip the warning by omission.
    remaining_phases: list[int] = []
    if old_role == "driver_trainee" and new_role == "driver":
        from app.services.driver_promotion import driver_phases_remaining
        remaining_phases = driver_phases_remaining(db, db_employee)
        if remaining_phases and not confirm_incomplete:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "phases_incomplete",
                    "remaining_phases": remaining_phases,
                    "message": ("Driver training is not complete: phase(s) "
                                + ", ".join(str(p) for p in remaining_phases)
                                + " remain. Confirm to promote anyway."),
                },
            )

    is_promotion = _ROLE_RANK.get(new_role, 0) > _ROLE_RANK.get(old_role, 0)

    # Leaving the captain role must release the pins, or assign_captains keeps
    # steering toward someone who is no longer a captain.
    pins_cleared = 0
    if old_role == "captain":
        pins_cleared = _clear_captain_pins(db, db_employee.id, db_employee.company_id)

    db_employee.role = new_role
    db.flush()

    if db_employee.cognito_sub and db_employee.account_status == "active":
        old_group = ROLE_TO_COGNITO_GROUP.get(old_role)
        new_group = ROLE_TO_COGNITO_GROUP.get(new_role)
        if new_group is None:
            # Never silently leave someone in their old group with old permissions.
            logger.error(
                "No Cognito group mapped for role %s — group NOT synced for employee %s",
                new_role, db_employee.id,
            )
        else:
            cognito = _cognito_client()
            # ADR-380 F7 — was `email or cognito_sub`, which skipped
            # Employee.username entirely, so a registered employee's group
            # never synced on a role transition.
            cognito_username = cognito_username_for(db_employee)
            # ADD BEFORE REMOVE. Nothing in this codebase creates Cognito groups —
            # they are assumed to already exist in the User Pool — so a role whose
            # group has not been created yet raises ResourceNotFoundException here.
            # Removing first would leave the user in NO group: worse than the old
            # one, and it locks them out rather than over-permitting them.
            # Briefly holding both is the safe direction to fail.
            try:
                cognito.admin_add_user_to_group(
                    UserPoolId=settings.aws_cognito_user_pool_id,
                    Username=cognito_username,
                    GroupName=new_group,
                )
            except ClientError as e:
                # Loud: the DB role has changed and the token claims have not, so
                # this person's permissions no longer match their role.
                logger.error(
                    "Cognito ADD to group %s FAILED for employee %s (%s) — role is now "
                    "%s in the database but their Cognito group is unchanged. If the "
                    "group does not exist, create it in the User Pool.",
                    new_group, db_employee.id, e, new_role,
                )
            else:
                if old_group and old_group != new_group:
                    try:
                        cognito.admin_remove_user_from_group(
                            UserPoolId=settings.aws_cognito_user_pool_id,
                            Username=cognito_username,
                            GroupName=old_group,
                        )
                    except ClientError as e:
                        # They hold both groups now. Over-permitted, not locked out,
                        # and recoverable by hand — but it must not pass silently.
                        logger.error(
                            "Cognito REMOVE from group %s failed for employee %s (%s) — "
                            "they now hold both %s and %s.",
                            old_group, db_employee.id, e, old_group, new_group,
                        )

    verb = "promoted" if is_promotion else "changed"
    write_notification(
        db,
        company_id=db_employee.company_id,
        employee_id=db_employee.id,
        type="role_change",
        message=f"Congratulations! You have been promoted from {old_role} to {new_role} by {caller.name}."
            if is_promotion
            else f"Your role has been updated from {old_role} to {new_role} by {caller.name}.",
    )
    write_audit(
        db,
        actor_id=str(caller.id),
        company_id=str(caller.company_id),
        action_type=f"employee.role_{verb}",
        target_table="employees",
        target_id=str(db_employee.id),
        before={"role": old_role},
        after={"role": new_role, "captain_pins_cleared": pins_cleared,
               # ADR-537 D4: an override is on the record, with what it skipped.
               **({"incomplete_override": True, "remaining_phases": remaining_phases}
                  if remaining_phases else {})},
    )
    db.commit()
    db.refresh(db_employee)

    if db_employee.discord_id:
        if is_promotion:
            _fire_discord_dm(
                str(db_employee.discord_id),
                f"Congratulations! You've been promoted to {new_role.title()}.",
            )
        _sync_discord_role_for_transition(db_employee, old_role, new_role)

    return db_employee


def _sync_discord_role_for_transition(db_employee: Employee, old_role: str, new_role: str) -> None:
    """Grant/revoke the Discord role that matches the new field role.

    Trainer and captain are DIFFERENT Discord roles (ADR-256): the guild's old
    "Captain" role is being renamed Trainer with a new Captain role created
    alongside it, so `grant_trainer` and `grant_captain` are distinct actions.
    Sending the wrong one would give a trainer route-lead channel access.
    """
    discord_id = str(db_employee.discord_id)
    company_id = str(db_employee.company_id)

    if old_role in ("trainer", "captain"):
        _fire_role_sync(discord_id, company_id, f"revoke_{old_role}")
    if new_role in ("trainer", "captain"):
        _fire_role_sync(discord_id, company_id, f"grant_{new_role}")


@router.post("/{employee_id}/transition", response_model=EmployeeRecordResponse)
def transition_employee_role(
    employee_id: UUID,
    payload: RoleTransitionRequest,
    caller: Employee = Depends(get_caller_employee),
    current_user: dict = Depends(RoleChecker(["management", "admin"])),
    db: Session = Depends(get_db),
):
    """Move an employee between field roles (ADR-256).

    walker  -> trainer | captain
    trainer -> captain | walker
    captain -> trainer | walker

    A new captain needs no further setup: `assign_captains` treats any captain with
    no completed familiarity rows as familiarising, so the rotation starts on their
    next dispatch automatically.
    """
    db_employee = db.query(Employee).filter(
        Employee.id == employee_id,
        Employee.company_id == caller.company_id,
    ).first()
    if not db_employee:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")

    return _apply_role_transition(db, db_employee, payload.new_role, caller,
                                  confirm_incomplete=payload.confirm_incomplete)


@router.post("/{employee_id}/promote", response_model=EmployeeResponse)
def promote_employee(
    employee_id: UUID,
    caller: Employee = Depends(get_caller_employee),
    current_user: dict = Depends(RoleChecker(["management", "admin"])),
    db: Session = Depends(get_db),
):
    """Promote a walker to trainer.

    Kept for the existing Assets UI call. Delegates to _apply_role_transition so the
    Cognito / notification / audit / Discord side effects cannot drift from the
    general /transition path — promote and demote each carried their own copy before
    ADR-256, which is how a new role gets added to one and missed in the other.
    """
    db_employee = db.query(Employee).filter(
        Employee.id == employee_id,
        Employee.company_id == caller.company_id,
    ).first()
    if not db_employee:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")
    if db_employee.role != "walker":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Can only promote walkers to trainer (current role: {db_employee.role}).",
        )
    return _apply_role_transition(db, db_employee, "trainer", caller)


@router.post("/{employee_id}/demote", response_model=EmployeeResponse)
def demote_employee(
    employee_id: UUID,
    caller: Employee = Depends(get_caller_employee),
    current_user: dict = Depends(RoleChecker(["management", "admin"])),
    db: Session = Depends(get_db),
):
    """Demote a trainer back to walker. See promote_employee on delegation."""
    db_employee = db.query(Employee).filter(
        Employee.id == employee_id,
        Employee.company_id == caller.company_id,
    ).first()
    if not db_employee:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")
    _refuse_if_owner(db_employee, "demoted")
    if db_employee.role != "trainer":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Can only demote trainers to walker (current role: {db_employee.role}).",
        )
    return _apply_role_transition(db, db_employee, "walker", caller)


# ── Injury / modified-duty status ─────────────────────────────────────────────

@router.patch("/{employee_id}/injury-status", response_model=EmployeeResponse)
def set_injury_status(
    employee_id: UUID,
    body: InjuryStatusPatch,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(RoleChecker(["management", "admin"])),
    db: Session = Depends(get_db),
):
    """Set or clear an employee's injury / modified-duty status.

    injury_status=null clears the flag and restores full routing eligibility.
    injury_status="injured"|"disabled" hard-blocks the employee from heavy route
    assignments until the flag is explicitly cleared (ADR-139).
    """
    employee = db.query(Employee).filter(
        Employee.id == employee_id,
        Employee.company_id == caller.company_id,
    ).first()
    if not employee:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found.")

    old_status = employee.injury_status
    employee.injury_status = body.injury_status
    employee.injury_status_since = datetime.now(timezone.utc) if body.injury_status else None

    write_audit(
        db,
        actor_id=str(caller.id),
        company_id=str(caller.company_id),
        action_type="employee.injury_status_updated",
        target_table="employees",
        target_id=str(employee_id),
        before={"injury_status": old_status},
        after={"injury_status": body.injury_status},
    )
    db.commit()
    db.refresh(employee)
    return employee


# ── Credential changes (ADR-541) ─────────────────────────────────────────────
#
# Password and email changes are confirmed OUT OF BAND (a code to the verified
# inbox) and END EVERY SESSION. Neither flow calls Cognito's USER-level APIs
# (ChangePassword, UpdateUserAttributes, VerifyUserAttribute): ADR-541 D4 reads
# those, seen in CloudTrail, as someone going around the app. The password code
# is Cognito's own ForgotPassword code; the email codes are held by
# services/account_security.py. Every role changes its own credentials, so the
# gate is the full role list.

_allow_self = RoleChecker(list(Employee_VALID_ROLES))

_NO_EMAIL = (
    "Your account has no email address yet. Ask your manager or an admin to add "
    "it from the People page, then try again."
)


def _username_or_409(caller) -> str:
    username = cognito_username_for(caller)
    if not username:
        raise HTTPException(status_code=409, detail="Your account isn't set up to sign in yet.")
    return username


class _PasswordConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(..., min_length=4, max_length=10)
    new_password: str = Field(..., min_length=8, max_length=256)


@router.get("/me/session", status_code=status.HTTP_200_OK)
def check_session(
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_self),
):
    """ADR-541 D2 amendment — the cheapest request that still runs the full
    caller check, so an open tab learns within a minute (or on focus) that its
    session was ended by a password or email change elsewhere. Reaching this
    body means the session is still good; the refusal is get_caller_employee's
    coded 401, which both clients already route on."""
    return {"ok": True}


@router.post("/me/password/request-code", status_code=status.HTTP_200_OK)
def request_password_code(
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_self),
):
    """Step 1 of a password change: email a code to the verified address.

    Cognito's ForgotPassword sends it (branded by CustomMessage_ForgotPassword).
    No current-password check -- ADR-541 R1: it would cost a real sign-in, and
    the inbox is the barrier either way.
    """
    if not (caller.email or "").strip():
        raise HTTPException(status_code=409, detail=_NO_EMAIL)
    username = _username_or_409(caller)
    if not account_security.allow_request(caller.id, "password"):
        raise HTTPException(status_code=429, detail="Too many code requests. Try again in an hour.")
    try:
        _cognito_client().forgot_password(
            ClientId=settings.aws_cognito_app_client_id, Username=username,
        )
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code == "InvalidParameterException":
            # Cognito's "no registered/verified email" -- an address in our DB
            # that Cognito never verified.
            raise HTTPException(status_code=409, detail=_NO_EMAIL)
        if code in ("LimitExceededException", "TooManyRequestsException"):
            raise HTTPException(status_code=429, detail="Too many code requests. Try again later.")
        logger.error("forgot_password failed for %s: %s", caller.id, code)
        raise HTTPException(status_code=500, detail="Couldn't send the code. Try again.")
    return {"detail": "Code sent.", "sent_to": account_security.mask_email(caller.email)}


@router.post("/me/password/confirm", status_code=status.HTTP_200_OK)
def confirm_password_change(
    payload: _PasswordConfirmRequest,
    caller: Employee = Depends(get_caller_employee),
    db: Session = Depends(get_db),
    _: dict = Depends(_allow_self),
):
    """Step 2: the code and the new password. Then every session ends (D2)."""
    username = _username_or_409(caller)
    try:
        _cognito_client().confirm_forgot_password(
            ClientId=settings.aws_cognito_app_client_id,
            Username=username,
            ConfirmationCode=payload.code.strip(),
            Password=payload.new_password,
        )
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code == "CodeMismatchException":
            raise HTTPException(status_code=400, detail="That code isn't right. Check the email and try again.")
        if code == "ExpiredCodeException":
            raise HTTPException(status_code=400, detail="That code has expired. Send a new one.")
        if code == "InvalidPasswordException":
            raise HTTPException(
                status_code=400,
                detail="That password doesn't meet the rules: at least 8 characters, with upper and lower case letters, a number and a symbol.",
            )
        if code in ("LimitExceededException", "TooManyFailedAttemptsException", "TooManyRequestsException"):
            raise HTTPException(status_code=429, detail="Too many attempts. Wait a few minutes and try again.")
        logger.error("confirm_forgot_password failed for %s: %s", caller.id, code)
        raise HTTPException(status_code=500, detail="Couldn't change your password. Try again.")

    signed_out = account_security.end_all_sessions(caller, username)
    db.flush()
    write_audit(
        db=db,
        company_id=caller.company_id,
        actor_id=caller.id,
        action_type="account.password_changed",
        target_table="employees",
        target_id=str(caller.id),
        detail={"confirmed_by": "email_code", "signed_out_everywhere": signed_out},
    )
    db.commit()
    return {"detail": "Password changed. Sign in with your new password.", "signed_out": True}


class _SignInNameIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # The shape rules live in sign_in_name.normalise; this only bounds the input.
    sign_in_name: str = Field(..., min_length=1, max_length=64)


def _sign_in_name_error(e) -> HTTPException:
    return HTTPException(status_code=e.status, detail=e.detail)


@router.get("/me/sign-in-name", status_code=status.HTTP_200_OK)
def get_sign_in_name(
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_self),
):
    """ADR-566 D4: the caller's own sign-in name, and whether this environment
    supports one yet."""
    from app.services import sign_in_name
    username = _username_or_409(caller)
    ok = sign_in_name.available()
    return {"available": ok, "username": username, "rules": sign_in_name.RULES,
            "sign_in_name": sign_in_name.current(username) if ok else None}


@router.put("/me/sign-in-name", status_code=status.HTTP_200_OK)
def set_sign_in_name(
    payload: _SignInNameIn,
    caller: Employee = Depends(get_caller_employee),
    db: Session = Depends(get_db),
    _: dict = Depends(_allow_self),
):
    """ADR-566 D4: only the person chooses their sign-in name."""
    from app.services import sign_in_name
    username = _username_or_409(caller)
    try:
        name = sign_in_name.apply_sign_in_name(
            db, username=username, raw=payload.sign_in_name, rate_key=caller.id,
            audit={"company_id": caller.company_id, "actor_id": caller.id,
                   "target_table": "employees", "target_id": str(caller.id)})
    except sign_in_name.SignInNameError as e:
        raise _sign_in_name_error(e)
    return {"sign_in_name": name}


@router.delete("/me/sign-in-name", status_code=status.HTTP_200_OK)
def clear_own_sign_in_name(
    caller: Employee = Depends(get_caller_employee),
    db: Session = Depends(get_db),
    _: dict = Depends(_allow_self),
):
    from app.services import sign_in_name
    username = _username_or_409(caller)
    try:
        cleared = sign_in_name.remove_sign_in_name(
            db, username=username, by="self",
            audit={"company_id": caller.company_id, "actor_id": caller.id,
                   "target_table": "employees", "target_id": str(caller.id)})
    except sign_in_name.SignInNameError as e:
        raise _sign_in_name_error(e)
    return {"cleared": cleared}


class _ChosenNameIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # The shape rule lives in chosen_name.normalise; this only bounds the input.
    chosen_name: str = Field(..., min_length=1, max_length=200)


def _chosen_name_changed(db: Session, target: Employee, before: Optional[str], *, actor_id, action: str,
                         by: str) -> bool:
    """Shared tail of every chosen-name change: audit, Cognito, the read cache.
    The audit holds chosen names only, never the legal name (ADR-567 D2)."""
    from app.services import chosen_name, chosen_names
    db.flush()
    write_audit(db=db, company_id=target.company_id, actor_id=actor_id, action_type=action,
                target_table="employees", target_id=str(target.id),
                detail={"from": before, "to": target.chosen_name, "by": by})
    db.commit()
    chosen_names.forget(db)
    return chosen_name.sync_cognito_name(target, cognito_username_for(target))


@router.put("/me/chosen-name", response_model=EmployeeRecordResponse)
def set_chosen_name(
    payload: _ChosenNameIn,
    caller: Employee = Depends(get_caller_employee),
    db: Session = Depends(get_db),
    _: dict = Depends(_allow_self),
):
    """ADR-567 D2: only the person sets the name they are called. No approval,
    no reason. Shown everywhere from the next request; the legal name stays the
    record."""
    from app.services import chosen_name
    try:
        name = chosen_name.normalise(payload.chosen_name)
    except chosen_name.ChosenNameError as e:
        raise HTTPException(status_code=e.status, detail=e.detail)
    if not account_security.allow_request(caller.id, "chosen_name"):
        raise HTTPException(status_code=429, detail="Too many changes. Try again in an hour.")
    before = caller.chosen_name
    # The legal name typed as a "chosen" one is no chosen name: store nothing.
    caller.chosen_name = None if name == caller.legal_name else name
    _chosen_name_changed(db, caller, before, actor_id=caller.id, action="account.chosen_name_set", by="self")
    db.refresh(caller)
    return EmployeeRecordResponse.model_validate(caller)


@router.delete("/me/chosen-name", response_model=EmployeeRecordResponse)
def clear_own_chosen_name(
    caller: Employee = Depends(get_caller_employee),
    db: Session = Depends(get_db),
    _: dict = Depends(_allow_self),
):
    before = caller.chosen_name
    if before is not None:
        caller.chosen_name = None
        _chosen_name_changed(db, caller, before, actor_id=caller.id, action="account.chosen_name_cleared", by="self")
        db.refresh(caller)
    return EmployeeRecordResponse.model_validate(caller)


@router.delete("/{employee_id}/chosen-name", status_code=status.HTTP_200_OK)
def admin_clear_chosen_name(
    employee_id: UUID,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    current_user: dict = Depends(RoleChecker(["management", "admin"])),
):
    """ADR-567 D2: management or admin may clear an abusive chosen name, never
    set one. Same scope as an email change: own company, and management can't
    act on an admin or a manager."""
    target = db.query(Employee).filter(Employee.id == employee_id,
                                       Employee.company_id == caller.company_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Employee not found")
    if target.id == caller.id:
        raise HTTPException(status_code=400, detail="Change your own name from My account.")
    _assert_not_protected(set(current_user.get("cognito_groups", [])), target.role)
    before = target.chosen_name
    if before is None:
        return {"cleared": False}
    target.chosen_name = None
    _chosen_name_changed(db, target, before, actor_id=caller.id, action="account.chosen_name_cleared",
                         by="tenant_admin")
    return {"cleared": True}


# Declared after the /me routes: "/{employee_id}/sign-in-name" would otherwise
# match "/me/sign-in-name" and fail UUID validation with a 422.
@router.delete("/{employee_id}/sign-in-name", status_code=status.HTTP_200_OK)
def admin_clear_sign_in_name(
    employee_id: UUID,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    current_user: dict = Depends(RoleChecker(["management", "admin"])),
):
    """ADR-566 D4: an admin may clear a sign-in name (an offensive one, say) but
    never choose one. Same scope as an email change: own company, and
    management can't act on an admin or a manager."""
    from app.services import sign_in_name
    target = db.query(Employee).filter(Employee.id == employee_id,
                                       Employee.company_id == caller.company_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Employee not found")
    if target.id == caller.id:
        raise HTTPException(status_code=400, detail="Change your own sign-in name from My account.")
    _assert_not_protected(set(current_user.get("cognito_groups", [])), target.role)
    username = cognito_username_for(target)
    if not username:
        raise HTTPException(status_code=409, detail="This employee has not completed registration yet.")
    try:
        cleared = sign_in_name.remove_sign_in_name(
            db, username=username, by="tenant_admin",
            audit={"company_id": caller.company_id, "actor_id": caller.id,
                   "target_table": "employees", "target_id": str(target.id)})
    except sign_in_name.SignInNameError as e:
        raise _sign_in_name_error(e)
    return {"cleared": cleared}


class _EmailChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    new_email: EmailStr


_PENDING_EMAIL_KEY = "acctsec:pending_email:{}"


@router.post("/me/email/request-change", status_code=status.HTTP_200_OK)
def request_email_change(
    payload: _EmailChangeRequest,
    caller: Employee = Depends(get_caller_employee),
    db: Session = Depends(get_db),
    _: dict = Depends(_allow_self),
):
    """Step 1 of an email change: a code to the CURRENT address and one to the NEW.

    ADR-541 R2. The current-address code proves the account owner (OWASP's
    confirm-through-the-current-address step); the new-address code proves the
    new inbox. A first email for an account with none is set by an admin (R3):
    with no current address there is nothing to confirm against.
    """
    # ADR-563 D1: "current" is the address Cognito sends this account's codes to,
    # not Employee.email -- the database copy could drift (staging walker.test).
    from app.services import email_change
    acct = email_change.cognito_account(_username_or_409(caller))
    current = acct["email"] if acct and acct["verified"] else None
    if not current:
        raise HTTPException(status_code=409, detail=_NO_EMAIL)
    new_email = payload.new_email.strip().lower()
    if new_email == current:
        raise HTTPException(status_code=400, detail="That's already your email address.")

    existing = db.query(Employee).filter(
        Employee.email == new_email,
        Employee.company_id == caller.company_id,
        Employee.id != caller.id,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="That email is already in use by another account.")

    if not account_security.allow_request(caller.id, "email"):
        raise HTTPException(status_code=429, detail="Too many code requests. Try again in an hour.")

    current_code = account_security.issue_code(caller.id, "email_current")
    new_code = account_security.issue_code(caller.id, "email_new")
    _get_redis().setex(_PENDING_EMAIL_KEY.format(caller.id), account_security.CODE_TTL_SECONDS, new_email)

    from app.services.email import send_email_change_code
    masked_new = account_security.mask_email(new_email)
    try:
        send_email_change_code(to_email=current, employee_name=caller.name, code=current_code,
                               which="current", new_email_masked=masked_new, account_ref=str(caller.id))
        send_email_change_code(to_email=new_email, employee_name=caller.name, code=new_code,
                               which="new", new_email_masked=masked_new, account_ref=str(caller.id))
    except ClientError:
        account_security.discard_codes(caller.id, "email_current", "email_new")
        raise HTTPException(status_code=502, detail="Couldn't send the codes. Try again.")

    return {
        "detail": "Codes sent.",
        "current_masked": account_security.mask_email(current),
        "new_masked": masked_new,
    }


class _EmailConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_code: str = Field(..., min_length=4, max_length=10)
    new_code: str = Field(..., min_length=4, max_length=10)


@router.post("/me/email/confirm-change", status_code=status.HTTP_200_OK)
def confirm_email_change(
    payload: _EmailConfirmRequest,
    caller: Employee = Depends(get_caller_employee),
    db: Session = Depends(get_db),
    _: dict = Depends(_allow_self),
):
    """Step 2: both codes. Then the address changes, the old one is told, and
    every session ends (D2/D3)."""
    raw = _get_redis().get(_PENDING_EMAIL_KEY.format(caller.id))
    if raw is None:
        raise HTTPException(status_code=400, detail="Those codes have expired. Start the change again.")
    new_email = raw.decode() if isinstance(raw, bytes) else raw

    for purpose, given, where in (("email_current", payload.current_code, "your current email"),
                                  ("email_new", payload.new_code, "your new email")):
        verdict = account_security.check_code(caller.id, purpose, given)
        if verdict == "expired":
            account_security.discard_codes(caller.id, "email_current", "email_new")
            raise HTTPException(status_code=400, detail="Those codes have expired. Start the change again.")
        if verdict == "wrong":
            raise HTTPException(status_code=400, detail=f"The code sent to {where} isn't right.")

    # ADR-563: one write path for every kind of email change -- Cognito first,
    # then the database copy, every session ended, the OLD (Cognito) address told.
    from app.services import email_change
    try:
        email_change.apply_change(db, username=_username_or_409(caller), new_email=new_email,
                                  actor={"kind": "self", "ref": str(caller.id), "employee_id": caller.id},
                                  confirmed_by="codes_to_both_addresses")
    except email_change.EmailChangeError as e:
        raise HTTPException(status_code=e.status, detail=e.detail)
    _get_redis().delete(_PENDING_EMAIL_KEY.format(caller.id))

    return {"detail": "Email updated. Sign in again.", "email": new_email, "signed_out": True}


# ── Discord account linking (ADR-270) ────────────────────────────────────────
#
# WHY THIS IS VERIFIED RATHER THAN A PLAIN FIELD EDIT
# `employees.discord_id` is not decoration. It is the bot's DM address (it was
# also an auth lookup step until ADR-560 removed it). A user who could set it
# freely could point their record at a colleague's Discord account and
# redirect that person's dispatch DMs.
#
# So it mirrors the email-change flow directly above: request a code, prove
# receipt, then write. The difference is where the code lives — Cognito holds
# the email code for us; for Discord we hold it in Redis with a short TTL.
#
# ADR-083 governs the value itself: numeric snowflake, 17-20 digits,
# VARCHAR(20). `_validate_discord_id` is reused rather than re-implemented so
# this endpoint cannot drift from EmployeeCreate/EmployeeUpdate.

_DISCORD_CODE_TTL_SECONDS = 600          # 10 minutes, matching typical email codes
_DISCORD_ATTEMPT_TTL_SECONDS = 3600      # rate-limit window
_DISCORD_MAX_ATTEMPTS = 5                # requests per window, per caller


def _discord_code_key(employee_id: UUID) -> str:
    return f"discord_link_code:{employee_id}"


def _discord_attempt_key(employee_id: UUID) -> str:
    return f"discord_link_attempts:{employee_id}"


class _DiscordLinkRequest(BaseModel):
    discord_id: str = Field(..., max_length=20)

    @field_validator("discord_id", mode="before")
    @classmethod
    def _check(cls, v):
        # Reuses the ADR-083 validator: a non-snowflake is a 422 here, not a
        # row we would have to defend against everywhere downstream.
        validated = _validate_discord_id(v)
        if validated is None:
            raise ValueError("discord_id is required")
        return validated


class _DiscordConfirmRequest(_DiscordLinkRequest):
    code: str = Field(..., min_length=6, max_length=6)


@router.post("/me/discord/request-link", status_code=status.HTTP_200_OK)
def request_discord_link(
    payload: _DiscordLinkRequest,
    caller: Employee = Depends(get_caller_employee),
    db: Session = Depends(get_db),
    _: dict = Depends(RoleChecker(
        ["driver", "walker", "trainer", "trainee", "captain",
         "dispatch", "management", "admin"]
    )),
):
    """Step 1: send a 6-digit code by Discord DM to the claimed account.

    Any authenticated employee may link their OWN account — the write target is
    `caller`, never an id from the request, so there is nothing to widen.

    The DM is the proof of ownership: only the person holding that Discord
    account can read the code. A typo therefore DMs a stranger, which is why
    the message says why it arrived and that it can be ignored.
    """
    discord_id = payload.discord_id

    # UNIQUE(company_id, discord_id) — surface the conflict as a 409 rather
    # than letting the commit fail later with an opaque IntegrityError.
    taken = db.query(Employee).filter(
        Employee.company_id == caller.company_id,
        Employee.discord_id == discord_id,
        Employee.id != caller.id,
    ).first()
    if taken:
        raise HTTPException(
            status_code=409,
            detail="That Discord account is already linked to another employee.",
        )

    r = _get_redis()

    # Rate limit: a code request DMs a third party, so an unbounded endpoint is
    # a spam vector against arbitrary Discord users.
    attempts = r.incr(_discord_attempt_key(caller.id))
    if attempts == 1:
        r.expire(_discord_attempt_key(caller.id), _DISCORD_ATTEMPT_TTL_SECONDS)
    if attempts > _DISCORD_MAX_ATTEMPTS:
        raise HTTPException(
            status_code=429,
            detail="Too many link attempts. Try again later.",
        )

    code = f"{secrets.randbelow(1_000_000):06d}"
    # Store the code WITH the id it was issued for: confirming must not accept
    # a code minted for a different account.
    r.setex(_discord_code_key(caller.id), _DISCORD_CODE_TTL_SECONDS,
            f"{discord_id}:{code}")

    _fire_discord_dm(
        discord_id,
        f"Your AsheFlow verification code is **{code}**.\n"
        "Someone entered this Discord ID on AsheFlow. If that was not you, "
        "ignore this message — nothing has been linked.",
    )

    return {"detail": "Verification code sent by Discord DM."}


@router.post("/me/discord/confirm-link", status_code=status.HTTP_200_OK)
def confirm_discord_link(
    payload: _DiscordConfirmRequest,
    caller: Employee = Depends(get_caller_employee),
    db: Session = Depends(get_db),
):
    """Step 2: confirm the code and write `discord_id` onto the caller."""
    r = _get_redis()
    stored = r.get(_discord_code_key(caller.id))
    if not stored:
        raise HTTPException(
            status_code=400,
            detail="No pending verification, or it expired. Request a new code.",
        )

    stored_id, _, stored_code = stored.partition(":")
    # BOTH must match. Checking only the code would let a caller request a code
    # for an id they control, then confirm it against someone else's id.
    if stored_id != payload.discord_id or not secrets.compare_digest(
        stored_code, payload.code
    ):
        raise HTTPException(status_code=400, detail="Incorrect verification code.")

    # Re-check uniqueness at write time: another employee may have linked this
    # id during the 10-minute window.
    taken = db.query(Employee).filter(
        Employee.company_id == caller.company_id,
        Employee.discord_id == payload.discord_id,
        Employee.id != caller.id,
    ).first()
    if taken:
        raise HTTPException(
            status_code=409,
            detail="That Discord account is already linked to another employee.",
        )

    previous = caller.discord_id
    caller.discord_id = payload.discord_id
    db.flush()
    write_audit(
        db=db,
        company_id=caller.company_id,
        actor_id=caller.id,
        action_type="employee.discord_linked",
        target_table="employees",
        target_id=str(caller.id),
        # No PII: the snowflake is an account identifier, and "who changed
        # their DM target" is exactly what an audit trail is for.
        detail={"previous": previous, "new": payload.discord_id},
    )
    db.commit()

    r.delete(_discord_code_key(caller.id))
    return {"detail": "Discord account linked.", "discord_id": payload.discord_id}


@router.post("/{employee_id}/transfer-ownership", response_model=EmployeeResponse)
def transfer_ownership(
    employee_id: UUID,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(RoleChecker(["admin"])),
    db: Session = Depends(get_db),
):
    """Move Ownership of this company to another admin (ADR-452 D3).

    TRANSFER, not "set owner". The flag moves in ONE transaction, so there is
    never a moment with two Owners or none -- and the unique partial index would
    refuse the intermediate state anyway.

    Only the current Owner may call this. An ordinary admin handing ownership to
    themselves is a privilege escalation with extra steps; a super admin can do
    it through the company endpoints when an Owner has left and cannot hand over.

    The target must already be an ACTIVE ADMIN. Promoting and transferring in one
    call would hide which of the two actually happened, and the audit row would
    not say.
    """
    if not caller.is_owner:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the current Owner can transfer ownership.",
        )

    target = db.query(Employee).filter(
        Employee.id == employee_id,
        Employee.company_id == caller.company_id,
    ).first()
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")
    if target.id == caller.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You are already the Owner.",
        )
    if target.role != "admin" or not target.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Ownership can only be transferred to an active admin. "
                "Promote them first."
            ),
        )

    # ORDER MATTERS, and the database enforces it. `ix_employees_owner` is a
    # UNIQUE PARTIAL INDEX, and a unique index cannot be DEFERRABLE in Postgres
    # -- it is checked per statement, not at commit. Setting the new Owner first
    # (which is what SQLAlchemy's flush ordering does if both are dirty at once)
    # raises UniqueViolation on the momentary two-Owner state.
    #
    # So: clear the old Owner, FLUSH that statement, then set the new one. The
    # whole thing is still one transaction, so there is no window where the
    # company has no Owner from any other session's point of view.
    caller.is_owner = False
    db.flush()
    target.is_owner = True
    db.flush()

    write_audit(
        db=db,
        company_id=caller.company_id,
        actor_id=caller.id,
        action_type="company.ownership_transferred",
        target_table="employees",
        target_id=str(target.id),
        before={"owner_employee_id": str(caller.id)},
        after={"owner_employee_id": str(target.id)},
    )
    db.commit()
    db.refresh(target)
    logger.info(
        "Ownership of company %s transferred from %s to %s",
        caller.company_id, caller.id, target.id,
    )
    return target

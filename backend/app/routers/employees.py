import boto3
import logging
import os
import secrets
import threading
from datetime import datetime, timezone, timedelta
from typing import List
from uuid import UUID
from botocore.exceptions import ClientError

from pydantic import BaseModel, EmailStr, Field

import requests as http_requests

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import RoleChecker, Pagination, get_caller_employee
from app.core.config import settings
from app.database import get_db
from app.models.employee import Employee
from app.models.invite_token import InviteToken
from app.models.notification import Notification
from app.schemas.employee import EmployeeCreate, EmployeeUpdate, EmployeeResponse, EmployeePublicResponse, BulkImportRow, BulkImportResult, InjuryStatusPatch, RoleTransitionRequest
from app.services.audit import write_audit
from app.services.email import send_invite_email

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/employees", tags=["employees"])


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
        except Exception as exc:
            logger.warning("promote DM failed for discord_id=%s: %s", discord_id, exc)

    threading.Thread(target=_run, daemon=True).start()


def _fire_role_sync(discord_id: str, company_id: str, action: str) -> None:
    """Fire-and-forget: tell the bot to grant or revoke the trainer Discord role.

    action: "grant_trainer" | "revoke_trainer"
    """
    bot_url = os.environ.get("BOT_INTERNAL_URL", "http://bot:8001")
    secret  = os.environ.get("INTERNAL_SECRET", "")

    def _run():
        try:
            http_requests.post(
                f"{bot_url}/internal/role-sync",
                json={"discord_id": discord_id, "company_id": company_id, "action": action},
                headers={"X-Internal-Secret": secret},
                timeout=5,
            )
        except Exception as exc:
            logger.warning("role-sync failed discord_id=%s action=%s: %s", discord_id, action, exc)

    threading.Thread(target=_run, daemon=True).start()

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


def _cognito_revoke_access(cognito_username: str | None) -> None:
    """Disable the Cognito user and revoke all their tokens — best effort.

    AdminDisableUser blocks new token issuance immediately.
    AdminUserGlobalSignOut invalidates all existing refresh tokens so the
    current access token (max 15 min TTL) cannot be silently renewed.
    """
    if not cognito_username:
        return
    cognito = _cognito_client()
    for action in ("admin_disable_user", "admin_user_global_sign_out"):
        try:
            getattr(cognito, action)(
                UserPoolId=settings.aws_cognito_user_pool_id,
                Username=cognito_username,
            )
        except ClientError as e:
            logger.warning("Cognito %s failed for %s: %s", action, cognito_username, e)


@router.post("/", response_model=EmployeeResponse, status_code=status.HTTP_201_CREATED)
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
    # Walker and trainer roles cannot be directly assigned — walkers start as trainees,
    # trainers are promoted from walkers via POST /employees/{id}/promote
    if employee.role in ("walker", "trainer"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Walkers must start as trainees and be assigned the walker role by dispatch. "
                if employee.role == "walker"
                else "Trainers can only be promoted from existing walkers by a manager or admin."
            ),
        )

    # Management callers may only create field-entry roles (driver or trainee)
    if caller.role == "management" and employee.role not in ("driver", "trainee"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Management users can only create driver or trainee accounts.",
        )

    if employee.email and db.query(Employee).filter(
        Employee.company_id == caller.company_id,
        Employee.email == employee.email,
    ).first():
        raise HTTPException(status_code=400, detail="An employee with this email already exists.")

    now = datetime.now(timezone.utc)
    db_employee = Employee(
        **employee.model_dump(),
        company_id=caller.company_id,
        is_active=False,
        account_status="pending_verification",
        invited_at=now,
    )
    db.add(db_employee)
    db.flush()  # get db_employee.id before creating the token

    if employee.email:
        token_str = secrets.token_urlsafe(48)
        expires_at = now + timedelta(days=settings.invite_expiry_days)
        db.add(InviteToken(
            token=token_str,
            company_id=caller.company_id,
            employee_id=db_employee.id,
            expires_at=expires_at,
        ))
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
            # Don't fail the request — manager can resend from the Assets UI
    else:
        db.commit()
        db.refresh(db_employee)

    write_audit(
        db=db,
        company_id=caller.company_id,
        actor_id=caller.id,
        action_type="employee.create",
        target_table="employees",
        target_id=str(db_employee.id),
        detail={"name": db_employee.name, "role": db_employee.role, "email": db_employee.email},
    )
    return db_employee


@router.post("/bulk", response_model=List[BulkImportResult], status_code=status.HTTP_200_OK)
def bulk_import_employees(
    rows: List[BulkImportRow],
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

        if db.query(Employee).filter(
            Employee.company_id == caller.company_id,
            Employee.discord_id == row.discord_id,
        ).first():
            results.append(BulkImportResult(
                row=i, status="skipped", name=row.name, email=row.email,
                reason="Discord ID already exists.",
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

        try:
            db.commit()
        except Exception as e:
            db.rollback()
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

        write_audit(
            db=db,
            company_id=caller.company_id,
            actor_id=caller.id,
            action_type="employee.bulk_create",
            target_table="employees",
            target_id=str(db_employee.id),
            detail={"name": row.name, "role": row.role, "email": str(row.email), "row": i},
        )
        results.append(BulkImportResult(
            row=i, status="created", name=row.name, email=row.email,
        ))

    return results


PRIVILEGED_ROLES  = {"management", "admin", "dispatch"}
FIELD_ROLES       = {"driver", "walker", "trainer", "trainee"}
# Roles that only admins may create, edit, deactivate, or view
PROTECTED_ROLES   = {"management", "admin"}


def _assert_not_protected(caller_groups: set, target_role: str) -> None:
    """Raise 403 if target has a protected role and caller is not admin."""
    if target_role in PROTECTED_ROLES and "admin" not in caller_groups:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can modify management or admin accounts.",
        )


@router.get("/", response_model=list[EmployeeResponse])
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

    # Management callers cannot see management or admin accounts
    if caller.role == "management":
        q = q.filter(Employee.role.notin_(PROTECTED_ROLES))

    employees = pg.apply(q).all()

    if is_privileged:
        return [EmployeeResponse.model_validate(e) for e in employees]
    return [EmployeePublicResponse.model_validate(e) for e in employees]


@router.get("/me", response_model=EmployeeResponse)
def get_my_employee(
    caller: Employee = Depends(get_caller_employee),
):
    """Return the Employee record for the currently authenticated user."""
    return EmployeeResponse.model_validate(caller)


@router.get("/by-discord/{discord_id}", response_model=EmployeePublicResponse)
def get_employee_by_discord(
    discord_id: str,
    caller: Employee = Depends(get_caller_employee),
    current_user: dict = Depends(RoleChecker(list(PRIVILEGED_ROLES | FIELD_ROLES))),
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


@router.get("/{employee_id}", response_model=EmployeeResponse)
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

    if caller_groups & PRIVILEGED_ROLES:
        return EmployeeResponse.model_validate(employee)
    return EmployeePublicResponse.model_validate(employee)


@router.put("/{employee_id}", response_model=EmployeeResponse)
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

    for key, value in updates.items():
        setattr(db_employee, key, value)

    db.commit()
    db.refresh(db_employee)

    cognito = _cognito_client()

    # Wrong-email recovery — only valid while the account is still pending.
    # Delete the old Cognito user and recreate with the corrected email so a
    # fresh invite is sent. Active accounts must use the Cognito console.
    if new_email and new_email != old_email and db_employee.account_status == "pending_verification":
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
                DesiredDeliveryMediums=["EMAIL"],
            )
            new_sub = next(
                (a["Value"] for a in response["User"]["Attributes"] if a["Name"] == "sub"),
                None,
            )
            db_employee.cognito_sub = new_sub
            db_employee.invited_at = datetime.now(timezone.utc)
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

    # Sync Cognito group when role changes on an active account
    elif new_role and new_role != old_role and db_employee.email and db_employee.account_status != "pending_verification":
        cognito_username = db_employee.email
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

    write_audit(
        db=db,
        company_id=caller.company_id,
        actor_id=caller.id,
        action_type="employee.update",
        target_table="employees",
        target_id=str(db_employee.id),
        detail={k: str(v) if v is not None else None for k, v in updates.items()},
    )
    return db_employee


@router.put("/{employee_id}/deactivate", response_model=EmployeeResponse)
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

    # Revoke Cognito session — blocks token refresh immediately
    _cognito_revoke_access(db_employee.email or db_employee.username)

    return db_employee


@router.put("/{employee_id}/reactivate", response_model=EmployeeResponse)
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
    cognito_username = db_employee.username or db_employee.email
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

    # Prefer username — Cognito accounts are created under the derived username.
    # Fall back to email only for legacy accounts predating the username column.
    cognito_username = db_employee.username or db_employee.email

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
ROLE_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "walker":  ("trainer", "captain"),
    "trainer": ("captain", "walker"),
    "captain": ("trainer", "walker"),
}

# Which direction the change is, for the audit trail and the wording of the notice.
# Captain outranks trainer outranks walker (ADR-256 hierarchy).
_ROLE_RANK: dict[str, int] = {"walker": 0, "trainer": 1, "captain": 2}


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
            cognito_username = db_employee.email or db_employee.cognito_sub
            try:
                if old_group:
                    cognito.admin_remove_user_from_group(
                        UserPoolId=settings.aws_cognito_user_pool_id,
                        Username=cognito_username,
                        GroupName=old_group,
                    )
                cognito.admin_add_user_to_group(
                    UserPoolId=settings.aws_cognito_user_pool_id,
                    Username=cognito_username,
                    GroupName=new_group,
                )
            except ClientError as e:
                logger.error("Cognito group sync failed for %s: %s", db_employee.id, e)

    verb = "promoted" if is_promotion else "changed"
    db.add(Notification(
        company_id=db_employee.company_id,
        employee_id=db_employee.id,
        type="role_change",
        message=(
            f"Congratulations! You have been promoted from {old_role} to {new_role} by {caller.name}."
            if is_promotion
            else f"Your role has been updated from {old_role} to {new_role} by {caller.name}."
        ),
    ))
    write_audit(
        db,
        actor_id=str(caller.id),
        company_id=str(caller.company_id),
        action_type=f"employee.role_{verb}",
        target_table="employees",
        target_id=str(db_employee.id),
        before={"role": old_role},
        after={"role": new_role, "captain_pins_cleared": pins_cleared},
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


@router.post("/{employee_id}/transition", response_model=EmployeeResponse)
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

    return _apply_role_transition(db, db_employee, payload.new_role, caller)


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


class _EmailChangeRequest(BaseModel):
    access_token: str
    new_email: EmailStr


@router.post("/me/email/request-change", status_code=status.HTTP_200_OK)
def request_email_change(
    payload: _EmailChangeRequest,
    caller: Employee = Depends(get_caller_employee),
    db: Session = Depends(get_db),
    _: dict = Depends(RoleChecker(["driver", "walker", "trainer", "trainee", "dispatch", "management", "admin"])),
):
    """Step 1: Request an email address change.

    Calls Cognito UpdateUserAttributes with the user's own access token.
    Cognito sends a verification code to the new email address.
    """
    new_email = payload.new_email.strip().lower()

    existing = db.query(Employee).filter(
        Employee.email == new_email,
        Employee.company_id == caller.company_id,
        Employee.id != caller.id,
    ).first()

    if existing:
        raise HTTPException(status_code=409, detail="That email is already in use by another account.")

    cognito = _cognito_client()
    try:
        cognito.update_user_attributes(
            AccessToken=payload.access_token,
            UserAttributes=[{"Name": "email", "Value": new_email}],
        )
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code == "NotAuthorizedException":
            raise HTTPException(status_code=401, detail="Access token is invalid or expired. Please sign in again.")
        logger.error("update_user_attributes failed for %s: %s", caller.id, e.response["Error"]["Code"])
        raise HTTPException(status_code=500, detail="Failed to update email. Please try again.")

    return {"detail": "Verification code sent to the new email address."}


class _EmailConfirmRequest(BaseModel):
    access_token: str
    code: str = Field(..., min_length=4, max_length=10)
    new_email: EmailStr


@router.post("/me/email/confirm-change", status_code=status.HTTP_200_OK)
def confirm_email_change(
    payload: _EmailConfirmRequest,
    caller: Employee = Depends(get_caller_employee),
    db: Session = Depends(get_db),
):
    """Step 2: Confirm the email change with the verification code.

    Calls Cognito VerifyUserAttribute, then updates the employee DB record.
    """
    new_email = payload.new_email.strip().lower()
    code      = payload.code.strip()

    cognito = _cognito_client()
    try:
        cognito.verify_user_attribute(
            AccessToken=payload.access_token,
            AttributeName="email",
            Code=code,
        )
    except ClientError as e:
        code_name = e.response["Error"]["Code"]
        if code_name == "CodeMismatchException":
            raise HTTPException(status_code=400, detail="Incorrect verification code.")
        if code_name == "ExpiredCodeException":
            raise HTTPException(status_code=400, detail="Verification code has expired. Request a new one.")
        if code_name == "NotAuthorizedException":
            raise HTTPException(status_code=401, detail="Access token is invalid or expired. Please sign in again.")
        logger.error("verify_user_attribute failed for %s: %s", caller.id, e.response["Error"]["Code"])
        raise HTTPException(status_code=500, detail="Failed to verify email. Please try again.")

    # Cognito confirmed — sync to our DB
    caller.email = new_email
    db.commit()

    return {"detail": "Email updated successfully.", "email": new_email}

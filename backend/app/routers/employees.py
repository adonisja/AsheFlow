import boto3
import logging
import secrets
from datetime import datetime, timezone, timedelta
from typing import List
from uuid import UUID
from botocore.exceptions import ClientError

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import RoleChecker, Pagination, get_caller_employee
from app.core.config import settings
from app.database import get_db
from app.models.employee import Employee
from app.models.invite_token import InviteToken
from app.models.notification import Notification
from app.schemas.employee import EmployeeCreate, EmployeeUpdate, EmployeeResponse, EmployeePublicResponse, BulkImportRow, BulkImportResult
from app.services.audit import write_audit
from app.services.email import send_invite_email

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/employees", tags=["employees"])

# Cognito group name per role — must match your User Pool group names exactly
ROLE_TO_COGNITO_GROUP: dict[str, str] = {
    "driver":     "driver",
    "walker":     "walker",
    "trainer":    "trainer",
    "trainee":    "trainee",
    "dispatch":   "dispatch",
    "management": "management",
    "admin":      "admin",
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
            results.append(BulkImportResult(
                row=i, status="failed", name=row.name, email=row.email,
                reason=f"Database error: {str(e)}",
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
            results.append(BulkImportResult(
                row=i, status="failed", name=row.name, email=row.email,
                reason=f"Database error: {str(e)}",
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


@router.get("/by-discord/{discord_id}", response_model=EmployeeResponse)
def get_employee_by_discord(
    discord_id: str,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(RoleChecker(list(PRIVILEGED_ROLES | FIELD_ROLES))),
    db: Session = Depends(get_db),
):
    """Fetch an employee by Discord ID. Used by the bot on member-join to assign roles."""
    employee = db.query(Employee).filter(
        Employee.discord_id == discord_id,
        Employee.company_id == caller.company_id,
    ).first()
    if not employee:
        raise HTTPException(status_code=404, detail="No employee found with that Discord ID.")
    return EmployeeResponse.model_validate(employee)


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
            logger.error("Cognito re-invite for corrected email %s failed: %s", new_email, e)
            raise HTTPException(
                status_code=502,
                detail=f"Email updated in DB but Cognito re-invite failed: {e.response['Error']['Message']}",
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

    db_employee.is_active = False
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

    # Re-enable the Cognito user so they can sign in again
    # Prefer username — Cognito accounts are created under the derived username.
    # Fall back to email only for legacy accounts predating the username column.
    cognito_username = db_employee.username or db_employee.email
    if cognito_username:
        try:
            _cognito_client().admin_enable_user(
                UserPoolId=settings.aws_cognito_user_pool_id,
                Username=cognito_username,
            )
        except ClientError as e:
            logger.warning("Cognito admin_enable_user failed for %s: %s", cognito_username, e)

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
    write_audit(
        db,
        actor_id=str(caller.id),
        company_id=str(caller.company_id),
        action_type="employee.deleted",
        target_table="employees",
        target_id=str(employee_id),
        before={
            "name":           db_employee.name,
            "email":          db_employee.email,
            "role":           db_employee.role,
            "username":       db_employee.username,
            "account_status": db_employee.account_status,
            "is_active":      db_employee.is_active,
            "company_id":     str(db_employee.company_id),
        },
    )
    db.delete(db_employee)
    db.commit()


@router.post("/{employee_id}/promote", response_model=EmployeeResponse)
def promote_employee(
    employee_id: UUID,
    caller: Employee = Depends(get_caller_employee),
    current_user: dict = Depends(RoleChecker(["management", "admin"])),
    db: Session = Depends(get_db),
):
    """Promote a walker to trainer.

    Syncs the Cognito group and fires an in-app notification to the employee.
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

    old_role = db_employee.role
    db_employee.role = "trainer"
    db.flush()

    # Sync Cognito group
    if db_employee.cognito_sub and db_employee.account_status == "active":
        cognito = _cognito_client()
        cognito_username = db_employee.email or db_employee.cognito_sub
        try:
            cognito.admin_remove_user_from_group(
                UserPoolId=settings.aws_cognito_user_pool_id,
                Username=cognito_username,
                GroupName=ROLE_TO_COGNITO_GROUP["walker"],
            )
            cognito.admin_add_user_to_group(
                UserPoolId=settings.aws_cognito_user_pool_id,
                Username=cognito_username,
                GroupName=ROLE_TO_COGNITO_GROUP["trainer"],
            )
        except ClientError as e:
            logger.error("Cognito group sync failed for promote %s: %s", employee_id, e)

    # In-app notification
    db.add(Notification(
        company_id=db_employee.company_id,
        employee_id=db_employee.id,
        type="role_change",
        message=f"Congratulations! You have been promoted from {old_role} to trainer by {caller.name}.",
    ))
    write_audit(
        db,
        actor_id=str(caller.id),
        company_id=str(caller.company_id),
        action_type="employee.promoted",
        target_table="employees",
        target_id=str(employee_id),
        before={"role": old_role},
        after={"role": "trainer"},
    )
    db.commit()
    db.refresh(db_employee)
    return db_employee


@router.post("/{employee_id}/demote", response_model=EmployeeResponse)
def demote_employee(
    employee_id: UUID,
    caller: Employee = Depends(get_caller_employee),
    current_user: dict = Depends(RoleChecker(["management", "admin"])),
    db: Session = Depends(get_db),
):
    """Demote a trainer back to walker.

    Syncs the Cognito group and fires an in-app notification to the employee.
    """
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

    old_role = db_employee.role
    db_employee.role = "walker"
    db.flush()

    # Sync Cognito group
    if db_employee.cognito_sub and db_employee.account_status == "active":
        cognito = _cognito_client()
        cognito_username = db_employee.email or db_employee.cognito_sub
        try:
            cognito.admin_remove_user_from_group(
                UserPoolId=settings.aws_cognito_user_pool_id,
                Username=cognito_username,
                GroupName=ROLE_TO_COGNITO_GROUP["trainer"],
            )
            cognito.admin_add_user_to_group(
                UserPoolId=settings.aws_cognito_user_pool_id,
                Username=cognito_username,
                GroupName=ROLE_TO_COGNITO_GROUP["walker"],
            )
        except ClientError as e:
            logger.error("Cognito group sync failed for demote %s: %s", employee_id, e)

    # In-app notification
    db.add(Notification(
        company_id=db_employee.company_id,
        employee_id=db_employee.id,
        type="role_change",
        message=f"Your role has been updated from {old_role} to walker by {caller.name}.",
    ))
    write_audit(
        db,
        actor_id=str(caller.id),
        company_id=str(caller.company_id),
        action_type="employee.demoted",
        target_table="employees",
        target_id=str(employee_id),
        before={"role": old_role},
        after={"role": "walker"},
    )
    db.commit()
    db.refresh(db_employee)
    return db_employee


@router.post("/me/email/request-change", status_code=status.HTTP_200_OK)
def request_email_change(
    payload: dict,
    caller: Employee = Depends(get_caller_employee),
    current_user: dict = Depends(RoleChecker(["driver", "walker", "trainer", "trainee", "dispatch", "management", "admin"])),
):
    """Step 1: Request an email address change.

    Calls Cognito UpdateUserAttributes with the user's own access token.
    Cognito sends a verification code to the new email address.

    Body: { "access_token": "<cognito_access_token>", "new_email": "<email>" }
    """
    access_token = payload.get("access_token")
    new_email    = payload.get("new_email", "").strip().lower()

    if not access_token or not new_email:
        raise HTTPException(status_code=422, detail="access_token and new_email are required.")

    # Basic format check
    if "@" not in new_email or "." not in new_email.split("@")[-1]:
        raise HTTPException(status_code=422, detail="Invalid email address.")

    # Check the new email isn't already taken in our DB
    existing = db_check = None
    try:
        from app.database import SessionLocal
        db_check = SessionLocal()
        existing = db_check.query(Employee).filter(
            Employee.email == new_email,
            Employee.company_id == caller.company_id,
            Employee.id    != caller.id,
        ).first()
    finally:
        if db_check:
            db_check.close()

    if existing:
        raise HTTPException(status_code=409, detail="That email is already in use by another account.")

    cognito = _cognito_client()
    try:
        cognito.update_user_attributes(
            AccessToken=access_token,
            UserAttributes=[{"Name": "email", "Value": new_email}],
        )
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code == "NotAuthorizedException":
            raise HTTPException(status_code=401, detail="Access token is invalid or expired. Please sign in again.")
        raise HTTPException(status_code=400, detail=e.response["Error"]["Message"])

    return {"detail": "Verification code sent to the new email address."}


@router.post("/me/email/confirm-change", status_code=status.HTTP_200_OK)
def confirm_email_change(
    payload: dict,
    caller: Employee = Depends(get_caller_employee),
    db: Session = Depends(get_db),
):
    """Step 2: Confirm the email change with the verification code.

    Calls Cognito VerifyUserAttribute, then updates the employee DB record.

    Body: { "access_token": "<cognito_access_token>", "code": "<6-digit code>", "new_email": "<email>" }
    """
    access_token = payload.get("access_token")
    code         = payload.get("code", "").strip()
    new_email    = payload.get("new_email", "").strip().lower()

    if not access_token or not code or not new_email:
        raise HTTPException(status_code=422, detail="access_token, code, and new_email are required.")

    cognito = _cognito_client()
    try:
        cognito.verify_user_attribute(
            AccessToken=access_token,
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
        raise HTTPException(status_code=400, detail=e.response["Error"]["Message"])

    # Cognito confirmed — sync to our DB
    caller.email = new_email
    db.commit()

    return {"detail": "Email updated successfully.", "email": new_email}

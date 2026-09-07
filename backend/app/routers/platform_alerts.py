"""Platform-level infrastructure alerts, for super admins (ADR-335).

Deliberately NOT on a company-scoped router. A platform alert may have no owning
tenant (a Discord outage is one incident across every company), so there is no
`company_id` to check a caller against — which is exactly why these endpoints
gate on `get_super_admin` rather than `RoleChecker`.
"""
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
import re

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_super_admin, get_platform_staff
from app.core.config import settings
from app.models.platform_alert import PlatformAlert
from app.services import mfa_containment
from app.services.audit import write_audit, super_admin_identity

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/platform", tags=["platform"])


class PlatformAlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    alert_type: str
    company_id: Optional[UUID]
    message: str
    severity: str
    is_resolved: bool
    occurrence_count: int
    first_seen_at: Optional[datetime]
    last_seen_at: Optional[datetime]
    resolved_at: Optional[datetime]
    resolved_by_email: Optional[str]


class ResolveRequest(BaseModel):
    """Dimension 9 — typed, bounded, closed."""
    model_config = ConfigDict(extra="forbid")
    note: Optional[str] = Field(default=None, max_length=500)


@router.get("/alerts", status_code=status.HTTP_200_OK)
def list_platform_alerts(
    include_resolved: bool = Query(False),
    limit: int = Query(100, ge=1, le=500),
    _super: dict = Depends(get_platform_staff),
    db: Session = Depends(get_db),
) -> list[PlatformAlertOut]:
    """Open infrastructure alerts, newest first (ADR-335 D5).

    No company filter: a super admin is looking across tenants, and a
    platform-wide incident has no tenant to filter by.
    """
    q = db.query(PlatformAlert)
    if not include_resolved:
        q = q.filter(PlatformAlert.is_resolved.is_(False))
    rows = q.order_by(PlatformAlert.last_seen_at.desc()).limit(limit).all()
    return [PlatformAlertOut.model_validate(r, from_attributes=True) for r in rows]


class MfaResetRequest(BaseModel):
    """Who to reset. A Cognito Username, not an employee id.

    Deliberately NOT an Employee UUID: the accounts this endpoint exists to
    rescue may have no Employee row at all (a super admin never does), and
    requiring one would rebuild the exact circular dependency this endpoint
    breaks.
    """
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=128)


@router.post("/mfa/reset", status_code=status.HTTP_200_OK)
def platform_reset_mfa(
    body: MfaResetRequest,
    _super: dict = Depends(get_super_admin),
    db: Session = Depends(get_db),
) -> dict:
    """Clear any account's MFA factor, sessions and devices (ADR-389).

    WHY THIS EXISTS ALONGSIDE /employees/{id}/mfa/reset
    That endpoint is gated `RoleChecker(["management", "admin"])`, which resolves
    the caller through an Employee row. A super admin has none by design
    (`get_super_admin` never touches the table), so the platform owner -- the one
    person who should always be able to rescue an account -- could not call it.

    Worse, the same gap runs the other way: a super admin who loses their
    authenticator cannot be reset BY anyone through the product, because the
    other endpoint takes an employee_id they do not have. That is the circular
    lockout ADR-389 documents.

    This endpoint breaks the circle in one direction. The other -- a super admin
    rescuing THEMSELVES -- is deliberately not solved in code, because any
    in-product self-rescue for the highest-privilege account is a backdoor by
    construction. See the break-glass runbook.
    """
    result = mfa_containment.contain(
        username=body.username,
        pool_id=settings.aws_cognito_user_pool_id,
        region=settings.aws_region,
        clear_factor=True,
    )

    write_audit(
        db=db,
        company_id=None,
        actor_id=None,  # super admin has no Employee row; identity goes in detail
        action_type="platform.mfa_reset",
        target_table="cognito_users",
        target_id=body.username,
        detail={
            "actor": super_admin_identity(_super),
            "devices_forgotten": result.devices_forgotten,
            "signed_out": result.signed_out,
            "factor_cleared": result.factor_cleared,
            "errors": result.errors,
        },
    )
    db.commit()

    if not result.fully_contained:
        raise HTTPException(
            status_code=502,
            detail="The reset did not fully complete. Please try again.",
        )
    return {
        "username": body.username,
        "devices_forgotten": result.devices_forgotten,
        "signed_out": result.signed_out,
        "factor_cleared": result.factor_cleared,
    }


# Only these two. This endpoint creates PLATFORM staff; granting a tenant role
# here would produce a Cognito user with no company and no Employee row, which is
# the ghost-account shape that 403s on every request (ADR-394).
PLATFORM_GROUPS = ("super_admin", "platform_support")


def _derive_platform_username(client, name: str) -> str:
    """firstname.lastname, matching every other account in the pool (ADR-396).

    The first version used the EMAIL as the username. It works, and it made this
    the only account type whose username is not a name: `adon`, `walker.test` and
    `manager.test` all follow the convention, and a staff list showing
    `nicoyhunt@gmail.com` twice -- once as username, once as email -- reads as a
    rendering bug rather than as data.

    Uniqueness is checked against COGNITO, not the Employee table.
    registration.py's `_derive_username` queries `Employee.username`, and platform
    staff have no Employee row by design (ADR-274), so that check would happily
    hand out a name Cognito already holds and the create would then 409.

    Bounded for the same reason as ADR-380 D5: a spin here is a bug or an attack,
    and either deserves a refusal.
    """
    parts = name.strip().lower().split()
    first = re.sub(r"[^a-z0-9]", "", parts[0]) if parts else ""
    last = re.sub(r"[^a-z0-9]", "", parts[-1]) if len(parts) > 1 else ""
    base = f"{first}.{last}" if last else first
    if not base:
        # A name of only punctuation would otherwise derive an empty username,
        # which Cognito rejects with an opaque InvalidParameterException.
        raise HTTPException(
            status_code=422,
            detail="Name must contain at least one letter or digit.",
        )

    candidate, suffix, MAX_SUFFIX = base, 2, 100
    while True:
        try:
            client.admin_get_user(
                UserPoolId=settings.aws_cognito_user_pool_id, Username=candidate,
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "UserNotFoundException":
                return candidate  # free
            raise
        if suffix > MAX_SUFFIX:
            logger.error("platform username derivation exhausted for base %r", base)
            raise HTTPException(
                status_code=502,
                detail="Could not allocate a unique username. Please try again.",
            )
        candidate = f"{base}{suffix}"
        suffix += 1


class PlatformStaffCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    name: str = Field(min_length=1, max_length=255)
    group: str = Field(description="super_admin or platform_support")


class PlatformStaffOut(BaseModel):
    username: str
    email: str
    # The person's actual name. Captured on create and, until ADR-396, never read
    # back -- so the list showed username and email, which for an account created
    # here are THE SAME STRING (username = email). A list of identical pairs is
    # not a roster.
    name: str
    group: str
    # True while the group is recorded but NOT granted: the account must enrol a
    # factor before /activate will grant it (ADR-397). Such an account holds no
    # privilege and cannot rescue anyone, which is why the UI labels it.
    pending: bool = False
    status: str


@router.get("/staff", status_code=status.HTTP_200_OK)
def list_platform_staff(
    _staff: dict = Depends(get_platform_staff),
) -> list[PlatformStaffOut]:
    """Who holds platform access (ADR-394).

    A READ, so `get_platform_staff` — a support engineer diagnosing an issue
    should be able to see who else has access without being able to grant it.
    """
    client = boto3.client("cognito-idp", region_name=settings.aws_region)
    out: list[PlatformStaffOut] = []
    for group in PLATFORM_GROUPS:
        try:
            resp = client.list_users_in_group(
                UserPoolId=settings.aws_cognito_user_pool_id,
                GroupName=group, Limit=60,
            )
        except (ClientError, BotoCoreError) as exc:
            logger.error("could not list %s: %s", group, type(exc).__name__)
            continue
        for u in resp.get("Users", []):
            attrs = {a["Name"]: a["Value"] for a in u.get("Attributes", [])}
            out.append(PlatformStaffOut(
                username=u["Username"],
                email=attrs.get("email", ""),
                name=attrs.get("name", ""),
                group=group,
                status=u.get("UserStatus", ""),
            ))

    # Pending accounts hold NO group, so the loop above cannot see them. Without
    # this they would be created and then invisible -- discovered months later as
    # an orphan (ADR-397). Listed last, flagged, so the page shows the work that
    # is not finished.
    seen = {r.username for r in out}
    try:
        resp = client.list_users(
            UserPoolId=settings.aws_cognito_user_pool_id,
            Filter='cognito:user_status = "FORCE_CHANGE_PASSWORD"',
            Limit=60,
        )
        for u in resp.get("Users", []):
            if u["Username"] in seen:
                continue
            attrs = {a["Name"]: a["Value"] for a in u.get("Attributes", [])}
            pending_group = attrs.get("custom:pending_group")
            if not pending_group:
                continue
            out.append(PlatformStaffOut(
                username=u["Username"],
                email=attrs.get("email", ""),
                name=attrs.get("name", ""),
                group=pending_group,
                pending=True,
                status=u.get("UserStatus", ""),
            ))
    except (ClientError, BotoCoreError) as exc:
        # A failure here hides pending accounts but must not hide the real staff
        # list, which is the more important of the two.
        logger.error("could not list pending staff: %s", type(exc).__name__)

    return out


@router.post("/staff", status_code=status.HTTP_201_CREATED)
def create_platform_staff(
    body: PlatformStaffCreate,
    _super: dict = Depends(get_super_admin),
    db: Session = Depends(get_db),
) -> PlatformStaffOut:
    """Create a platform staff account (ADR-394).

    WHY get_super_admin AND NOT get_platform_staff
    ADR-343 D1 split those deliberately: `get_platform_staff` accepts
    `platform_support` and is for endpoints that only READ, so someone onboarded
    to investigate an issue cannot change a customer's world. Creating a super
    admin is the most privileged write there is — a `platform_support` caller
    able to reach it could promote themselves.

    NO EMPLOYEE ROW IS CREATED, deliberately. `get_super_admin` never touches
    that table (ADR-274 D13/D14) because the platform owner has no tenant, and a
    row here would leak them into company-scoped queries. This is the one place
    a Cognito user without an Employee row is correct rather than a ghost.

    Cognito emails the temporary password; no credential is returned. The account
    CANNOT sign in until it enrols MFA — the PreAuthentication trigger refuses a
    privileged group member with no factor — so the username is returned for the
    operator to watch through that first sign-in.
    """
    if body.group not in PLATFORM_GROUPS:
        raise HTTPException(
            status_code=422,
            detail=f"group must be one of: {', '.join(PLATFORM_GROUPS)}",
        )

    client = boto3.client("cognito-idp", region_name=settings.aws_region)
    username = _derive_platform_username(client, body.name)

    try:
        client.admin_create_user(
            UserPoolId=settings.aws_cognito_user_pool_id,
            Username=username,
            UserAttributes=[
                {"Name": "email", "Value": body.email},
                {"Name": "email_verified", "Value": "true"},
                {"Name": "name", "Value": body.name},
                # The group is NOT granted here (ADR-397). PreAuthentication
                # refuses a privileged account with no factor BEFORE issuing any
                # challenge, so granting it now creates an account that can never
                # sign in to enrol. Recorded, then granted by /activate once a
                # factor exists.
                {"Name": "custom:pending_group", "Value": body.group},
            ],
            DesiredDeliveryMediums=["EMAIL"],
        )
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code == "UsernameExistsException":
            raise HTTPException(
                status_code=409, detail="An account with that email already exists.",
            )
        logger.error("platform staff create failed: %s", code)
        raise HTTPException(status_code=502, detail="Could not create the account.")
    except BotoCoreError as exc:
        logger.error("platform staff create failed: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Could not create the account.")

    write_audit(
        db=db,
        company_id=None,
        actor_id=None,  # super admin has no Employee row; identity goes in detail
        action_type="platform.staff_created",
        target_table="cognito_users",
        target_id=username,
        detail={"actor": super_admin_identity(_super),
                "pending_group": body.group, "activated": False},
    )
    db.commit()

    return PlatformStaffOut(
        username=username, email=body.email, name=body.name,
        group=body.group, pending=True,
        status="FORCE_CHANGE_PASSWORD",
    )


@router.post("/staff/{username}/activate", status_code=status.HTTP_200_OK)
def activate_platform_staff(
    username: str,
    _super: dict = Depends(get_super_admin),
    db: Session = Depends(get_db),
) -> PlatformStaffOut:
    """Grant the recorded group, once the account has an MFA factor (ADR-397).

    THE 409 IS THE POINT. Creating an account already in a privileged group makes
    it unable to sign in at all: PreAuthentication reads the groups, sees an empty
    UserMFASettingList, and refuses BEFORE any password challenge -- so it never
    reaches enrolment. Deferring the grant to here means it is impossible for this
    surface to put a privileged group on an unprotected account.
    """
    client = boto3.client("cognito-idp", region_name=settings.aws_region)

    try:
        user = client.admin_get_user(
            UserPoolId=settings.aws_cognito_user_pool_id, Username=username,
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "UserNotFoundException":
            raise HTTPException(status_code=404, detail="No such account.")
        logger.error("activate lookup failed: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Could not read the account.")

    attrs = {a["Name"]: a["Value"] for a in user.get("UserAttributes", [])}
    pending = attrs.get("custom:pending_group")
    if not pending:
        raise HTTPException(
            status_code=409,
            detail="This account has no group awaiting activation.",
        )
    if pending not in PLATFORM_GROUPS:
        # A tampered attribute must not become a grant.
        raise HTTPException(status_code=422, detail="Recorded group is not valid.")

    if not user.get("UserMFASettingList"):
        raise HTTPException(
            status_code=409,
            detail="This account has not set up two-factor authentication yet. "
                   "It must enrol before it can be activated.",
        )

    try:
        client.admin_add_user_to_group(
            UserPoolId=settings.aws_cognito_user_pool_id,
            Username=username, GroupName=pending,
        )
        # Clear the marker only AFTER the grant succeeds, so a failure here leaves
        # the account visibly pending rather than silently orphaned.
        client.admin_delete_user_attributes(
            UserPoolId=settings.aws_cognito_user_pool_id,
            Username=username, UserAttributeNames=["custom:pending_group"],
        )
    except (ClientError, BotoCoreError) as exc:
        logger.error("activate failed for %s: %s", pending, type(exc).__name__)
        raise HTTPException(
            status_code=502, detail="Could not grant the group. Please try again.",
        )

    write_audit(
        db=db, company_id=None, actor_id=None,
        action_type="platform.staff_activated",
        target_table="cognito_users", target_id=username,
        detail={"actor": super_admin_identity(_super), "group": pending},
    )
    db.commit()

    return PlatformStaffOut(
        username=username, email=attrs.get("email", ""), name=attrs.get("name", ""),
        group=pending, pending=False, status=user.get("UserStatus", ""),
    )



@router.post("/alerts/{alert_id}/resolve", status_code=status.HTTP_200_OK)
def resolve_platform_alert(
    alert_id: UUID,
    body: ResolveRequest,
    _super: dict = Depends(get_super_admin),
    db: Session = Depends(get_db),
) -> PlatformAlertOut:
    """Close an alert by hand (ADR-335 D3).

    Most alerts resolve THEMSELVES when the integration answers again. This is
    for a condition the code cannot detect — and it is the only path that sets
    `resolved_by_sub`, which is how a self-resolve is told apart from a human one.
    """
    row = db.query(PlatformAlert).filter(PlatformAlert.id == alert_id).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alert not found.",
        )
    if row.is_resolved:
        # One-way state stamp — 409 rather than silently re-stamping, so a
        # double click cannot overwrite who actually closed it.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That alert is already resolved.",
        )

    row.is_resolved = True
    row.resolved_at = datetime.now(timezone.utc)
    # Text, not an FK. A super admin has no Employee row, and writing their
    # Cognito sub into an employees FK raises ForeignKeyViolation (ADR-274 D13).
    row.resolved_by_sub = _super.get("id")
    row.resolved_by_email = _super.get("email")

    db.flush()
    write_audit(
        db=db,
        # Platform-scoped: the alert may belong to no tenant.
        company_id=str(row.company_id) if row.company_id else None,
        actor_id=None,  # ADR-274 D13 — super admins leave actor_id NULL
        action_type="platform_alert.resolved",
        target_table="platform_alerts",
        target_id=str(row.id),
        after={**super_admin_identity(_super),
               "alert_type": row.alert_type,
               "note": body.note},
    )
    db.commit()
    db.refresh(row)
    return PlatformAlertOut.model_validate(row, from_attributes=True)

"""Platform-level infrastructure alerts, for super admins (ADR-335).

Deliberately NOT on a company-scoped router. A platform alert may have no owning
tenant (a Discord outage is one incident across every company), so there is no
`company_id` to check a caller against — which is exactly why these endpoints
gate on `get_super_admin` rather than `RoleChecker`.
"""
import secrets
import string
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
import re

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_super_admin, get_platform_staff
from app.core.config import settings
from app.models.platform_alert import PlatformAlert
from app.services import account_security, mfa_containment, mfa_reset_requests
from app.services.audit import write_audit, super_admin_identity
from app.services.email import send_credentials_email

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
    # ADR-543 D2/D3 — who an account alert is about. subject_ref (the account
    # handle) is blanked for platform support (ADR-343 D4); kind and role stay.
    subject_kind: Optional[str] = None
    subject_ref: Optional[str] = None
    subject_role: Optional[str] = None
    # ADR-544 — actions taken on the account. Who acted is a super admin's
    # email, which support may see as the same field resolved_by_email is.
    reminded_at: Optional[datetime] = None
    reminded_by_email: Optional[str] = None
    reminder_count: int = 0
    sessions_ended_at: Optional[datetime] = None
    sessions_ended_by_email: Optional[str] = None


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
    out = [PlatformAlertOut.model_validate(r, from_attributes=True) for r in rows]
    # ADR-543 D3: the account handle is for super admins. Platform support is a
    # cross-tenant login and may not see personal identifiers (ADR-343 D4).
    if "super_admin" not in set(_super.get("cognito_groups") or []):
        for a in out:
            a.subject_ref = None
    return out


class MfaResetRequest(BaseModel):
    """Who to reset: an account ID (preferred) or a Cognito Username (ADR-550 D3).

    Never an Employee UUID: the accounts this endpoint exists to rescue may
    have no Employee row (a super admin never does), and requiring one would
    rebuild the circular dependency it breaks.

    `account_id` is the Cognito sub -- the permanent ID shown on Platform staff.
    A name typed into a reset box is how the wrong account gets reset, so the
    page resets staff by ID. `username` stays for rescuing a tenant admin by
    name, the case ADR-389 built this for. Exactly one.
    """
    model_config = ConfigDict(extra="forbid")
    account_id: Optional[UUID] = None
    username: Optional[str] = Field(default=None, min_length=1, max_length=128)
    # ADR-561 D3: optional; shown to the person in the reset notice.
    reason: Optional[str] = Field(default=None, min_length=10, max_length=200)

    @model_validator(mode="after")
    def _exactly_one(self):
        if (self.account_id is None) == (self.username is None):
            raise ValueError("Give exactly one of account_id or username.")
        return self


def _resolve_account(client, *, account_id: Optional[UUID], username: Optional[str]) -> tuple[str, str]:
    """(username, sub) for the account to reset; 404 if Cognito has none.

    By sub, via list_users -- `account_id` is a validated UUID, so the filter
    string cannot be injected into. By username, via admin_get_user."""
    pool = settings.aws_cognito_user_pool_id
    try:
        if account_id is not None:
            users = client.list_users(UserPoolId=pool, Filter=f'sub = "{account_id}"', Limit=1).get("Users", [])
            if not users:
                raise HTTPException(status_code=404, detail="No account has that ID.")
            return users[0]["Username"], str(account_id)
        u = client.admin_get_user(UserPoolId=pool, Username=username)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "UserNotFoundException":
            raise HTTPException(status_code=404, detail="No account has that username.")
        logger.error("mfa reset: could not resolve account: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Could not look up the account. Try again.")
    except BotoCoreError as exc:
        logger.error("mfa reset: could not resolve account: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Could not look up the account. Try again.")
    # The `sub` USER ATTRIBUTE from Cognito -- not a JWT claim (get_current_user
    # exposes the claim as "id"; the claim-key guard in test_audit_coverage
    # rightly flags .get("sub") on a claims dict, so read it by name here).
    sub = next((a.get("Value") for a in u.get("UserAttributes", []) if a.get("Name") == "sub"), None)
    if not sub:
        raise HTTPException(status_code=502, detail="Could not look up the account. Try again.")
    return u["Username"], sub


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
    username, sub = _resolve_account(boto3.client("cognito-idp", region_name=settings.aws_region),
                                     account_id=body.account_id, username=body.username)
    result = mfa_containment.contain(
        username=username,
        pool_id=settings.aws_cognito_user_pool_id,
        region=settings.aws_region,
        clear_factor=True,
    )
    # ADR-550 D4: end sessions here too, not only at Cognito.
    kind = account_security.mark_sessions_ended(db, sub)
    # ADR-551 D4: closes the account's reset request, if any.
    mfa_reset_requests.resolve_for(db, sub, by_kind="super_admin", by_ref=_super.get("id"))
    from app.services.note_scrub import scrub_note
    reason = (scrub_note(body.reason.strip())[0] or "").strip() or None if body.reason else None

    write_audit(
        db=db,
        company_id=None,
        actor_id=None,  # super admin has no Employee row; identity goes in detail
        action_type="platform.mfa_reset",
        target_table="cognito_users",
        # The SUB, never the username: write_audit drops a non-UUID target, and
        # passing the username meant no platform reset was ever recorded
        # (ADR-550; prod had 0 platform.mfa_reset rows).
        target_id=sub,
        detail={
            "actor": super_admin_identity(_super),
            "target_username": username,
            "account_kind": kind,
            "reason": reason,
            "devices_forgotten": result.devices_forgotten,
            "signed_out": result.signed_out,
            "factor_cleared": result.factor_cleared,
            "errors": result.errors,
        },
    )
    db.commit()

    # ADR-561: tell them. A tenant admin rescued here (ADR-389) hears it from
    # the AsheFlow team too, and their manager can't act on a super admin's reset.
    emailed = account_security.notify_mfa_reset(
        username, reset_by="The AsheFlow team", account="your AsheFlow account",
        if_not_you="reply to this email so we can check your account",
        account_ref=sub, reason=reason)

    if not result.fully_contained:
        raise HTTPException(
            status_code=502,
            detail="The reset did not fully complete. Please try again.",
        )
    return {
        "username": username,
        "account_id": sub,
        "emailed": emailed,
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
    # ADR-550 D1: the staff member's account ID -- the Cognito sub, permanent
    # and unique. Names repeat and emails change; this does not.
    account_id: str = ""
    # ADR-551 D3: they asked for a two-factor reset (pending, last 7 days).
    reset_requested_at: Optional[datetime] = None
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
    # ADR-444 D1 / ADR-442 D2. Cognito's email is suppressed, so OUR send is the
    # only delivery. If it fails the account exists with a password nobody has
    # and no reset path (it cannot sign in to request one), so the credential
    # comes back here instead. None on the happy path — never returned when the
    # email actually went out.
    email_delivered: bool = True
    temp_password: str | None = None


@router.get("/staff", status_code=status.HTTP_200_OK)
def list_platform_staff(
    _staff: dict = Depends(get_platform_staff),
    db: Session = Depends(get_db),
) -> list[PlatformStaffOut]:
    return _with_reset_requests(_list_platform_staff(), db)


def _list_platform_staff() -> list[PlatformStaffOut]:
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
                account_id=attrs.get("sub", ""),
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
                account_id=attrs.get("sub", ""),
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


def _with_reset_requests(rows: list[PlatformStaffOut], db: Session) -> list[PlatformStaffOut]:
    """ADR-551 D3: mark the staff rows whose owner asked for a reset."""
    requested = mfa_reset_requests.pending_since(db, [r.account_id for r in rows if r.account_id])
    for r in rows:
        r.reset_requested_at = requested.get(r.account_id)
    return rows


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

    # ADR-444 D1. GENERATED HERE, because the create below suppresses Cognito's
    # email and nobody would ever see the one it makes. Same shape as the
    # employee generator in registration.py: mixed case, digits and symbols, so
    # it satisfies the pool policy without depending on its exact settings.
    temp_password = (
        secrets.choice(string.ascii_uppercase) +
        secrets.choice(string.ascii_uppercase) +
        secrets.choice(string.digits) +
        secrets.choice(string.digits) +
        secrets.choice(string.digits) +
        secrets.choice(string.ascii_lowercase) +
        secrets.choice(string.ascii_lowercase) +
        secrets.choice("!@#$%^&*") +
        secrets.choice("!@#$%^&*")
    )

    try:
        client.admin_create_user(
            UserPoolId=settings.aws_cognito_user_pool_id,
            Username=username,
            TemporaryPassword=temp_password,
            # ADR-444 D1. Cognito's stock template is a plain-text line carrying
            # a live credential — the exact shape of a phishing email. Training
            # people to accept it trains them to accept the forgery; the branded
            # template is what makes "if it doesn't look like this, it isn't us"
            # a usable rule.
            MessageAction="SUPPRESS",
            UserAttributes=[
                {"Name": "email", "Value": body.email},
                # ADR-564: verified by signing in with the emailed password.
                {"Name": "email_verified", "Value": "false"},
                {"Name": "name", "Value": body.name},
                # The group is NOT granted here (ADR-397). PreAuthentication
                # refuses a privileged account with no factor BEFORE issuing any
                # challenge, so granting it now creates an account that can never
                # sign in to enrol. Recorded, then granted by /activate once a
                # factor exists.
                {"Name": "custom:pending_group", "Value": body.group},
            ],
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

    # ADR-444 D1. The branded credentials email, the same one every employee
    # gets. ADR-442 D2's rule applies: if the send fails, the password comes
    # back in the response rather than stranding an account nobody can reach.
    email_delivered = True
    try:
        send_credentials_email(
            to_email=body.email,
            employee_name=body.name,
            username=username,
            temp_password=temp_password,
        )
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "Unknown")
        logger.error("platform staff credentials email failed (%s)", code)
        email_delivered = False
    account_security.record_password_delivery(username, emailed=email_delivered)   # ADR-564 D3

    write_audit(
        db=db,
        company_id=None,
        actor_id=None,  # super admin has no Employee row; identity goes in detail
        action_type="platform.staff_created",
        target_table="cognito_users",
        target_id=username,
        detail={"actor": super_admin_identity(_super),
                "pending_group": body.group, "activated": False,
                # ADR-444 D1. Recorded because a suppressed Cognito email means
                # a failed send is otherwise invisible in the audit trail.
                "email_delivered": email_delivered},
    )
    db.commit()

    return PlatformStaffOut(
        username=username, email=body.email, name=body.name,
        group=body.group, pending=True,
        status="FORCE_CHANGE_PASSWORD",
        email_delivered=email_delivered,
        temp_password=None if email_delivered else temp_password,
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


# ── ADR-544: act on the account an alert is about ─────────────────────────────
#
# Super admin only (ADR-343: platform support never acts on an account). Both
# need an ACCOUNT alert of an actionable type: an infrastructure alert names no
# account to act on.

REMINDABLE = {"mfa.privileged_unprotected"}
REMINDER_COOLDOWN_SECONDS = 24 * 3600


def _account_alert_or_error(db: Session, alert_id: UUID) -> PlatformAlert:
    row = db.query(PlatformAlert).filter(PlatformAlert.id == alert_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Alert not found.")
    if row.is_resolved:
        raise HTTPException(status_code=409, detail="That alert is already resolved.")
    if not row.subject_ref or row.alert_type not in REMINDABLE:
        raise HTTPException(status_code=400, detail="This alert isn't about an account, so there's no one to act on.")
    return row


def _verified_email(username: str) -> str | None:
    """The account's email if Cognito marks it verified; None otherwise."""
    try:
        attrs = boto3.client("cognito-idp", region_name=settings.aws_region).admin_get_user(
            UserPoolId=settings.aws_cognito_user_pool_id, Username=username,
        ).get("UserAttributes", [])
    except (ClientError, BotoCoreError):
        return None
    a = {x["Name"]: x["Value"] for x in attrs}
    return a.get("email") if a.get("email_verified") == "true" and a.get("email") else None


@router.post("/alerts/{alert_id}/remind", status_code=status.HTTP_200_OK)
def remind_alert_account(
    alert_id: UUID,
    _super: dict = Depends(get_super_admin),
    db: Session = Depends(get_db),
) -> PlatformAlertOut:
    """D1 — email the account a reminder to set up MFA. Once per 24 hours."""
    row = _account_alert_or_error(db, alert_id)
    now = datetime.now(timezone.utc)
    if row.reminded_at is not None:
        last = row.reminded_at if row.reminded_at.tzinfo else row.reminded_at.replace(tzinfo=timezone.utc)
        if (now - last).total_seconds() < REMINDER_COOLDOWN_SECONDS:
            raise HTTPException(status_code=429, detail="A reminder was sent less than 24 hours ago.")

    to = _verified_email(row.subject_ref)
    if not to:
        raise HTTPException(
            status_code=409,
            detail="This account has no verified email to remind. Sign them out instead.",
        )
    from app.services.email import send_mfa_setup_reminder
    try:
        send_mfa_setup_reminder(to_email=to, account_ref=row.subject_ref)
    except ClientError:
        raise HTTPException(status_code=502, detail="Couldn't send the reminder. Try again.")

    row.reminded_at = now
    row.reminded_by_email = _super.get("email")
    row.reminder_count = (row.reminder_count or 0) + 1
    db.flush()
    write_audit(
        db=db,
        company_id=str(row.company_id) if row.company_id else None,
        actor_id=None,  # ADR-274 D13
        action_type="platform_alert.account_reminded",
        target_table="platform_alerts",
        target_id=str(row.id),
        after={**super_admin_identity(_super), "alert_type": row.alert_type,
               "subject_kind": row.subject_kind, "reminder_count": row.reminder_count},
    )
    db.commit()
    db.refresh(row)
    return PlatformAlertOut.model_validate(row, from_attributes=True)


@router.post("/alerts/{alert_id}/sign-out", status_code=status.HTTP_200_OK)
def sign_out_alert_account(
    alert_id: UUID,
    _super: dict = Depends(get_super_admin),
    db: Session = Depends(get_db),
) -> PlatformAlertOut:
    """D2 — end every session and forget every device (ADR-387's containment).

    clear_factor=False: if MFA was removed by an attacker, adding a factor back
    is the victim's job; if they never had one, PreAuthentication refuses their
    next privileged sign-in until they enrol (ADR-530).
    """
    row = _account_alert_or_error(db, alert_id)
    result = mfa_containment.contain(
        username=row.subject_ref,
        pool_id=settings.aws_cognito_user_pool_id,
        region=settings.aws_region,
        clear_factor=False,
    )
    if row.subject_kind == "employee" and row.company_id is not None:
        # ADR-541 D2 — refuse the existing access tokens here at once; Cognito's
        # sign-out only stops refreshes. Scoped to the alert's company.
        from app.models.employee import Employee
        emp = db.query(Employee).filter(
            Employee.company_id == row.company_id,
            (Employee.username == row.subject_ref) | (Employee.email == row.subject_ref),
        ).first()
        if emp is not None:
            emp.tokens_valid_after = datetime.now(timezone.utc)

    # Only claim it on the card when Cognito confirmed it. The attempt is
    # audited either way, with what actually happened.
    if result.signed_out:
        row.sessions_ended_at = datetime.now(timezone.utc)
        row.sessions_ended_by_email = _super.get("email")
    db.flush()
    write_audit(
        db=db,
        company_id=str(row.company_id) if row.company_id else None,
        actor_id=None,  # ADR-274 D13
        action_type="platform_alert.account_signed_out",
        target_table="platform_alerts",
        target_id=str(row.id),
        after={**super_admin_identity(_super), "alert_type": row.alert_type,
               "subject_kind": row.subject_kind,
               "signed_out": result.signed_out,
               "devices_forgotten": result.devices_forgotten,
               "errors": result.errors[:5]},
    )
    db.commit()
    db.refresh(row)
    if not result.signed_out:
        raise HTTPException(status_code=502, detail="Cognito didn't confirm the sign-out. Try again.")
    return PlatformAlertOut.model_validate(row, from_attributes=True)


# ── ADR-563 D3: a super admin changes a PLATFORM account's email ──────────
# For a super admin, platform support or surveyor who lost access to their
# inbox. Never a tenant employee: that's their company's admin
# (/employees/{id}/email/change). Nothing changes until the link sent to the
# new address is used.

class PlatformEmailChangeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_id: UUID
    new_email: EmailStr


def _platform_target(account_id: UUID, _super: dict) -> tuple[str, str, str]:
    from app.api.deps import PLATFORM_ACCOUNT_GROUPS
    from app.services import email_change
    if str(account_id) == str(_super.get("id")):
        raise HTTPException(status_code=400, detail="Change your own email from My account.")
    username, sub = _resolve_account(boto3.client("cognito-idp", region_name=settings.aws_region),
                                     account_id=account_id, username=None)
    acct = email_change.cognito_account(username)
    groups = acct["groups"] if acct else set()
    if not (groups & PLATFORM_ACCOUNT_GROUPS):
        raise HTTPException(status_code=403,
                            detail="That's a company account; its company's admin changes its email.")
    kind = "surveyor" if "surveyor" in groups else "staff"
    return username, sub, kind


@router.post("/accounts/email/change", status_code=status.HTTP_200_OK)
def platform_start_email_change(body: PlatformEmailChangeIn, _super: dict = Depends(get_super_admin),
                                db: Session = Depends(get_db)) -> dict:
    from app.services import email_change
    username, sub, kind = _platform_target(body.account_id, _super)
    try:
        expires = email_change.start_admin_change(
            db, username=username, kind=kind, company_id=None, new_email=str(body.new_email),
            by_kind="super_admin", by_ref=str(_super.get("id")), by_label="The AsheFlow team")
    except email_change.EmailChangeError as e:
        raise HTTPException(status_code=e.status, detail=e.detail)
    return {"detail": "Confirmation sent to the new address.",
            "pending_email_masked": account_security.mask_email(str(body.new_email).lower()),
            "expires_at": expires.isoformat()}


@router.delete("/accounts/{account_id}/email/change", status_code=status.HTTP_200_OK)
def platform_cancel_email_change(account_id: UUID, _super: dict = Depends(get_super_admin),
                                 db: Session = Depends(get_db)) -> dict:
    from app.services import email_change
    _username, sub, _kind = _platform_target(account_id, _super)
    return {"cancelled": email_change.cancel_admin_change(db, sub=sub, by_kind="super_admin",
                                                          by_ref=str(_super.get("id")))}

import logging

from fastapi import Depends, HTTPException, Query, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from app.models.employee import Employee
from app.core.security import verify_cognito_token
from app.database import get_db
from app.services.constants import OVERSIGHT_ROLES
from app.core.config import settings

logger = logging.getLogger(__name__)

# This tells FastAPI an endpoint requires a "Bearer" token in the Authorization header.
# It also adds the "Authorize" padlock button to our /docs Swagger UI automatically!
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    """FastAPI dependency that verifies the JWT and returns the authenticated user's claims.

    Extracts the Bearer token from the ``Authorization`` header, delegates
    cryptographic verification to ``verify_cognito_token``, then returns a
    normalized user dict for use in route handlers.

    Args:
        token: JWT string injected by FastAPI's ``OAuth2PasswordBearer`` scheme.

    Returns:
        A dict with ``id`` (Cognito ``sub``), ``email``, and ``cognito_groups``.

    Raises:
        HTTPException(401): If the token is invalid, expired, or missing the
            ``sub`` claim.
    """
    # 1. Hand the raw token to our custome crytographic engine
    payload = verify_cognito_token(token)

    # 2. Extract standard user identifiers
    # Cognito stores the unique user ID in 'sub' and the email in 'email'
    user_id = payload.get("sub")
    email = payload.get("email")

    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token is valid, but missing user identity (sub) claim.",
        )
    
    # 3. Return the user data so the router can use it (e.g., to look up the DB record)
    # ID tokens use 'cognito:username'; access tokens use 'username'. Support both.
    username = payload.get("cognito:username") or payload.get("username", "")
    return {
        "id": user_id,
        "email": email,
        "username": username,
        "cognito_groups": payload.get("cognito:groups", [])
    }

def _resolve_employee_from_cognito(current_user: dict, db: Session):
    """Shared lookup chain: cognito_sub → discord_id → email → UUID fallback.

    Returns the Employee if found, else None.  Also stamps cognito_sub on first
    login so future calls take the fast path.  Does NOT commit activation logic
    (that's handled by the non-optional caller that knows the account lifecycle).
    """
    from app.models.employee import Employee
    from uuid import UUID as _UUID

    sub      = current_user.get("id", "")
    username = current_user.get("username", "")
    email    = current_user.get("email", "")

    employee = None

    # Fast path: cognito_sub stamped on first login
    if sub:
        employee = db.query(Employee).filter(Employee.cognito_sub == sub).first()

    if not employee and username:
        # Legacy path — fires only when cognito_sub is not yet stamped.
        # Not company-scoped (company_id unknown until employee is resolved);
        # username collisions across tenants are possible but extremely unlikely
        # for human-readable usernames. Stamp cognito_sub after resolution so
        # subsequent calls take the globally-unique fast path.
        logger.warning(
            "SC-3 fallback: resolving employee by username=%r (cognito_sub fast-path missed). "
            "sub=%r — cognito_sub will be stamped after resolution.",
            username, sub,
        )
        # New pool: username is danny.rivera — match Employee.username
        employee = db.query(Employee).filter(Employee.username == username).first()
        # Old pool fallback: username was the discord_id
        if not employee:
            employee = db.query(Employee).filter(Employee.discord_id == username).first()

    if not employee and email:
        logger.warning(
            "SC-3 fallback: resolving employee by email=%r (username fallback also missed). "
            "sub=%r — cognito_sub will be stamped after resolution.",
            email, sub,
        )
        employee = db.query(Employee).filter(Employee.email == email).first()

    if not employee and sub:
        try:
            employee = db.query(Employee).filter(Employee.id == _UUID(sub)).first()
        except (ValueError, AttributeError):
            pass

    return employee, sub


def get_caller_employee(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Resolve the Employee DB record for the authenticated caller.

    Matches on discord_id == current_user['username'] (Cognito username).
    Raises 403 if no employee record exists for the caller — prevents ghost
    users from submitting field-ops records on behalf of real employees.
    """
    employee, sub = _resolve_employee_from_cognito(current_user, db)

    needs_commit = False

    # Stamp cognito_sub on first login so future calls take the fast path
    if employee and sub and not employee.cognito_sub:
        employee.cognito_sub = sub
        needs_commit = True

    # Activate on first successful login regardless of when cognito_sub was stamped
    # (registration now stamps it before the employee ever signs in)
    if employee and employee.account_status == "pending_verification":
        employee.account_status = "active"
        employee.is_active = True
        needs_commit = True
        _send_discord_invite(employee)

    if needs_commit:
        db.commit()

    if not employee:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No employee record found for your account. Contact your manager.",
        )
    return employee


def _send_discord_invite(employee) -> None:
    """Get a guild invite URL from the bot and email it to the employee — best effort, non-blocking."""
    import threading
    import requests
    from app.services.email import send_discord_invite_email
    from botocore.exceptions import ClientError

    def _fire():
        
        log = __import__("logging").getLogger(__name__)
        if not employee.email:
            log.warning("No email on file for %s — skipping Discord invite email.", employee.name)
            return
        try:
            bot_url = settings.bot_internal_url
            secret  = settings.internal_secret
            resp = requests.post(
                f"{bot_url}/internal/invite",
                json={"name": employee.name, "company_id": str(employee.company_id)},
                headers={"X-Internal-Secret": secret},
                timeout=10,
            )
            resp.raise_for_status()
            invite_url = resp.json().get("invite_url")
            if not invite_url:
                log.error("Bot returned no invite_url for %s.", employee.name)
                return
        except Exception as e:
            log.warning("Discord invite bot call failed for %s: %s", employee.name, e)
            return

        try:
            send_discord_invite_email(
                to_email=employee.email,
                employee_name=employee.name,
                invite_url=invite_url,
            )
        except ClientError as e:
            log.error("Discord invite email failed for %s: %s", employee.email, e)

    threading.Thread(target=_fire, daemon=True).start()


def get_caller_employee_optional(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Same lookup chain as ``get_caller_employee`` but returns ``None`` instead of
    raising 403 when no employee record is found.

    Use this for audit/attribution fields (e.g. resolved_by) where the caller
    not being in the DB should not block the operation.
    """
    employee, sub = _resolve_employee_from_cognito(current_user, db)

    if employee and sub and not employee.cognito_sub:
        employee.cognito_sub = sub
        db.commit()

    return employee  # may be None — caller decides what to do


class Pagination:
    """Reusable query-parameter dependency for offset-based pagination.

    Usage::

        @router.get("/")
        def list_things(pg: Pagination = Depends(), db: Session = Depends(get_db)):
            q = db.query(Thing)
            return pg.apply(q).all()

    Adds ``?skip=0&limit=100`` to every endpoint that uses it.
    ``limit`` is capped at 500 to prevent accidental full-table dumps.
    """

    MAX_LIMIT = 500

    def __init__(
        self,
        skip:  int = Query(default=0,   ge=0,   description="Number of records to skip"),
        limit: int = Query(default=100, ge=1,   description="Maximum records to return (max 500)"),
    ):
        self.skip  = skip
        self.limit = min(limit, self.MAX_LIMIT)

    def apply(self, query):
        return query.offset(self.skip).limit(self.limit)


def get_super_admin(current_user: dict = Depends(get_current_user)) -> dict:
    """Dependency for super-admin-only endpoints.

    Reads the JWT groups and returns the claims dict if the caller belongs to
    the 'super_admin' Cognito group. Raises 403 otherwise.

    Intentionally never touches the Employee table — the platform owner has no
    Employee row. Do NOT use this on company-scoped endpoints.
    """
    if "super_admin" not in current_user.get("cognito_groups", []):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super admin access required.",
        )
    return current_user


class RoleChecker:
    """Dependency class to check if a user has the required roles."""
    def __init__(self, allowed_roles: list[str]):
        self.allowed_roles = allowed_roles

    def __call__(self, user: dict = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
        from app.models.employee import Employee

        sub   = user.get("id", "")
        email = user.get("email", "")

        employee = None
        if sub:
            employee = db.query(Employee).filter(Employee.cognito_sub == sub).first()
        if not employee and email:
            employee = db.query(Employee).filter(Employee.email == email).first()

        if employee:
            # DB role is authoritative — JWT claim may be stale after a role change
            if employee.role not in self.allowed_roles:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Operation not permitted. Insufficient role permissions."
                )
        else:
            # No employee row (super admin or platform account) — fall back to JWT groups
            if not any(role in user.get("cognito_groups", []) for role in self.allowed_roles):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Operation not permitted. Insufficient role permissions."
                )

        return user


_PRIVILEGED_ROLES = frozenset(OVERSIGHT_ROLES)


def require_configured(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Dependency that blocks any request if the caller's company has not
    completed initial setup.  Add to APIRouter(dependencies=[...]) for
    every router except the companies config router and registration router.

    Super admins have no Employee row and are never company-scoped — they
    bypass this check entirely.
    """
    if "super_admin" in current_user.get("cognito_groups", []):
        return

    # Resolve the Employee row to get company_id
    employee, _ = _resolve_employee_from_cognito(current_user, db)
    if not employee:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No employee record found for your account. Contact your manager.",
        )

    row = _company_config_for_request(db, employee.company_id)
    if row is None or not row.is_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Company setup is not complete. An admin must finish configuration before the platform can be used.",
        )


def _company_config_for_request(db: Session, company_id):
    """CompanyConfig for this company, memoised on the request's Session.

    ``require_configured`` and ``RequireMode`` both run on every gated request and
    both need this row. ``filter().first()`` does NOT hit SQLAlchemy's identity map
    (verified: two calls emit two SELECTs), so without this a gated endpoint pays a
    second round trip on the hot path of the busiest routers.

    ``get_db`` yields a fresh Session per request and closes it after, so the cache
    cannot outlive the request or leak across tenants. Keyed by company_id anyway,
    so a request that legitimately touches two companies stays correct.
    """
    from app.models.company import CompanyConfig

    cache = getattr(db, "_asheflow_config_cache", None)
    if cache is None:
        cache = {}
        db._asheflow_config_cache = cache
    if company_id not in cache:
        cache[company_id] = (
            db.query(CompanyConfig)
            .filter(CompanyConfig.company_id == company_id)
            .first()
        )
    return cache[company_id]


class RequireMode:
    """Gate a router on the caller's company operating_mode (ADR-289).

    Add to ``APIRouter(dependencies=[...])`` — or to ``include_router(...,
    dependencies=[...])`` — for every router whose feature only exists when the
    tenant has an Amazon package feed::

        api_v1_router.include_router(
            sort.router, dependencies=_configured + [Depends(RequireMode(MODE_FULL))]
        )

    **404, not 403.** A 403 says "this exists and you may not have it", which invites
    retries and leaks the shape of the product to a tenant who will never have it. A 404
    says "this company does not have this feature", which is the truth. The detail string
    is deliberately generic for the same reason.

    Super admins have no Employee row and are never company-scoped, so they bypass this
    exactly as ``require_configured`` does — otherwise a platform operator could not
    inspect a workforce tenant's endpoints at all.

    A missing CompanyConfig row is treated as NOT having the mode. That is the safe
    direction: the alternative (assume ``full``) would expose the package pipeline to a
    tenant whose configuration never said so.
    """

    def __init__(self, required: str):
        self.required = required

    def __call__(
        self,
        current_user: dict = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> None:
        if "super_admin" in current_user.get("cognito_groups", []):
            return

        employee, _ = _resolve_employee_from_cognito(current_user, db)
        if not employee:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No employee record found for your account. Contact your manager.",
            )

        row = _company_config_for_request(db, employee.company_id)
        if row is None or row.operating_mode != self.required:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Not found.",
            )


def assert_owns_or_privileged(
    caller,
    target_id: str,
    resource: str = "resource",
    target_company_id=None,
) -> None:
    """Raise 403 unless caller owns the resource or has a privileged role within the same tenant.

    Args:
        caller:             Employee ORM object returned by ``get_caller_employee``.
        target_id:          String UUID of the resource owner.
        resource:           Human-readable noun for the error message.
        target_company_id:  company_id of the target record, when available.
                            Omit only for self-owned resources (where target_id == caller.id).
    """
    owns = str(caller.id) == str(target_id)
    privileged = caller.role in _PRIVILEGED_ROLES

    if not owns and not privileged:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"You do not have permission to access this {resource}.",
        )

    # Privileged callers must still be in the same tenant as the target record.
    if privileged and target_company_id is not None:
        if str(caller.company_id) != str(target_company_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"You do not have permission to access this {resource}.",
            )
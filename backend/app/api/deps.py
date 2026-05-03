from fastapi import Depends, HTTPException, Query, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from app.core.security import verify_cognito_token
from app.database import get_db
from app.services.constants import OVERSIGHT_ROLES

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
    if sub:
        employee = db.query(Employee).filter(Employee.cognito_sub == sub).first()

    if not employee:
        if username:
            employee = db.query(Employee).filter(Employee.discord_id == username).first()
        if not employee and email:
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

    if employee and sub and not employee.cognito_sub:
        employee.cognito_sub = sub
        # Stamp cognito_sub permanently so future logins use the fast path.
        # Also activate the account on first successful login.
        if employee.account_status == "pending_verification":
            employee.account_status = "active"
            employee.is_active = True
            db.commit()
            # Fire Discord server invite in the background — best effort
            _send_discord_invite(employee.discord_id, employee.name)
        else:
            db.commit()

    if not employee:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No employee record found for your account. Contact your manager.",
        )
    return employee


def _send_discord_invite(discord_id: str, name: str) -> None:
    """Fire a POST to the bot's /internal/invite endpoint — best effort, non-blocking."""
    import threading
    import requests
    import os

    def _fire():
        try:
            bot_url = os.environ.get("BOT_INTERNAL_URL", "http://bot:8001")
            secret  = os.environ.get("INTERNAL_SECRET") or ""
            requests.post(
                f"{bot_url}/internal/invite",
                json={"discord_id": discord_id, "name": name},
                headers={"X-Internal-Secret": secret},
                timeout=5,
            )
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                "Discord invite webhook failed for %s (%s): %s", name, discord_id, e
            )

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


class RoleChecker:
    """Dependency class to check if a user has the required roles."""
    def __init__(self, allowed_roles: list[str]):
        self.allowed_roles = allowed_roles

    def __call__(self, user: dict = Depends(get_current_user)) -> dict:
        user_groups = user.get("cognito_groups", [])
        
        # Check if the user has at least one of the allowed roles
        if not any(role in user_groups for role in self.allowed_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Operation not permitted. Insufficient role permissions."
            )
        
        # Return the user so the endpoint can still access their info
        return user


_PRIVILEGED_ROLES = frozenset(OVERSIGHT_ROLES)


def assert_owns_or_privileged(caller, target_id: str, resource: str = "resource") -> None:
    """Raise 403 unless caller owns the resource or has a privileged role.

    Usage::

        assert_owns_or_privileged(caller, employee_id)

    Args:
        caller:      Employee ORM object returned by ``get_caller_employee``.
        target_id:   String UUID of the resource owner.
        resource:    Human-readable noun for the error message.
    """
    if str(caller.id) != str(target_id) and caller.role not in _PRIVILEGED_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"You do not have permission to access this {resource}.",
        )
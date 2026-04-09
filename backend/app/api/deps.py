from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from app.core.security import verify_cognito_token

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
    return {
        "id": user_id,
        "email": email,
        "cognito_groups": payload.get("cognito:groups", [])
    }

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
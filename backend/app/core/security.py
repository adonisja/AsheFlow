import json
from urllib.request import urlopen
import jwt
from fastapi import HTTPException, status
from jwt.algorithms import RSAAlgorithm

from app.core.config import settings

# I'll construct the Cognito Issuer ULR dynamically using my .ev variables
COGNITO_ISSUER = f"https://cognito-idp.{settings.aws_region}.amazonaws.com/{settings.aws_cognito_user_pool_id}"
JWKS_URL = f"{COGNITO_ISSUER}/.well-known/jwks.json"

# Cache for the public keys so we don't have to make a network request on every API call.
# Keyed by kid → RSA key dict for O(1) lookup. Populated lazily and refreshed on key miss
# (AWS rotates Cognito signing keys periodically; a miss means a new key was issued).
_jwks_cache: dict[str, dict] = {}


def _fetch_jwks() -> dict[str, dict]:
    """Fetch the JWKS from Cognito and return a kid→key mapping."""
    try:
        with urlopen(JWKS_URL) as response:
            raw = json.loads(response.read().decode("utf-8"))
    except Exception as e:
        raise RuntimeError(f"Failed to fetch public keys from AWS Cognito: {e}")
    return {key["kid"]: key for key in raw.get("keys", [])}


def get_jwks() -> dict[str, dict]:
    """Return the cached kid→key mapping, fetching on first call.

    Returns:
        Dict mapping each key ID (kid) to its RSA public key object.

    Raises:
        RuntimeError: If the JWKS endpoint cannot be reached.
    """
    global _jwks_cache
    if not _jwks_cache:
        _jwks_cache = _fetch_jwks()
    return _jwks_cache


def verify_cognito_token(token: str) -> dict:
    """Verify a JWT signature using AWS Cognito public keys and validate its claims.

    Decodes the token header to locate the signing key, fetches the JWKS if not
    cached, verifies the RSA signature, and confirms the token's ``client_id`` or
    ``aud`` claim matches the configured Cognito app client.

    Args:
        token: Raw JWT string from the ``Authorization: Bearer`` header.

    Returns:
        The decoded token payload as a dict containing Cognito user claims
        (e.g. ``sub``, ``email``, ``cognito:groups``).

    Raises:
        HTTPException(401): If the token header is malformed, the signing key is
            not found, the token has expired, or signature verification fails.
    """
    # 1. Read the unverified header to find out which key AWS used to sign this token
    try:
        unverified_header = jwt.get_unverified_header(token)
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token header. Not a valid JWT.",
        )
    
    # Every key in AWS has a unique Key ID ('kid')
    kid = unverified_header.get("kid")
    if not kid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token header missing 'kid' (Key ID).",
        )
    
    # 2. Find the matching public key — try cache first, re-fetch once on miss
    #    (handles AWS key rotation without requiring a service restart)
    jwks = get_jwks()
    key_data = jwks.get(kid)
    if not key_data:
        # kid not in cache — AWS may have rotated keys; force a re-fetch
        global _jwks_cache
        _jwks_cache = _fetch_jwks()
        key_data = _jwks_cache.get(kid)

    if not key_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Public key not found. Token may be forged or from the wrong User Pool.",
        )

    # 3. Mathematically verify the token signature and claims.
    #    Cognito issues two token types:
    #      - ID tokens:     audience claim is set to the app client ID
    #      - Access tokens: no 'aud' claim; client_id is in the payload instead
    #    We accept both; PyJWT validates 'aud' when present.
    try:
        public_key = RSAAlgorithm.from_jwk(json.dumps(key_data))

        # Attempt decode treating this as an ID token (has 'aud')
        try:
            payload = jwt.decode(
                token,
                public_key,
                algorithms=["RS256"],
                issuer=COGNITO_ISSUER,
                audience=settings.aws_cognito_app_client_id,
            )
        except jwt.InvalidAudienceError:
            # Fall back to access token path — no 'aud', validate 'client_id' manually
            payload = jwt.decode(
                token,
                public_key,
                algorithms=["RS256"],
                issuer=COGNITO_ISSUER,
                options={"verify_aud": False},
            )
            token_client_id = payload.get("client_id")
            if token_client_id != settings.aws_cognito_app_client_id:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token was not issued for the AsheFlow Dispatch App Client.",
                )

        return payload

    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired. Please log in again.",
        )

    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token verification failed.",
        )
import json
from urllib.request import urlopen
import jwt
import redis as _redis_sync
from fastapi import HTTPException, status
from jwt.algorithms import RSAAlgorithm

from app.core.config import settings

COGNITO_ISSUER = f"https://cognito-idp.{settings.aws_region}.amazonaws.com/{settings.aws_cognito_user_pool_id}"
JWKS_URL = f"{COGNITO_ISSUER}/.well-known/jwks.json"

JWKS_REDIS_KEY = "jwks_cache"
JWKS_TTL_SECONDS = 3600  # 1 hour — AWS rotates Cognito keys infrequently; balances freshness vs. Cognito load

# SCALING NOTE: We use the synchronous Redis client here deliberately.
# verify_cognito_token() is a sync function called inside a sync FastAPI dependency
# (get_current_user in deps.py). Introducing async Redis would require making
# get_current_user and verify_cognito_token async, which cascades through every
# dependency in deps.py that calls get_current_user.
#
# Trade-off accepted: a sync Redis GET blocks the event loop for ~1ms (localhost)
# to ~10ms (cross-region). At this project's traffic level that is immeasurable.
#
# IF this system ever scales to high concurrency (hundreds of simultaneous requests),
# migrate to redis.asyncio and make get_current_user + verify_cognito_token async.
# The Redis logic below stays identical — only the client import and await keywords change.
def _get_redis() -> _redis_sync.Redis:
    return _redis_sync.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
    )


def _fetch_jwks() -> dict[str, dict]:
    """Fetch the JWKS from Cognito and return a kid→key mapping."""
    try:
        with urlopen(JWKS_URL) as response:
            raw = json.loads(response.read().decode("utf-8"))
    except Exception as e:
        raise RuntimeError(f"Failed to fetch public keys from AWS Cognito: {e}")
    return {key["kid"]: key for key in raw.get("keys", [])}


def get_jwks() -> dict[str, dict]:
    """Return the cached kid→key mapping from Redis, fetching from Cognito on miss.

    All worker processes share the same Redis instance, so a cache populated by
    worker 1 is immediately visible to workers 2, 3, and 4. The in-process dict
    this replaced was per-replica — each worker fetched independently and held
    stale keys after AWS key rotation until the process restarted.

    Returns:
        Dict mapping each key ID (kid) to its RSA public key dict.

    Raises:
        RuntimeError: If the JWKS endpoint cannot be reached on a cache miss.
    """
    r = _get_redis()
    cached = r.get(JWKS_REDIS_KEY)
    if cached:
        return json.loads(cached)
    jwks = _fetch_jwks()
    r.set(JWKS_REDIS_KEY, json.dumps(jwks), ex=JWKS_TTL_SECONDS)
    return jwks


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

    kid = unverified_header.get("kid")
    if not kid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token header missing 'kid' (Key ID).",
        )

    # 2. Find the matching public key — try Redis cache first, re-fetch once on miss
    #    (handles AWS key rotation without requiring a service restart)
    jwks = get_jwks()
    key_data = jwks.get(kid)
    if not key_data:
        # kid not in cache — AWS may have rotated keys; force a re-fetch and update Redis
        jwks = _fetch_jwks()
        r = _get_redis()
        r.set(JWKS_REDIS_KEY, json.dumps(jwks), ex=JWKS_TTL_SECONDS)
        key_data = jwks.get(kid)

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

        try:
            payload = jwt.decode(
                token,
                public_key,
                algorithms=["RS256"],
                issuer=COGNITO_ISSUER,
                audience=settings.aws_cognito_app_client_id,
            )
        except (jwt.InvalidAudienceError, jwt.MissingRequiredClaimError):
            # Fall back to access token path — no 'aud', validate 'client_id' manually
            payload = jwt.decode(
                token,
                public_key,
                algorithms=["RS256"],
                issuer=COGNITO_ISSUER,
                options={"verify_aud": False},
            )
            # ADR-363 — two client ids are accepted, and only two. The app
            # client for humans, and the bot's machine client if one is
            # configured. An allowlist rather than "any client in this pool":
            # anyone who can create an app client in the pool could otherwise
            # mint tokens the API trusts.
            token_client_id = payload.get("client_id")
            allowed = {settings.aws_cognito_app_client_id}
            if settings.aws_cognito_bot_client_id:
                allowed.add(settings.aws_cognito_bot_client_id)
            if token_client_id not in allowed:
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

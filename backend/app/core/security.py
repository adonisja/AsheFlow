import json
from urllib.request import urlopen
import jwt
from fastapi import HTTPException, status
from jwt.algorithms import RSAAlgorithm

from app.core.config import settings

# I'll construct the Cognito Issuer ULR dynamically using my .ev variables
COGNITO_ISSUER = f"https://cognito-idp.{settings.aws_region}.amazonaws.com/{settings.aws_cognito_user_pool_id}"
JWKS_URL = f"{COGNITO_ISSUER}/.well-known/jwks.json"

# Cache for the public keys so we don't have to make a network request on every API call
_jwks_cache = {}

def get_jwks() -> dict:
    """Fetch and cache the JSON Web Key Set from AWS Cognito.

    Makes a one-time network request to the Cognito JWKS endpoint and stores
    the result in the module-level ``_jwks_cache``. Subsequent calls return the
    cached value without hitting the network.

    Returns:
        A dict containing the ``keys`` array of RSA public key objects.

    Raises:
        RuntimeError: If the JWKS endpoint cannot be reached or returns invalid data.
    """
    global _jwks_cache
    if not _jwks_cache:
        try:
            # We'll fet the jwks once when the first request hits, then store it in memory.
            with urlopen(JWKS_URL) as response:
                _jwks_cache = json.loads(response.read().decode("utf-8"))
        except Exception as e:
            raise RuntimeError(f"Failed to fetch public keys from AWS Cognito: {e}")
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
    
    # 2. Find the matching public key from our cached AWS keys
    jwks = get_jwks()
    rsa_key = {}
    for key in jwks.get("keys", []):
        if key["kid"] == kid:
            rsa_key = {
                "kty": key["kty"], # Key Type (RSA)
                "kid": key["kid"], # Key ID
                "use": key["use"], # Public Key Use (Signature)
                "n": key["n"],     # RSA Modulus (The cryptographic math)
                "e": key["e"],     # RSA Exponent (The cryptographic match)
            }
            break

    if not rsa_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Public key not found. Token may be forged or from the wrong User Pool",
        )
    
    # 3. Mathematically verify the token signature and claims
    try:
        # Convert the JSON Web Key from AWS into a format PyJWT can use
        public_key = RSAAlgorithm.from_jwk(json.dumps(rsa_key))

        # This function will throw an error if the signature is fake or if the token is expired
        payload = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            issuer=COGNITO_ISSUER,
            options={"verify_aud": False}
        )

        # 4. Verify the token belongs to Our App, not some other app in the same pool
        # Access tokens use 'client_id', ID tokens use 'aud' (audience)
        token_client_id = payload.get("client_id") or payload.get("aud")
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
"""The 'coat-check ticket' for a two-factor reset request (ADR-551 D2b).

Step 1 resolves the typed username to the account ONCE and hands back this
token; step 2 sends the token and the emailed code, never a name. Only the
server can read it (Fernet: AES with an HMAC, so it is both unreadable and
tamper-evident), and it carries its own issue time, so it expires without a
store.

It is NOT proof of ownership. Anyone who types a username gets one, the same
as anyone sees the refusal screen. The emailed code is the proof; the token
only remembers which account the code was sent for, so the account cannot be
switched between the steps and nothing identifying travels back.

For a username that does not exist, step 1 returns a DECOY: a real token for a
random account no code was ever sent to. It looks the same and behaves the
same at step 2, so neither step tells a caller which usernames exist.
"""
from __future__ import annotations

import base64
import json
import uuid

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.config import settings

#: Matches the code's life (account_security.CODE_TTL_SECONDS).
TOKEN_TTL_SECONDS = 600
_PURPOSE = "mfa_reset_request"


def _fernet() -> Fernet:
    """A key of its own, derived from INTERNAL_SECRET with HKDF.

    Derived rather than a new secret so no environment needs another
    parameter; the HKDF `info` label separates it from every other use of that
    secret, so a token minted here can never be accepted anywhere else.
    """
    raw = HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
               info=b"asheflow/mfa-reset-request-token/v1").derive(settings.internal_secret.encode())
    return Fernet(base64.urlsafe_b64encode(raw))


def issue(sub: str, username: str) -> str:
    body = json.dumps({"p": _PURPOSE, "sub": sub, "u": username}, separators=(",", ":"))
    return _fernet().encrypt(body.encode()).decode()


def decoy(username: str) -> str:
    """A real-looking token for an account that does not exist."""
    return issue(str(uuid.uuid4()), username)


def read(token: str) -> tuple[str, str] | None:
    """(sub, username), or None if forged, tampered with, expired or not ours."""
    try:
        body = json.loads(_fernet().decrypt(token.encode(), ttl=TOKEN_TTL_SECONDS))
    except (InvalidToken, ValueError, TypeError):
        return None
    if body.get("p") != _PURPOSE or not body.get("sub"):
        return None
    return body["sub"], body.get("u") or ""

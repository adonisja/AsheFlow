"""Login retry policy for the Discord bot (ADR-447).

Separate from main.py so it can be tested WITHOUT importing discord.py, which
is a bot-container dependency and absent from the backend test environment.
That is not a technicality: the CI job that would run these tests has no
`discord` module, so logic left in main.py is logic no test can execute — and
this whole ADR exists because untested startup code looped 13,999 times.

Pure: no I/O, no Discord types, no logging.
"""
from __future__ import annotations

import random

# Tuned in ADR-447 D2. Eight attempts spans roughly 20 minutes of real outage,
# which is longer than any Discord incident we have seen, and is bounded.
RETRY_BASE_SECONDS = 2.0
RETRY_CAP_SECONDS = 300.0
MAX_LOGIN_ATTEMPTS = 8


def backoff_delay(attempt: int, *, rand=random.uniform) -> float:
    """Exponential backoff with FULL jitter, in seconds. `attempt` is 0-based.

    The ceiling is min(BASE * 2**attempt, CAP); the delay is drawn uniformly
    from [0, ceiling].

    FULL jitter, not a +/-10% band around the ceiling. The failure being
    defended against is SYNCHRONISED retries: during a Discord outage every
    client retries on the same schedule and the recovery gets a thundering
    herd. A narrow band keeps that herd together; drawing across the whole
    interval breaks it up. This is the variant AWS's architecture guidance
    recommends for exactly this case.

    A consequence worth stating plainly: an individual delay can be near zero.
    That is correct. The guarantee is on the DISTRIBUTION across clients, not
    on any single wait, and MAX_LOGIN_ATTEMPTS bounds the total regardless.

    `rand` is injectable so a test can pin the draw without patching the
    `random` module globally.
    """
    if attempt < 0:
        raise ValueError("attempt must be >= 0")
    ceiling = min(RETRY_BASE_SECONDS * (2 ** attempt), RETRY_CAP_SECONDS)
    return rand(0, ceiling)


def is_last_attempt(attempt: int) -> bool:
    """True when `attempt` (0-based) is the final one before giving up."""
    return attempt >= MAX_LOGIN_ATTEMPTS - 1

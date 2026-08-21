"""Every confirmation DB write must also write the Redis cache.

WHY THIS EXISTS
GET /dispatch/{date}/confirmations reads Redis and falls back to Postgres ONLY
when Redis is empty:

    if not confirmations:      # empty -> re-seed from DB

`seed_pending` fills that hash at publish, so for a published date it is never
empty. A DB write that skips the cache is therefore invisible to the UI until
the TTL expires — the finalize gate (ADR-205) and the emergency pool (ADR-267)
would both read a status that is no longer true.

This was investigated as a suspected live bug and turned out to be clean: all
write sites already pair. The test exists so it STAYS clean — the failure mode
is silent, and nothing else would catch a new unpaired write.

It is a source-level structural check rather than a behavioural one because the
hazard is "somebody adds a write site and forgets", which no runtime test over
existing endpoints can observe.
"""
import inspect
import re

from app.routers import dispatch as dispatch_router

# Every way the cache is legitimately written. `_fire_redis_*` are the
# sync-context wrappers (the endpoints are `def`, not `async def`);
# `seed_pending` writes the whole hash at publish; `clear_confirmations` wipes
# it. Missing one of these from this tuple is what made the first audit report
# a false positive.
_CACHE_CALLS = (
    "set_confirmation(",
    "_fire_redis_set(",
    "_fire_redis_cancel(",
    "seed_pending(",
    "clear_confirmations(",
)

# Assignment only. An earlier version used `\.status\s*=\s*"..."`, which also
# matched SQLAlchemy's `== "confirmed"` in a filter and reported
# finalize_dispatch — a pure READER — as an unpaired writer. `(?<!=)=(?!=)` is
# what separates "sets the column" from "compares it".
_DB_WRITE = re.compile(
    r"db\.add\(DispatchConfirmation\(|"
    r"conf_row\.status\s*(?<!=)=(?!=)\s*|"
    r"\w+\.status\s*(?<!=)=(?!=)\s*[\"'](pending|confirmed|declined|cancelled)[\"']"
)


def _strip_comments(src: str) -> str:
    """Drop `#` comments before matching.

    finalize_dispatch documents its own query as
    `DispatchConfirmation.status='confirmed'`, which is indistinguishable from
    an assignment once you are matching text. Prose describing a write is not a
    write — a source-level check has to read only code.
    """
    return "\n".join(line.split("#", 1)[0] for line in src.split("\n"))


def _functions_with_confirmation_writes():
    """{name: code} for every top-level function that writes a confirmation."""
    out = {}
    for name, obj in vars(dispatch_router).items():
        if not callable(obj) or not hasattr(obj, "__code__"):
            continue
        try:
            src = inspect.getsource(obj)
        except (OSError, TypeError):
            continue
        code = _strip_comments(src)
        if _DB_WRITE.search(code):
            out[name] = code
    return out


def test_the_detector_finds_the_known_write_sites():
    """Guard the guard: if the regex stops matching, the real test below passes
    vacuously and proves nothing."""
    found = _functions_with_confirmation_writes()
    assert "record_confirmation" in found, (
        "the DB-write detector matched nothing in record_confirmation — the "
        "pattern has drifted and the pairing test is now vacuous"
    )
    assert len(found) >= 4, f"expected several write sites, found {sorted(found)}"


def test_every_confirmation_write_also_writes_the_cache():
    unpaired = [
        name for name, src in _functions_with_confirmation_writes().items()
        if not any(call in src for call in _CACHE_CALLS)
    ]
    assert not unpaired, (
        "these functions write DispatchConfirmation without writing the Redis "
        f"cache: {unpaired}. The UI reads Redis first and only falls back to "
        "the DB when the hash is EMPTY, so the write will be invisible until "
        "the TTL expires. Add a set_confirmation / _fire_redis_set call."
    )


def test_finalize_reads_the_database_not_the_cache():
    """ADR-205's gate must not trust the cache.

    It is the safety boundary that stops a near-empty crew being posted to
    Discord. Reading a cache that can lag would let a stale 'confirmed' through,
    which is the one place that must never happen.
    """
    src = inspect.getsource(dispatch_router.finalize_dispatch)
    assert "db.query(DispatchConfirmation" in src
    assert "get_all_confirmations" not in src

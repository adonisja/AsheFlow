"""ADR-493 D1 — the erasure registry guards itself (the ADR-464 pattern).

Walks the WORLD (every mapped column), not the list: a registry-walking test
passes forever while the registry goes stale. A new column whose name looks
like an address, a package id or a note must be registered in
`pi_erasure.REGISTRY` with an erase action, or exempted in `EXEMPT` with a
written reason — otherwise an Amazon erasure request would silently miss it.
"""
import re

import app.models  # noqa: F401 — registers every mapper
from app.models.base import Base
from app.services import pi_erasure

# `location` added by ADR-512: incidents.incident_location stored a customer
# address under a name this scan could not see, so erasure never reached it.
_PATTERN = re.compile(r"address|tba|location|(^|_)notes?$")


def _candidates() -> dict[tuple[str, str], str]:
    out = {}
    for m in Base.registry.mappers:
        for c in m.local_table.columns:
            if _PATTERN.search(c.name):
                out[(m.local_table.name, c.name)] = m.class_.__name__
    return out


def _registered() -> set[tuple[str, str]]:
    return {(pi_erasure.resolve(t).__tablename__, t.column) for t in pi_erasure.REGISTRY}


def test_every_pi_column_is_registered_or_exempt():
    missing = sorted(set(_candidates()) - _registered() - set(pi_erasure.EXEMPT))
    assert not missing, (
        "Columns that look like an address, a package id or a note, but which an "
        "erasure would not touch:\n  "
        + "\n  ".join(f"{t}.{c}  ({_candidates()[(t, c)]})" for t, c in missing)
        + "\nRegister each in app/services/pi_erasure.py REGISTRY with how to erase it, "
          "or add it to EXEMPT with the reason it is not Personal Information."
    )


def test_exempt_entries_still_exist():
    """A stale exemption for a dropped column would quietly cover a future
    column of the same name."""
    stale = sorted(set(pi_erasure.EXEMPT) - set(_candidates()))
    assert not stale, f"EXEMPT names columns that no longer exist: {stale}"


def test_registry_entries_are_not_also_exempt():
    both = sorted(_registered() & set(pi_erasure.EXEMPT))
    assert not both, f"Both registered and exempt (REGISTRY wins; the exemption misleads): {both}"


def test_every_registered_column_exists_on_its_model():
    """Dimension 3: `Model.column` reads like working code whether or not the
    attribute exists, and fails only when the erasure runs."""
    for t in pi_erasure.REGISTRY:
        model = pi_erasure.resolve(t)
        assert t.column in model.__table__.columns, f"{t.model}.{t.column} does not exist"
        if t.tenant:
            assert "company_id" in model.__table__.columns, f"{t.model} has no company_id to scope by"


def test_the_scan_finds_the_known_columns():
    """If the walk ever finds nothing, every test above passes vacuously."""
    assert ("delivery_stops", "normalised_address") in _candidates()
    assert ("routes", "tba_numbers") in _candidates()

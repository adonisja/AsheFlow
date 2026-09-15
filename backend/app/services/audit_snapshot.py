"""Build an audit snapshot from columns that actually exist (ADR-395).

WHY THIS EXISTS
`delete_employee_relationships` built its `before` payload from
`relationship.related_employee_id`. The model's column is `target_employee_id`.
Every DELETE raised AttributeError and returned 500, so favourites and blocks
could be created and never removed (ADR-384).

The bad reference arrived with ADR-132's GDPR Art. 17 compliance sweep. **The
audit trail intended to make deletions accountable is what made them
impossible.**

WHY IT SURVIVED FOR MONTHS
An audit snapshot runs on the *unhappy* path -- the delete, the rejection, the
override -- which is exactly where nobody looks until a user complains. And the
endpoint WAS tested: ADR-361 and ADR-353 both cover it, and both read the
router's source text and assert on substrings, which cannot see an AttributeError.

WHAT THIS CHANGES
`snapshot(obj, "col", ...)` validates the names against the SQLAlchemy mapper and
raises `UnknownAuditColumn` if one does not exist. A stale name then fails when
the module is exercised at all -- including by any test that touches the endpoint
-- rather than only when a user presses delete.

It deliberately does NOT accept `**kwargs` of literal values. Those are already
safe: a typo in a literal key is a wrong label, not a crash, and mixing the two
would blur which half is checked.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import inspect as sa_inspect


class UnknownAuditColumn(AttributeError):
    """A snapshot named a column the model does not have.

    Subclasses AttributeError so existing `except AttributeError` handlers keep
    working, but the message names the model and lists what IS available --
    ADR-384's failure took a database query to diagnose, and the answer was
    always sitting in the mapper.
    """


def _column_names(obj: Any) -> set[str]:
    try:
        return {c.key for c in sa_inspect(type(obj)).mapper.column_attrs}
    except Exception:  # not a mapped object
        return set()


def snapshot(obj: Any, *columns: str, **extra: Any) -> dict[str, Any]:
    """Read `columns` off `obj`, validated against the model's real columns.

    UUIDs and datetimes are stringified because the payload lands in JSONB and
    neither is JSON-serialisable. That conversion is why the original code was
    full of `str(...)` calls, and doing it here removes the reason to hand-write
    the dict at all.

    `extra` is for values that are not columns -- a computed count, the actor's
    identity -- and is merged unvalidated, because there is nothing to validate
    it against.

        snapshot(rel, "employee_id", "target_employee_id", "relationship_type")

    Raises:
        UnknownAuditColumn: if a name is not a column on the model. Raised at
            call time, which for an audited write means the first test that
            exercises the path rather than the first user who hits it.
    """
    known = _column_names(obj)
    if known:
        unknown = [c for c in columns if c not in known]
        if unknown:
            raise UnknownAuditColumn(
                f"{type(obj).__name__} has no column(s) {', '.join(sorted(unknown))}. "
                f"Available: {', '.join(sorted(known))}"
            )

    out: dict[str, Any] = {}
    for c in columns:
        v = getattr(obj, c)
        # JSONB cannot hold a UUID or a datetime; isoformat/str keeps the audit
        # row readable rather than storing a repr.
        if v is None or isinstance(v, (str, int, float, bool)):
            out[c] = v
        elif hasattr(v, "isoformat"):
            out[c] = v.isoformat()
        else:
            out[c] = str(v)
    out.update(extra)
    return out

"""Regression: write_audit must accept `detail=` as an alias for `after=`.

25 call sites (walker_routes, rts, roll_call, employees, building_profiles)
pass the post-change payload as detail=. write_audit only declared `after`, so
every one raised TypeError and 500-ed its endpoint — commit-sort surfaced this
in the browser as a misleading CORS error (2026-07-04). This locks the alias.
"""
import uuid
from unittest.mock import MagicMock

from app.services.audit import write_audit


def _capture():
    db = MagicMock()
    added = []
    db.add.side_effect = added.append
    return db, added


def test_detail_maps_to_after_snapshot():
    db, added = _capture()
    write_audit(
        db=db, action_type="route_sort.committed", target_table="routes",
        target_id=str(uuid.uuid4()), actor_id=str(uuid.uuid4()),
        company_id=str(uuid.uuid4()), detail={"routes_created": 3},
    )
    assert added[0].after_snapshot == {"routes_created": 3}


def test_after_still_supported_and_wins_over_detail():
    db, added = _capture()
    write_audit(
        db=db, action_type="x", target_table="t", target_id=str(uuid.uuid4()),
        after={"a": 1},
    )
    assert added[0].after_snapshot == {"a": 1}

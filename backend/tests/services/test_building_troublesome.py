"""Troublesome decaying-score service (ADR-218).

Public service (scoring helper, no proprietary imports). Covers weighted bump,
stub-create on cold building, nightly decay + floor, and resolution dampening.
"""
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.building_troublesome import (
    bump_for_rts_type, record_rts_incident, apply_resolution, decay_all,
    DECAY_PER_NIGHT, DECAY_FLOOR, RESOLUTION_DAMPEN, TROUBLESOME_THRESHOLD,
)

_CID = uuid.uuid4()


def test_bump_weights_by_type():
    assert bump_for_rts_type("no_access") == 0.5          # reattemptable → light
    assert bump_for_rts_type("business_closed") == 0.5
    assert bump_for_rts_type("customer_refused") == 1.0   # hard → full
    assert bump_for_rts_type("package_damaged") == 1.0


def _db_with_existing(bp):
    db = MagicMock()
    q = MagicMock(); f = MagicMock(); f.filter.return_value = f
    f.first.return_value = bp
    q.filter.return_value = f
    db.query.return_value = q
    return db


def test_bump_existing_building():
    bp = SimpleNamespace(troublesome_score=1.0, troublesome_last_incident_at=None)
    db = _db_with_existing(bp)
    record_rts_incident(db, _CID, "340 W 36 St", "W_36_St_300", "customer_refused")
    assert bp.troublesome_score == 2.0            # 1.0 + hard 1.0
    assert bp.troublesome_last_incident_at is not None


def test_cold_building_creates_stub_and_bumps():
    added = {}
    db = MagicMock()
    q = MagicMock(); f = MagicMock(); f.filter.return_value = f
    f.first.return_value = None                    # no existing profile
    q.filter.return_value = f
    db.query.return_value = q
    db.add.side_effect = lambda o: added.setdefault("bp", o)
    record_rts_incident(db, _CID, "999 Nowhere St", "W_99_St_900", "no_access")
    bp = added["bp"]
    assert bp.company_id == _CID
    assert bp.normalised_address == "999 Nowhere St"
    assert bp.building_type_status == "pending"
    assert bp.troublesome_score == 0.5             # reattemptable bump on fresh stub


def test_no_address_is_noop():
    db = MagicMock()
    record_rts_incident(db, _CID, None, None, "customer_refused")
    db.query.assert_not_called()
    db.add.assert_not_called()


def test_resolution_dampens_not_zero():
    bp = SimpleNamespace(troublesome_score=4.0, troublesome_resolved_at=None)
    apply_resolution(MagicMock(), bp)
    assert bp.troublesome_score == 4.0 * RESOLUTION_DAMPEN   # halved, not zeroed
    assert bp.troublesome_resolved_at is not None


def test_decay_and_floor():
    hi = SimpleNamespace(troublesome_score=10.0)
    lo = SimpleNamespace(troublesome_score=0.05)   # below floor → snaps to 0
    db = MagicMock()
    q = MagicMock(); f = MagicMock(); f.filter.return_value = f
    f.all.return_value = [hi, lo]
    q.filter.return_value = f
    db.query.return_value = q
    n = decay_all(db)
    assert n == 2
    assert abs(hi.troublesome_score - 10.0 * DECAY_PER_NIGHT) < 1e-9
    assert lo.troublesome_score == 0.0             # floored


def test_threshold_sane():
    # one hard incident (1.0) stays under threshold; ~3 needed to flag.
    assert TROUBLESOME_THRESHOLD > 1.0

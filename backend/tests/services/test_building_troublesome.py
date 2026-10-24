"""Troublesome decaying-score service (ADR-218 scoring; ADR-584 D6 storage).

Real rows in `troublesome_doors`: weighted bump, a door created on first RTS
(and no stub BuildingProfile), the borough a pre-ADR-584 score is claimed by,
nightly decay + floor, resolution dampening, and the two readers.
"""
import uuid
from types import SimpleNamespace

import pytest

from app.models.troublesome_door import TroublesomeDoor
from app.services.building_troublesome import (
    DECAY_FLOOR, DECAY_PER_NIGHT, RESOLUTION_DAMPEN, TROUBLESOME_THRESHOLD,
    apply_resolution, bump_for_rts_type, decay_all, record_rts_incident,
    scores_by_address, troublesome_doors,
)
from tests.conftest import SEED_COMPANY_ID, sqlite_mirror_with_defaults

OTHER = uuid.uuid4()


@pytest.fixture(autouse=True)
def _table(db):
    sqlite_mirror_with_defaults(TroublesomeDoor.__table__).create(db.get_bind(), checkfirst=True)


def _doors(db):
    db.expire_all()
    return db.query(TroublesomeDoor).order_by(TroublesomeDoor.address).all()


def test_bump_weights_by_type():
    assert bump_for_rts_type("no_access") == 0.5          # reattemptable → light
    assert bump_for_rts_type("business_closed") == 0.5
    assert bump_for_rts_type("customer_refused") == 1.0   # hard → full
    assert bump_for_rts_type("package_damaged") == 1.0


def test_the_first_rts_creates_the_door_and_no_profile(db):
    from app.models.building_profile import BuildingProfile
    sqlite_mirror_with_defaults(BuildingProfile.__table__).create(db.get_bind(), checkfirst=True)
    record_rts_incident(db, SEED_COMPANY_ID, "340 W 36 ST", "W_36_St_300", "no_access", borough="1")
    db.commit()
    (d,) = _doors(db)
    assert (d.borough, d.address, d.score) == ("1", "340 W 36 ST", 0.5) and d.last_incident_at
    assert db.query(BuildingProfile).count() == 0, "ADR-584 D6: no stub BuildingProfile"


def test_a_second_rts_bumps_the_same_door(db):
    for t in ("no_access", "customer_refused"):
        record_rts_incident(db, SEED_COMPANY_ID, "340 W 36 ST", None, t, borough="1")
    db.commit()
    (d,) = _doors(db)
    assert d.score == 1.5


def test_the_same_address_in_two_boroughs_is_two_doors(db):
    record_rts_incident(db, SEED_COMPANY_ID, "100 BROADWAY", None, "customer_refused", borough="1")
    record_rts_incident(db, SEED_COMPANY_ID, "100 BROADWAY", None, "customer_refused", borough="3")
    db.commit()
    assert {(d.borough, d.score) for d in _doors(db)} == {("1", 1.0), ("3", 1.0)}


def test_a_copied_score_without_a_borough_is_claimed_by_the_first_door_with_one(db):
    """The migration copies pre-ADR-584 scores with borough NULL; the next RTS
    with a borough adopts it instead of starting a second row."""
    db.add(TroublesomeDoor(company_id=SEED_COMPANY_ID, borough=None, address="340 W 36 ST", score=3.0))
    db.commit()
    record_rts_incident(db, SEED_COMPANY_ID, "340 W 36 ST", None, "customer_refused", borough="1")
    db.commit()
    (d,) = _doors(db)
    assert (d.borough, d.score) == ("1", 4.0)


def test_no_address_is_a_noop(db):
    record_rts_incident(db, SEED_COMPANY_ID, None, None, "customer_refused", borough="1")
    db.commit()
    assert _doors(db) == []


def test_resolution_dampens_the_companys_doors_not_to_zero(db):
    db.add_all([TroublesomeDoor(company_id=SEED_COMPANY_ID, borough="1", address="340 W 36 ST", score=4.0),
                TroublesomeDoor(company_id=OTHER, borough="1", address="340 W 36 ST", score=4.0)])
    db.commit()
    apply_resolution(db, SimpleNamespace(company_id=SEED_COMPANY_ID, normalised_address="340 W 36 ST"))
    db.commit()
    mine, theirs = sorted(_doors(db), key=lambda d: d.company_id != SEED_COMPANY_ID)
    assert mine.score == 4.0 * RESOLUTION_DAMPEN and mine.resolved_at is not None
    assert theirs.score == 4.0, "Dimension 1: another company's door is untouched"


def test_decay_and_floor(db, monkeypatch):
    monkeypatch.setattr("app.services.company_config.full_mode_company_ids", lambda db: {SEED_COMPANY_ID})
    db.add_all([TroublesomeDoor(company_id=SEED_COMPANY_ID, borough="1", address="A", score=10.0),
                TroublesomeDoor(company_id=SEED_COMPANY_ID, borough="1", address="B", score=0.05)])
    db.commit()
    assert decay_all(db) == 2
    db.commit()
    a, b = _doors(db)
    assert abs(a.score - 10.0 * DECAY_PER_NIGHT) < 1e-9 and b.score == 0.0


def test_decay_skips_workforce_companies(db, monkeypatch):
    """ADR-293: with no full-mode tenant nothing is decayed. In workforce mode no
    delivery evidence refreshes the score, so decaying would erase it unopposed."""
    monkeypatch.setattr("app.services.company_config.full_mode_company_ids", lambda db: set())
    db.add(TroublesomeDoor(company_id=SEED_COMPANY_ID, borough="1", address="A", score=10.0))
    db.commit()
    assert decay_all(db) == 0
    assert _doors(db)[0].score == 10.0


def test_the_readers(db):
    db.add_all([TroublesomeDoor(company_id=SEED_COMPANY_ID, borough="1", address="A", score=3.0),
                TroublesomeDoor(company_id=SEED_COMPANY_ID, borough="3", address="A", score=5.0),
                TroublesomeDoor(company_id=SEED_COMPANY_ID, borough="1", address="B", score=1.0),
                TroublesomeDoor(company_id=OTHER, borough="1", address="C", score=9.0)])
    db.commit()
    assert [d.address for d in troublesome_doors(db, SEED_COMPANY_ID)] == ["A", "A"]
    assert scores_by_address(db, SEED_COMPANY_ID) == {"A": 5.0, "B": 1.0}


def test_threshold_sane():
    # one hard incident (1.0) stays under threshold; ~3 needed to flag.
    assert TROUBLESOME_THRESHOLD > 1.0
    assert DECAY_FLOOR < 1.0

"""ADR-503 — an erasure asks the database for candidates, and reads them in pages.

ADR-493's first build loaded every row of every registered table into memory
and matched in Python. On staging (1.19M delivery stops for one tenant) the
preview was killed by the kernel at 2.9 GB and the browser saw "Couldn't reach
the server". These tests pin the two properties that fix it:

1. The SQL pre-filter is a NECESSARY condition, so it can never lose a match.
2. Rows that cannot match are never loaded, and matching rows past the first
   page are still found.
"""
import uuid

import pytest
from sqlalchemy import event

from app.models.delivery_stop import DeliveryStop
from app.services import pi_erasure
from app.services.door_key import door_key
from tests.conftest import SEED_COMPANY_ID
# Re-use ADR-493's fixtures: the ARRAY shim and the table set (both autouse).
from tests.services.test_adr493_erasure import _route, _tables, array_as_json  # noqa: F401

# Spellings that fold to the same door as "433 West 32nd Street".
SPELLINGS = [
    "433 W 32 ST", "433 w. 32nd st", "433 WEST 32ND STREET", "433 West 32nd St, Apt 4",
    "John Smith 433 W 32nd Street", "433,W,32,ST",
]


@pytest.mark.parametrize("spelling", SPELLINGS)
def test_every_matching_spelling_contains_every_candidate_token(spelling):
    req = pi_erasure.Request(kind="address", value="433 West 32nd Street", company_id=None)
    assert door_key(spelling) == req.key, "vector entry must really be the same door"
    for tok in pi_erasure.candidate_tokens(req):
        assert tok.lower() in spelling.lower(), (tok, spelling)


def test_folded_words_are_not_required():
    """'W' may be stored as 'West' and 'ST' as 'Street' or 'St'; requiring the
    folded form would drop real matches."""
    req = pi_erasure.Request(kind="address", value="433 W 32 ST", company_id=None)
    assert pi_erasure.candidate_tokens(req) == ["433", "32"]


def test_a_tba_candidate_survives_case_and_spaces():
    req = pi_erasure.Request(kind="tba", value=" tba123456789000 ", company_id=None)
    (tok,) = pi_erasure.candidate_tokens(req)
    assert tok.lower() in "TBA123456789000".lower()


def _stop(db, address, route):
    s = DeliveryStop(id=uuid.uuid4(), company_id=SEED_COMPANY_ID, route_id=route.id,
                     truck_assignment_id=uuid.uuid4(), block_key="b", stop_sequence=1,
                     normalised_address=address, tba_numbers=[])
    db.add(s)
    return s


class TestOnlyCandidatesAreLoaded:
    def test_rows_that_cannot_match_are_never_loaded(self, db):
        route = _route(db, addrs=("999 OTHER ST",), tbas=())
        for i in range(200):
            _stop(db, f"{1000 + i} BROADWAY", route)
        hit = _stop(db, "433 w. 32nd st", route)
        db.commit()
        db.expunge_all()

        loaded = []
        listener = lambda target, ctx: loaded.append(target.normalised_address)
        event.listen(DeliveryStop, "load", listener)
        try:
            res = pi_erasure.erase(db, pi_erasure.Request(
                kind="address", value="433 West 32nd Street", company_id=SEED_COMPANY_ID),
                dry_run=True)
        finally:
            event.remove(DeliveryStop, "load", listener)
        assert res.counts.get("delivery_stops.normalised_address") == 1
        assert loaded == ["433 w. 32nd st"], f"loaded {len(loaded)} stops, expected only the match"
        db.rollback()

    def test_matches_past_the_first_page_are_found(self, db, monkeypatch):
        monkeypatch.setattr(pi_erasure, "PAGE_SIZE", 3)
        route = _route(db, addrs=("999 OTHER ST",), tbas=())
        for i in range(8):
            _stop(db, "433 W 32 ST" if i % 2 else "433 WEST 32ND STREET", route)
        db.commit()
        res = pi_erasure.erase(db, pi_erasure.Request(
            kind="address", value="433 W 32 St", company_id=SEED_COMPANY_ID), dry_run=False)
        db.commit()
        assert res.counts["delivery_stops.normalised_address"] == 8
        left = db.query(DeliveryStop).filter(DeliveryStop.normalised_address.isnot(None)).count()
        assert left == 0

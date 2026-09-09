"""ADR-400 A2/A5d — OV ids mint atomically and reset daily.

Behavioural, not source-text: these build a real table and exercise the mint
against it, because the properties that matter (a race recovers, the sequence
resets at midnight, two trucks do not collide) are runtime facts.
"""
import datetime as dt
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.workforce_ov import WorkforceOV, OV_SIZES, OV_SOURCES
from app.services.workforce_ov_mint import mint, is_ov_id


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    WorkforceOV.__table__.create(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture()
def ids():
    return uuid.uuid4(), uuid.uuid4(), uuid.uuid4()   # company, truck A, truck B


class TestMinting:
    def test_ids_are_sequential_and_zero_padded(self, db, ids):
        cid, ta, _ = ids
        today = dt.date.today()
        got = [
            mint(db, company_id=cid, truck_id=ta, entry_date=today, source="sheet").ov_id
            for _ in range(3)
        ]
        assert got == ["OV0001", "OV0002", "OV0003"]

    def test_second_truck_continues_the_company_sequence(self, db, ids):
        """Scoped to (company, date), NOT (company, truck).

        Per-truck numbering would give two trucks their own OV0001, and a
        captain reading "OV1" off a hand-written label would have no way to tell
        them apart — while the packages themselves get handed between trucks.
        """
        cid, ta, tb = ids
        today = dt.date.today()
        mint(db, company_id=cid, truck_id=ta, entry_date=today, source="sheet")
        db.commit()
        second = mint(db, company_id=cid, truck_id=tb, entry_date=today, source="milk_run")
        assert second.ov_id == "OV0002", "the sequence restarted per truck"

    def test_sequence_resets_the_next_day(self, db, ids):
        """The whole reason a Postgres sequence was rejected: "OV12" must mean
        today's twelfth, not the twelfth since the feature shipped."""
        cid, ta, _ = ids
        today = dt.date.today()
        for _ in range(3):
            mint(db, company_id=cid, truck_id=ta, entry_date=today, source="sheet")
        db.commit()
        tomorrow = mint(db, company_id=cid, truck_id=ta,
                        entry_date=today + dt.timedelta(days=1), source="sheet")
        assert tomorrow.ov_id == "OV0001"

    def test_a_lost_race_retries_past_the_stolen_id(self, db, ids, monkeypatch):
        """A5d. Two captains compute the same max()+1; the loser must recover.

        The race has to be simulated INSIDE mint, not before it. An id that is
        already committed when mint starts is simply read by `_next_number` and
        stepped over — the retry never runs, so a test written that way passes
        with the whole except-branch deleted (confirmed by mutation, 2026-09-09).

        So: let the first attempt compute its number, then steal that exact id
        underneath it. The INSERT then fails the way a lost race actually fails.
        """
        import app.services.workforce_ov_mint as M
        cid, ta, tb = ids
        today = dt.date.today()

        real_next = M._next_number
        calls = {"n": 0}

        def racing_next(session, company_id, entry_date):
            n = real_next(session, company_id, entry_date)
            calls["n"] += 1
            if calls["n"] == 1:
                # The other captain commits OUR id between our read and our write.
                session.add(WorkforceOV(
                    company_id=company_id, truck_id=tb, entry_date=entry_date,
                    ov_id=f"OV{n:04d}", source="captain"))
                session.flush()
            return n

        monkeypatch.setattr(M, "_next_number", racing_next)
        recovered = M.mint(db, company_id=cid, truck_id=ta, entry_date=today,
                           source="sheet")

        assert calls["n"] >= 2, "mint did not retry after losing the race"
        assert recovered.ov_id == "OV0002", (
            "mint did not step past the id the other captain took"
        )

    def test_a_failed_mint_does_not_discard_the_callers_work(self, db, ids, monkeypatch):
        """The retry uses a SAVEPOINT, not a rollback.

        Seeding a sheet mints many OVs in one transaction. If losing one race
        rolled the session back, a single collision would discard every OV
        created before it.
        """
        import app.services.workforce_ov_mint as M
        cid, ta, tb = ids
        today = dt.date.today()

        first = M.mint(db, company_id=cid, truck_id=ta, entry_date=today, source="sheet")

        real_next = M._next_number
        calls = {"n": 0}

        def racing_next(session, company_id, entry_date):
            n = real_next(session, company_id, entry_date)
            calls["n"] += 1
            if calls["n"] == 1:
                session.add(WorkforceOV(
                    company_id=company_id, truck_id=tb, entry_date=entry_date,
                    ov_id=f"OV{n:04d}", source="captain"))
                session.flush()
            return n

        monkeypatch.setattr(M, "_next_number", racing_next)
        M.mint(db, company_id=cid, truck_id=ta, entry_date=today, source="sheet")
        db.commit()

        # Without begin_nested the failed INSERT poisons the transaction and
        # takes `first` down with it.
        assert db.query(WorkforceOV).filter_by(id=first.id).one().ov_id == "OV0001", (
            "the first OV was lost when a later mint hit the constraint"
        )


class TestIdDiscrimination:
    @pytest.mark.parametrize("value,expected", [
        ("OV0012", True), ("OV1", True),
        ("6800", False),        # a real bag id: bare digits after parse_bag_label
        ("OVX", False), ("", False), (None, False),
        ("Green 6800", False),
    ])
    def test_is_ov_id(self, value, expected):
        """Bag ids are bare digits once the colour word is stripped, so the two
        namespaces cannot overlap and this test is total."""
        assert is_ov_id(value) is expected


class TestVocabulary:
    def test_source_distinguishes_a_milk_run_from_a_wrong_sheet(self):
        """A5b. A mid-day OV is an ARRIVAL, not evidence the sheet was wrong.

        Collapsing these to two values makes every normal milk-run look like a
        data-quality problem, and loses "how much extra freight came in today".
        """
        assert set(OV_SOURCES) == {"sheet", "milk_run", "captain"}

    def test_sizes_match_the_capacity_tiers(self):
        """These feed `OV_{size}` into route_sort's existing OV_HALF_SLOTS path.
        A size here with no tier there would cost nothing and silently
        understate the route."""
        from app.schemas.walker_routes import OV_HALF_SLOTS
        assert set(OV_SIZES) == set(OV_HALF_SLOTS), (
            "OV_SIZES drifted from OV_HALF_SLOTS — an OV whose size has no tier "
            "contributes zero half-slots and the route is under-costed"
        )

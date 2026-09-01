"""ADR-291 — the workforce adapter feeds the UNCHANGED route sort.

The load-bearing test is `test_run_sort_accepts_adapter_output`: if the adapter's
PackageInput records do not satisfy the real `run_sort`, the whole premise of D5
(adapter, not a fork) is wrong and the alternative is duplicating 1,700 lines of
the deepest IP in the product.

Everything else guards a specific decision:
  D1  both modes route on block_key — the adapter emits block_key, never segment
  D2  1..N addresses per tote resolve by the EXISTING majority vote
  D4  a tote whose addresses disagree is surfaced, not silently resolved
  D5  synthetic ids are deterministic and unmistakable for real TBAs
  dim 5  a tote nobody addressed is REPORTED, never dropped
"""
import uuid
from datetime import date

import pytest

from app.services.workforce_sort_adapter import (
    AdapterResult, build_packages, is_synthetic_tba, synthetic_tba,
)


# ── synthetic identifiers (D5) ────────────────────────────────────────────────

def test_synthetic_tba_is_deterministic():
    """A re-sort of the same entries must produce the same ids, or the sort is
    not reproducible and telemetry cannot be compared across runs."""
    assert synthetic_tba("5270", 1) == synthetic_tba("5270", 1)
    assert synthetic_tba("5270", 1) != synthetic_tba("5270", 2)


def test_synthetic_tba_cannot_be_mistaken_for_a_real_one():
    """A real Amazon TBA is TBA + 12-15 digits (label_ingestor._TBA_RE). Ours is
    prefixed so it can never be filed in a scorecard appeal as if Amazon issued
    it, nor matched against a future manifest."""
    minted = synthetic_tba("5270", 1)
    assert minted.startswith("WF-")
    assert not minted.upper().startswith("TBA")
    assert is_synthetic_tba(minted)
    assert not is_synthetic_tba("TBA303012345678")
    assert not is_synthetic_tba(None)


def test_synthetic_ids_are_unique_within_a_tote():
    """route_sort's null-block sentinel is f"__unknown_{tba}". Duplicate ids
    would collapse two unaddressable entries into one block."""
    ids = {synthetic_tba("5270", i) for i in range(1, 6)}
    assert len(ids) == 5


# ── adapter behaviour, against a real session ─────────────────────────────────

def _entry(db, company_id, truck_id, bag_id, block_key, seq=0,
           address="123 W 36 St", lat=40.75, lng=-73.99):
    from app.models.tote_address import ToteAddress
    row = ToteAddress(
        id=uuid.uuid4(), company_id=company_id, truck_id=truck_id,
        entry_date=date.today(), bag_id=bag_id, raw_address=address,
        normalised_address=address, block_key=block_key,
        lat=lat, lng=lng, entry_sequence=seq,
    )
    db.add(row)
    db.commit()
    return row


@pytest.fixture
def wf_db():
    """Own engine: ToteAddress/BTR tables are not in the shared conftest set."""
    from sqlalchemy import create_engine, MetaData
    from sqlalchemy.orm import sessionmaker
    from app.models.company import Company, CompanyConfig
    from app.models.employee import Employee
    from app.models.truck import Truck
    from app.models.tote_address import ToteAddress
    from app.models.btr_sheet import BTRSheet, BTRRoute, BTRBag, BTROVZone

    meta = MetaData()
    for t in (Company.__table__, CompanyConfig.__table__, Employee.__table__,
              Truck.__table__, ToteAddress.__table__, BTRSheet.__table__,
              BTRRoute.__table__, BTRBag.__table__, BTROVZone.__table__):
        t.to_metadata(meta)
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    meta.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


def test_one_address_makes_one_package(wf_db):
    cid, tid = uuid.uuid4(), uuid.uuid4()
    _entry(wf_db, cid, tid, "5270", "W_36_St_100")

    res = build_packages(wf_db, cid, tid, date.today())
    assert len(res.packages) == 1
    p = res.packages[0]
    assert p.bag_id == "5270"
    assert p.block_key == "W_36_St_100"
    assert p.tba_number == "WF-5270-1"


def test_several_addresses_on_one_tote_all_become_packages(wf_db):
    """D2: they vote via _Tote.dominant_block_key exactly as package addresses
    do. One address is a degenerate unanimous vote."""
    cid, tid = uuid.uuid4(), uuid.uuid4()
    for i, addr in enumerate(["1 A St", "2 A St", "3 A St"], start=1):
        _entry(wf_db, cid, tid, "5270", "W_36_St_100", seq=i, address=addr)

    res = build_packages(wf_db, cid, tid, date.today())
    assert len(res.packages) == 3
    assert {p.bag_id for p in res.packages} == {"5270"}
    assert len({p.tba_number for p in res.packages}) == 3


def test_disagreeing_addresses_are_surfaced_not_silently_resolved(wf_db):
    """D4: a split tote is real information — loose bagging or a typo. The sort
    still proceeds on the majority, but the captain is told."""
    cid, tid = uuid.uuid4(), uuid.uuid4()
    _entry(wf_db, cid, tid, "5270", "W_36_St_100", seq=1, address="1 A St")
    _entry(wf_db, cid, tid, "5270", "W_36_St_100", seq=2, address="2 A St")
    _entry(wf_db, cid, tid, "5270", "E_50_St_900", seq=3, address="900 E 50 St")

    res = build_packages(wf_db, cid, tid, date.today())
    assert len(res.disagreements) == 1
    d = res.disagreements[0]
    assert d.bag_id == "5270"
    assert set(d.block_keys) == {"W_36_St_100", "E_50_St_900"}
    assert d.winning_block_key == "W_36_St_100"      # 2 votes beats 1
    # and it still sorts — all three entries reach run_sort
    assert len(res.packages) == 3


def test_agreeing_addresses_raise_no_disagreement(wf_db):
    cid, tid = uuid.uuid4(), uuid.uuid4()
    _entry(wf_db, cid, tid, "5270", "W_36_St_100", seq=1, address="1 A St")
    _entry(wf_db, cid, tid, "5270", "W_36_St_100", seq=2, address="2 A St")
    assert build_packages(wf_db, cid, tid, date.today()).disagreements == []


def test_an_unparseable_address_still_reaches_the_sort(wf_db):
    """Dimension 5 — no silent drops. The tote is physically on the truck; it
    must reach a walker even when its address would not parse."""
    cid, tid = uuid.uuid4(), uuid.uuid4()
    _entry(wf_db, cid, tid, "5270", None, address="ask the doorman")

    res = build_packages(wf_db, cid, tid, date.today())
    assert len(res.packages) == 1
    assert res.packages[0].block_key is None
    assert res.unparseable and "5270" in res.unparseable[0]


def test_a_tote_with_no_address_is_reported_not_dropped(wf_db):
    """The BTR sheet says the tote is on the truck. Nobody addressed it. It must
    surface for the captain, not vanish from the sort."""
    from app.models.btr_sheet import BTRSheet, BTRRoute, BTRBag
    cid, tid = uuid.uuid4(), uuid.uuid4()

    sheet = BTRSheet(id=uuid.uuid4(), company_id=cid, truck_id=tid,
                     sheet_date=date.today(), source="csv")
    wf_db.add(sheet); wf_db.flush()
    route = BTRRoute(id=uuid.uuid4(), company_id=cid, btr_sheet_id=sheet.id,
                     amazon_route_name="WE37")
    wf_db.add(route); wf_db.flush()
    for bag in ("5270", "7171"):
        wf_db.add(BTRBag(id=uuid.uuid4(), company_id=cid, btr_sheet_id=sheet.id,
                         btr_route_id=route.id, bag_id=bag))
    wf_db.commit()

    _entry(wf_db, cid, tid, "5270", "W_36_St_100")      # only one addressed

    res = build_packages(wf_db, cid, tid, date.today())
    assert res.unaddressed_bags == ["7171"]


def test_no_btr_sheet_means_nothing_is_known_to_be_missing(wf_db):
    """The sheet is a convenience, not a prerequisite. Without one the entered
    addresses ARE the inventory — reporting phantom missing totes would be worse
    than reporting none."""
    cid, tid = uuid.uuid4(), uuid.uuid4()
    _entry(wf_db, cid, tid, "5270", "W_36_St_100")
    assert build_packages(wf_db, cid, tid, date.today()).unaddressed_bags == []


def test_adapter_is_tenant_scoped(wf_db):
    """Dimension 1. Another company's entries for the same bag id must not leak."""
    mine, theirs, tid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    _entry(wf_db, mine, tid, "5270", "W_36_St_100")
    _entry(wf_db, theirs, tid, "9999", "E_50_St_900")

    res = build_packages(wf_db, mine, tid, date.today())
    assert {p.bag_id for p in res.packages} == {"5270"}


def test_adapter_is_date_scoped(wf_db):
    """Yesterday's totes are not on today's truck."""
    from datetime import timedelta
    from app.models.tote_address import ToteAddress
    cid, tid = uuid.uuid4(), uuid.uuid4()
    wf_db.add(ToteAddress(
        id=uuid.uuid4(), company_id=cid, truck_id=tid,
        entry_date=date.today() - timedelta(days=1), bag_id="OLD",
        raw_address="1 A St", block_key="W_36_St_100", entry_sequence=1,
    ))
    wf_db.commit()
    _entry(wf_db, cid, tid, "5270", "W_36_St_100")

    res = build_packages(wf_db, cid, tid, date.today())
    assert {p.bag_id for p in res.packages} == {"5270"}


# ── THE CLAIM: the real sort accepts this input unchanged (D5) ────────────────

def test_run_sort_accepts_adapter_output(wf_db):
    """If this fails, D5 is wrong and workforce mode needs a forked sort.

    Calls the genuine `route_sort.run_sort` — not a stub — with packages the
    adapter built, and asserts it produces routes carrying those totes.
    """
    from app.services.route_sort import run_sort
    from app.schemas.walker_routes import SortRequest

    cid, tid = uuid.uuid4(), uuid.uuid4()
    # Two totes on adjacent blocks of the same street, three addresses each.
    for bag, block in (("5270", "W_36_St_100"), ("7171", "W_36_St_200")):
        for i in range(1, 4):
            _entry(wf_db, cid, tid, bag, block, seq=i, address=f"{i} W 36 St")

    res = build_packages(wf_db, cid, tid, date.today())
    assert len(res.packages) == 6

    result = run_sort(
        request=SortRequest(
            truck_assignment_id=uuid.uuid4(),
            route_date=date.today(),
            packages=res.packages,
        ),
        address_workloads={},
        block_workloads={},
        difficulty_flags={},
    )

    assert result.routes, "the real sort produced no routes from adapter output"
    carried = {b for r in result.routes for b in r.tote_ids}
    assert carried == {"5270", "7171"}, f"totes lost or invented: {carried}"


def test_run_sort_keeps_a_split_tote_whole(wf_db):
    """A tote is the atomic unit — the majority vote decides its block, but the
    tote is never split across routes. Verified through the real sort."""
    from app.services.route_sort import run_sort
    from app.schemas.walker_routes import SortRequest

    cid, tid = uuid.uuid4(), uuid.uuid4()
    _entry(wf_db, cid, tid, "5270", "W_36_St_100", seq=1, address="1 W 36 St")
    _entry(wf_db, cid, tid, "5270", "W_36_St_100", seq=2, address="2 W 36 St")
    _entry(wf_db, cid, tid, "5270", "E_50_St_900", seq=3, address="900 E 50 St")

    res = build_packages(wf_db, cid, tid, date.today())
    result = run_sort(
        request=SortRequest(truck_assignment_id=uuid.uuid4(),
                            route_date=date.today(), packages=res.packages),
        address_workloads={}, block_workloads={}, difficulty_flags={},
    )
    holders = [r for r in result.routes if "5270" in r.tote_ids]
    assert len(holders) == 1, "a tote must not be split across routes"

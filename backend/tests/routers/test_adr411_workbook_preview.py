"""ADR-411 — workbook preview: partial failure, and the unclaimed-truck offer.

The two decisions worth pinning:

  - D3: a bad worksheet must NOT sink the good ones. ADR-290 D6 rejects a
    DSP-mismatched sheet outright; scoped to a workbook that would let one foreign
    worksheet block the morning for the whole fleet.
  - D6: an unmatched worksheet is offered against trucks ABSENT from the workbook
    before the create path. Reading one sheet at a time, a reassigned anchor is
    indistinguishable from a new truck.
"""
import uuid
from pathlib import Path

import pytest

from app.models.truck import Truck
from app.routers.btr_sheets import _unclaimed_trucks, UnclaimedTruckOut, WorkbookSheetOut
from app.services.btr_ingestor import XLSXBTRIngestor
from tests.conftest import SEED_COMPANY_ID, make_truck

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
DAY1 = FIXTURES / "btr_sheet_verified.xlsx"

# The verified fleet (ADR-410 context).
FLEET = {
    "Morgan": (40.76066, -73.99086),
    "Atlas":  (40.75643, -73.99744),
    "Viking": (40.76352, -73.99244),
    "Eagle":  (40.76017, -73.99551),
    "Titan":  (40.76061, -73.99126),
    "Falcon": (40.75603, -73.99675),
}
NEW_ANCHOR = (40.76386, -73.99611)   # appears on day 2, 311 m from Viking


def _register(db, name, lat, lng):
    t = make_truck(db, name=name)
    t.amazon_anchor_lat, t.amazon_anchor_lng = lat, lng
    db.commit()
    db.refresh(t)
    return t


def test_every_worksheet_resolves_when_the_fleet_is_registered(db):
    """The happy path the whole ADR exists for: six sheets, six trucks, no lookup."""
    from app.services.resolve_truck_anchor import resolve_truck_by_anchor

    for name, (lat, lng) in FLEET.items():
        _register(db, name, lat, lng)

    sheets = XLSXBTRIngestor(DAY1.read_bytes()).ingest()
    resolved = [
        resolve_truck_by_anchor(db, SEED_COMPANY_ID, s.amazon_anchor_lat, s.amazon_anchor_lng)
        for s in sheets
    ]
    assert all(r is not None for r in resolved)
    assert {r.name for r in resolved} == set(FLEET)


def test_no_unclaimed_trucks_when_every_sheet_matched(db):
    trucks = [_register(db, n, *a) for n, a in FLEET.items()]
    matched = {t.id for t in trucks}
    assert _unclaimed_trucks(db, SEED_COMPANY_ID, matched, []) == []


def test_a_truck_absent_from_the_workbook_is_reported_unclaimed(db):
    """D6. Viking has no worksheet; it is the candidate for the orphan anchor."""
    trucks = {n: _register(db, n, *a) for n, a in FLEET.items()}
    matched = {t.id for n, t in trucks.items() if n != "Viking"}

    orphan = WorkbookSheetOut(
        worksheet="BTR43",
        sheet=_fake_sheet_out(*NEW_ANCHOR),
    )
    unclaimed = _unclaimed_trucks(db, SEED_COMPANY_ID, matched, [orphan])

    assert [u.truck_name for u in unclaimed] == ["Viking"]
    # Described, not chosen: 311 m from the orphan anchor.
    assert unclaimed[0].distance_m == pytest.approx(311, abs=2)


def test_distance_is_omitted_when_more_than_one_sheet_is_unmatched(db):
    """A distance implies a pairing. With two orphans there is no pairing to imply,
    and offering one would preselect a guess (D6)."""
    trucks = {n: _register(db, n, *a) for n, a in FLEET.items()}
    matched = {t.id for n, t in trucks.items() if n not in ("Viking", "Falcon")}

    orphans = [
        WorkbookSheetOut(worksheet="A", sheet=_fake_sheet_out(*NEW_ANCHOR)),
        WorkbookSheetOut(worksheet="B", sheet=_fake_sheet_out(40.7700, -73.9800)),
    ]
    unclaimed = _unclaimed_trucks(db, SEED_COMPANY_ID, matched, orphans)

    assert {u.truck_name for u in unclaimed} == {"Viking", "Falcon"}
    assert all(u.distance_m is None for u in unclaimed)


def test_unclaimed_never_includes_another_companys_truck(db):
    """Dimension 1."""
    other = uuid.uuid4()
    t = make_truck(db, name="Foreign")
    t.company_id = other
    t.amazon_anchor_lat, t.amazon_anchor_lng = FLEET["Viking"]
    db.commit()

    assert _unclaimed_trucks(db, SEED_COMPANY_ID, set(), []) == []


def test_unclaimed_ignores_trucks_with_no_registered_anchor(db):
    """A truck nobody registered cannot be 'absent from the workbook' — it was
    never identifiable in the first place."""
    make_truck(db, name="Unregistered")
    assert _unclaimed_trucks(db, SEED_COMPANY_ID, set(), []) == []


# ── helper ────────────────────────────────────────────────────────────────────

def _fake_sheet_out(lat, lng):
    """A BTRSheetOut carrying only what _unclaimed_trucks reads."""
    from app.routers.btr_sheets import BTRSheetOut
    return BTRSheetOut(amazon_anchor_lat=lat, amazon_anchor_lng=lng, truck_match=None)


def test_workbook_preview_has_no_write_path():
    """ADR-411 D3/D4, enforced structurally like ADR-290 D3's single-sheet form.

    A workbook carries the whole fleet, so a preview that could persist would let
    one upload write six trucks' totes with no human confirming any of them. The
    write it precedes, confirm_btr_sheet, stays per-truck and audited.
    """
    import inspect
    from app.routers import btr_sheets

    for fn in (btr_sheets.preview_btr_workbook, btr_sheets._unclaimed_trucks):
        src = inspect.getsource(fn)
        for writer in ("db.add", "db.commit", "db.flush", "db.delete"):
            assert writer not in src, f"{fn.__name__} must not call {writer}"

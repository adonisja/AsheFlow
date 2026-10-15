"""ADR-506 — the BTR test workbooks are invented, and stay that way.

The previous fixtures were a carrier's confidential exports with coordinates
shifted (ADR-489 D2): the layout, the relative geometry of a real station, and
the shape of real routes all survived the transform. They were replaced by
workbooks generated from hand-written data. These tests keep a real export from
coming back:

1. Each committed workbook equals what make_btr_workbooks.py writes, cell by
   cell. Swapping in an exported file fails here even if every other test passes.
2. The fixtures folder holds no other spreadsheet.
3. Every anchor is in the open Atlantic, where no delivery station exists.
"""
from pathlib import Path

import openpyxl

from tests.fixtures import make_btr_workbooks as G

FIXTURES = Path(G.__file__).resolve().parent


def _cells(path):
    wb = openpyxl.load_workbook(path, data_only=True)
    return {ws.title: _trim(list(r) for r in ws.iter_rows(values_only=True)) for ws in wb.worksheets}


def _trim(rows):
    """openpyxl does not keep trailing all-blank rows; compare without them."""
    rows = list(rows)
    while rows and all(v is None for v in rows[-1]):
        rows.pop()
    return rows


def _expected(day):
    return {label: _trim(G.grid(label, anchor, routes)) for label, anchor, routes in day}


def test_the_committed_workbooks_are_exactly_the_generated_ones():
    for name, day in (("btr_workbook_day1.xlsx", G.DAY1), ("btr_workbook_day2.xlsx", G.DAY2)):
        got = _cells(FIXTURES / name)
        want = _expected(day)
        assert list(got) == list(want), f"{name}: worksheets differ from the generator"
        for sheet in want:
            assert got[sheet] == want[sheet], (
                f"{name}/{sheet} differs from make_btr_workbooks.py. Regenerate it; "
                "never edit or replace the file by hand (ADR-506)."
            )


def test_no_other_spreadsheet_is_in_the_fixtures_folder():
    found = sorted(p.name for p in FIXTURES.iterdir() if p.suffix.lower() in {".xlsx", ".xls", ".csv"})
    assert found == ["btr_workbook_day1.xlsx", "btr_workbook_day2.xlsx"], (
        f"unexpected spreadsheet fixture(s): {found}. Real exports are confidential; "
        "generate test data instead (ADR-506)."
    )


def test_every_anchor_is_in_the_open_ocean():
    for name, (lat, lng) in G.ANCHORS.items():
        assert 0 < lat < 1 and -31 < lng < -30, f"{name} anchor {lat},{lng} is not the invented area"

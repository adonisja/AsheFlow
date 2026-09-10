"""ADR-411 — a workbook is the day's whole fleet, parsed one worksheet per truck.

Both fixtures are the real dispatch exports, one day apart. The pair is the point:
every BTR label moved between them while five of six anchors stayed identical, which
is what makes the anchor the identifier and the label useless as one (ADR-410).

The load-bearing test is the block folding. A route occupies several rows — only the
first carries its fields, the rest carry only extra bag labels — so a parser that
flattens rows drops those bags SILENTLY, with no error and a plausible-looking sheet.
The sheet's own printed Bag Count is what catches it.
"""
from pathlib import Path

import pytest

from app.services.btr_ingestor import XLSXBTRIngestor

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
DAY1 = FIXTURES / "btr_sheet_verified.xlsx"        # 2026-09-09
DAY2 = FIXTURES / "btr_sheet_verified_day2.xlsx"   # 2026-09-10


def _sheets(path):
    return XLSXBTRIngestor(path.read_bytes()).ingest()


def test_a_workbook_yields_one_sheet_per_worksheet():
    """D1. The old CSV path would flatten six trucks into one sheet."""
    sheets = _sheets(DAY1)
    assert len(sheets) == 6
    assert [s.btr_loading_zone for s in sheets] == [
        "BTR43", "BTR44", "BTR45", "BTR46", "BTR47", "BTR48",
    ]


def test_each_worksheet_keeps_its_own_header():
    """A flattening parser would give every truck BTR43's anchor and DSP."""
    by_zone = {s.btr_loading_zone: s for s in _sheets(DAY1)}
    assert by_zone["BTR43"].amazon_anchor_lat == 40.76066
    assert by_zone["BTR48"].amazon_anchor_lat == 40.75603
    assert {s.dsp for s in _sheets(DAY1)} == {"NYCD"}


def test_route_count_matches_each_sheets_printed_total():
    """D2's arithmetic check: the header states Total Routes per truck."""
    for s in _sheets(DAY1):
        assert len(s.routes) == s.amazon_route_count, s.btr_loading_zone


def test_continuation_rows_fold_into_the_route_above():
    """The whole reason csv.DictReader cannot read this.

    WE119 (BTR44) prints Bag Count 2 across two rows: the second row carries only
    a bag label. Flattened, that row has no Name and is skipped — the tote vanishes.
    """
    btr44 = {s.btr_loading_zone: s for s in _sheets(DAY1)}["BTR44"]
    we119 = next(r for r in btr44.routes if r.amazon_route_name == "WE119")
    assert we119.bag_count == 2
    assert len(we119.bags) == 2


def test_bags_reconcile_against_the_printed_counts():
    """339 bags are printed across day 1. Exactly one route legitimately fails to
    reconcile — BTR44/WE123 prints `Yellow 3508` and `Black 3508`, and
    parse_bag_labels dedupes on bag_id alone (ADR-290), so one is dropped.

    Pinned deliberately: it is a pre-existing dedupe rule, NOT a folding bug, and
    this test fails loudly if the folding ever starts losing other bags.
    """
    unreconciled = [
        (s.btr_loading_zone, r.amazon_route_name, r.bag_count, len(r.bags))
        for s in _sheets(DAY1)
        for r in s.routes
        if r.bag_count is not None and r.bag_count != len(r.bags)
    ]
    assert unreconciled == [("BTR44", "WE123", 4, 3)]


def test_ov_zones_survive_the_workbook_path():
    """ADR-405's zone parsing applies per worksheet, unchanged."""
    total = sum(z.ov_count or 0 for s in _sheets(DAY1) for r in s.routes for z in r.ov_zones)
    assert total == 1106


def test_the_second_export_parses_and_every_btr_label_moved():
    """ADR-410's premise, as data.

    Day 2's labels are BTR41-BTR46 where day 1's were BTR43-BTR48, and the anchors
    are what carry across. If this ever fails because labels DID stay put, the
    anchor-as-identifier reasoning deserves re-reading — it would not be wrong,
    but its evidence would have changed.
    """
    d1 = {s.btr_loading_zone: (s.amazon_anchor_lat, s.amazon_anchor_lng) for s in _sheets(DAY1)}
    d2 = {s.btr_loading_zone: (s.amazon_anchor_lat, s.amazon_anchor_lng) for s in _sheets(DAY2)}

    assert len(d2) == 6
    assert set(d1) != set(d2), "BTR labels are expected to rotate between days"

    shared_anchors = set(d1.values()) & set(d2.values())
    assert len(shared_anchors) == 5, "five of six anchors recur exactly"

    # And the label is genuinely useless as a key: where a label appears on both
    # days it points at a DIFFERENT anchor.
    for label in set(d1) & set(d2):
        assert d1[label] != d2[label], f"{label} kept its anchor across days"


def test_an_empty_workbook_yields_no_sheets():
    """openpyxl on a workbook with a single blank sheet must not raise."""
    import io, openpyxl
    wb = openpyxl.Workbook()
    buf = io.BytesIO()
    wb.save(buf)
    sheets = XLSXBTRIngestor(buf.getvalue()).ingest()
    assert all(not s.routes for s in sheets)

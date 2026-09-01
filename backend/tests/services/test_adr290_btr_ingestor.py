"""ADR-290 — BTR sheet parsing, checked against the real printed sheet.

Every fixture here is taken from the photograph the operator supplied, not
invented: BTR31 / Box Truck Parcel (26ft) NYC / NYCD / 40.75643 -73.99744 / 12
routes, then WE37 (56 pkgs, 3 bags, 6 OVs), WE38 and WE39.

The wrapped-label case is the one worth having. A photographed Bag Labels cell
breaks "Orange 4772" across two lines, and a parser that splits naively on
newlines yields a colour word with no id and drops a whole tote.
"""
import pytest

from app.services.btr_ingestor import (
    BTRSheetRead, BTRRouteRead, BTROVZoneRead,
    CSVBTRIngestor, ImageBTRIngestor, ManualBTRIngestor,
    parse_anchor, parse_bag_labels, parse_ov_zones, reconcile,
)


# ── bag labels (ADR-230 format, reused parser) ────────────────────────────────

def test_bag_labels_comma_separated():
    bags = parse_bag_labels("Green 5270, Green 7171, Orange 4772")
    assert [b.bag_id for b in bags] == ["5270", "7171", "4772"]
    assert bags[0].bag_color == "#10B981"     # green
    assert bags[2].bag_color == "#F97316"     # orange


def test_bag_label_wrapped_across_lines():
    """The photographed sheet wraps "Orange 4772" onto two lines. Splitting on
    newlines alone yields a bare colour word and silently loses the tote."""
    bags = parse_bag_labels("Green 5270\nGreen 7171\nOrange\n4772")
    assert [b.bag_id for b in bags] == ["5270", "7171", "4772"]
    assert bags[2].bag_color == "#F97316"


def test_bag_labels_deduplicate():
    """A re-read of the same label is one tote, not two."""
    assert len(parse_bag_labels("Green 5270, Green 5270")) == 1


def test_bag_labels_empty_cell():
    assert parse_bag_labels(None) == []
    assert parse_bag_labels("") == []


# ── OV sort zones ─────────────────────────────────────────────────────────────

def test_ov_zones_from_the_real_cell():
    """WE37's zones must sum to its printed OV Count of 6. The cell interleaves
    the word "OV" between entries, so line-splitting does not work."""
    zones = parse_ov_zones("OV\nA-27.2W | 2\nOV\nA-27.3U | 2\nOV\nA-28.2W | 1\nA-27.3W | 1")
    assert [(z.zone_label, z.ov_count) for z in zones] == [
        ("A-27.2W", 2), ("A-27.3U", 2), ("A-28.2W", 1), ("A-27.3W", 1),
    ]
    assert sum(z.ov_count for z in zones) == 6


def test_ov_zones_empty_cell():
    assert parse_ov_zones(None) == []


# ── anchor point ──────────────────────────────────────────────────────────────

def test_anchor_parses_lat_lng():
    assert parse_anchor("40.75643 -73.99744") == (40.75643, -73.99744)


def test_anchor_missing_is_none_not_zero():
    """(0, 0) is a real coordinate in the Atlantic. An unread cell must be None."""
    assert parse_anchor(None) == (None, None)
    assert parse_anchor("-") == (None, None)


# ── CSV ingest ────────────────────────────────────────────────────────────────

_CSV = (
    "Route,Service Type,DSP,Anchor Point,Total Routes,"
    "Name,Package Count,Bag Count,OV Count,OV Sort Zones,Bag Labels\n"
    'BTR31,Box Truck Parcel (26ft) NYC,NYCD,40.75643 -73.99744,12,'
    'WE37,56,3,6,"A-27.2W | 2 A-27.3U | 2 A-28.2W | 1 A-27.3W | 1",'
    '"Green 5270, Green 7171, Orange 4772"\n'
    'BTR31,Box Truck Parcel (26ft) NYC,NYCD,40.75643 -73.99744,12,'
    'WE38,43,2,5,"A-27.3W | 2 A-28.2X | 2 A-27.2Z | 1",'
    '"Yellow 0483, Orange 6218"\n'
)


def test_csv_reads_the_header_row():
    sheet = CSVBTRIngestor(_CSV).ingest()
    assert sheet.btr_loading_zone == "BTR31"
    assert sheet.service_type == "Box Truck Parcel (26ft) NYC"
    assert sheet.dsp == "NYCD"
    assert sheet.amazon_route_count == 12
    assert sheet.amazon_anchor_lat == 40.75643
    assert sheet.amazon_anchor_lng == -73.99744


def test_csv_reads_routes_and_bags():
    sheet = CSVBTRIngestor(_CSV).ingest()
    assert [r.amazon_route_name for r in sheet.routes] == ["WE37", "WE38"]
    we37 = sheet.routes[0]
    assert (we37.package_count, we37.bag_count, we37.ov_count) == (56, 3, 6)
    assert [b.bag_id for b in we37.bags] == ["5270", "7171", "4772"]
    assert sum(z.ov_count for z in we37.ov_zones) == 6
    assert sheet.bag_count == 5     # 3 + 2 across both routes


def test_csv_is_exact_so_carries_no_confidence():
    """Confidence exists to flag a shaky OCR read. A CSV has nothing to flag,
    and a fake number here would invite a needless confirmation step."""
    assert CSVBTRIngestor(_CSV).ingest().confidence is None


def test_csv_headers_are_matched_loosely():
    """An exported header is rarely byte-exact — case and padding vary."""
    messy = _CSV.replace("Bag Labels", " bag labels ").replace("DSP", "dsp")
    sheet = CSVBTRIngestor(messy).ingest()
    assert sheet.dsp == "NYCD"
    assert [b.bag_id for b in sheet.routes[0].bags] == ["5270", "7171", "4772"]


# ── unread cells are None, never zero ─────────────────────────────────────────

def test_missing_counts_are_none_not_zero():
    """Zero is a measurement. An unread cell reported as 0 would make full-mode
    reconciliation announce a discrepancy that is really a camera miss."""
    csv_no_counts = (
        "Route,DSP,Name,Package Count,Bag Count,OV Count,Bag Labels\n"
        'BTR31,NYCD,WE40,,,,"Green 1111"\n'
    )
    route = CSVBTRIngestor(csv_no_counts).ingest().routes[0]
    assert route.package_count is None
    assert route.bag_count is None
    assert route.ov_count is None


# ── reconciliation warns, never raises ────────────────────────────────────────

def test_reconcile_flags_ov_zone_mismatch():
    sheet = BTRSheetRead(routes=[BTRRouteRead(
        amazon_route_name="WE37", ov_count=6,
        ov_zones=[BTROVZoneRead("A-27.2W", 2)],      # only 2 of 6 read
    )])
    warnings = reconcile(sheet)
    assert any("OV zones sum to 2" in w for w in warnings)


def test_reconcile_flags_bag_count_mismatch():
    sheet = CSVBTRIngestor(
        "Route,DSP,Name,Bag Count,Bag Labels\n"
        'BTR31,NYCD,WE37,3,"Green 5270"\n'            # says 3, only 1 label
    ).ingest()
    assert any("1 bag label(s) read but Bag Count says 3" in w for w in sheet.warnings)


def test_reconcile_is_silent_when_the_sheet_agrees():
    assert CSVBTRIngestor(_CSV).ingest().warnings == []


def test_reconcile_skips_checks_it_cannot_make():
    """A null count is unknown, not wrong — it must not manufacture a warning."""
    sheet = BTRSheetRead(routes=[BTRRouteRead(amazon_route_name="WE37", ov_count=None,
                                              ov_zones=[BTROVZoneRead("A-1.1A", 3)])])
    assert reconcile(sheet) == []


# ── manual ingest ─────────────────────────────────────────────────────────────

def test_manual_matches_csv_for_the_same_sheet():
    """Three sources, one result. A captain typing the sheet must produce what
    dispatch's export produces, or the two paths are not interchangeable."""
    rows = [{
        "Route": "BTR31", "Service Type": "Box Truck Parcel (26ft) NYC",
        "DSP": "NYCD", "Anchor Point": "40.75643 -73.99744", "Total Routes": "12",
        "Name": "WE37", "Package Count": "56", "Bag Count": "3", "OV Count": "6",
        "OV Sort Zones": "A-27.2W | 2 A-27.3U | 2 A-28.2W | 1 A-27.3W | 1",
        "Bag Labels": "Green 5270, Green 7171, Orange 4772",
    }]
    manual = ManualBTRIngestor(rows).ingest()
    csv_sheet = CSVBTRIngestor(_CSV).ingest()

    assert manual.btr_loading_zone == csv_sheet.btr_loading_zone
    assert manual.dsp == csv_sheet.dsp
    assert manual.amazon_anchor_lat == csv_sheet.amazon_anchor_lat
    assert [b.bag_id for b in manual.routes[0].bags] == \
           [b.bag_id for b in csv_sheet.routes[0].bags]


# ── image ingest (Textract stub — never calls AWS) ────────────────────────────

def _textract_table(rows: list[list[str]], confidence: float = 96.0) -> dict:
    """Minimal AnalyzeDocument(TABLES) response for `rows` (first row = header)."""
    blocks: list[dict] = []
    cell_ids: list[str] = []
    for r, row in enumerate(rows, start=1):
        for c, text in enumerate(row, start=1):
            wid, cid = f"w{r}-{c}", f"c{r}-{c}"
            blocks.append({"Id": wid, "BlockType": "WORD", "Text": text,
                           "Confidence": confidence})
            blocks.append({"Id": cid, "BlockType": "CELL", "RowIndex": r, "ColumnIndex": c,
                           "Relationships": [{"Type": "CHILD", "Ids": [wid]}]})
            cell_ids.append(cid)
    blocks.append({"Id": "t1", "BlockType": "TABLE",
                   "Relationships": [{"Type": "CHILD", "Ids": cell_ids}]})
    return {"Blocks": blocks}


class _StubTextract:
    def __init__(self, response): self._response = response
    def analyze_document(self, **_): return self._response


def test_image_ingest_parses_a_table():
    response = _textract_table([
        ["Route", "DSP", "Name", "Package Count", "Bag Labels"],
        ["BTR31", "NYCD", "WE37", "56", "Green 5270"],
    ])
    sheet = ImageBTRIngestor(b"fake", _textract_client=_StubTextract(response)).ingest()
    assert sheet.btr_loading_zone == "BTR31"
    assert sheet.routes[0].amazon_route_name == "WE37"
    assert sheet.routes[0].package_count == 56


def test_image_ingest_reports_confidence():
    """The whole point of the image path: the UI needs to know how shaky the read
    was, because ADR-290 D3 requires a human to confirm before anything persists."""
    response = _textract_table([["Route", "Name"], ["BTR31", "WE37"]], confidence=72.5)
    sheet = ImageBTRIngestor(b"fake", _textract_client=_StubTextract(response)).ingest()
    assert sheet.confidence == pytest.approx(0.725, abs=1e-3)


def test_image_ingest_never_calls_aws_in_tests():
    """If the stub were ignored, this would attempt a real Textract call."""
    stub = _StubTextract(_textract_table([["Route"], ["BTR31"]]))
    ImageBTRIngestor(b"fake", _textract_client=stub).ingest()


def test_a_partial_sheet_is_not_a_warning():
    """The real sheet says Total Routes: 12 while its visible Pick List shows 3 —
    the rest continue below the fold. A cropped photo is the NORMAL case, so
    warning on it would fire on nearly every import and teach the operator to
    ignore the warnings that do matter."""
    sheet = CSVBTRIngestor(_CSV).ingest()      # 2 routes parsed, Total Routes 12
    assert sheet.amazon_route_count == 12
    assert len(sheet.routes) == 2
    assert sheet.warnings == []


def test_more_routes_than_amazon_says_IS_a_warning():
    """The one direction a crop cannot explain — likely two sheets merged."""
    csv_extra = (
        "Route,DSP,Total Routes,Name\n"
        "BTR31,NYCD,1,WE37\n"
        "BTR31,NYCD,1,WE38\n"
    )
    sheet = CSVBTRIngestor(csv_extra).ingest()
    assert any("two sheets merged" in w for w in sheet.warnings)

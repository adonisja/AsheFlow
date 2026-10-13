"""Generate the two BTR dispatch-workbook test fixtures from INVENTED data (ADR-506).

    python3 backend/tests/fixtures/make_btr_workbooks.py

Every value here was written by hand for the tests: truck labels, anchors, route
names, bag numbers, zones and counts. Nothing is copied, transformed or derived
from a real export. ADR-489 D2's fixtures were the real exports with coordinates
shifted, which kept the real station's layout and relative geometry; this
replaces them.

What IS kept is the export's documented LAYOUT, because the parser exists to
read it (btr_ingestor.XLSXBTRIngestor):

    row 1   Route | Service Type | DSP | Dispatch Time | Anchor Point | | Total Routes | Duration
    row 2   <truck values>
    row 3   section labels
    row 4   Dispatch Time | Duration | Name | Package Count | Bag Count | OV Count |
            OV Sort Zones | Bag Labels | Bag Sort Zones
    row 5+  one BLOCK per route: the first row carries every field, each further
            row carries only one more bag label + its zone, then two blank rows.

The quirks the tests pin are built in on purpose, each marked QUIRK below.
Anchors sit in the open Atlantic (~0.5 N, 30.5 W) so they can name no real place.

The committed .xlsx files must equal this script's output; a test checks it, so
a fixture can never be silently swapped for a real export.
"""
from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent
CR = "_x000D_\n"     # QUIRK: the export writes CR+LF inside a cell as `_x000D_` + newline

# Invented anchors. Distances are designed, not measured (checked in tests):
#   MORGAN-TITAN ~34 m (near pair), ATLAS-FALCON <100 m, NEW ~300 m from VIKING.
ANCHORS = {
    "MORGAN": (0.51200, -30.51100),
    "ATLAS":  (0.50800, -30.51700),
    "VIKING": (0.51500, -30.51400),
    "EAGLE":  (0.51100, -30.51550),
    "TITAN":  (0.51197, -30.51130),
    "FALCON": (0.50760, -30.51650),
    "NEW":    (0.51500, -30.51130),   # day 2 only: replaces VIKING's worksheet
}


def _ov(*zones: tuple[str, int]) -> tuple[str, int]:
    """(cell text, declared OV count)."""
    return CR.join(f"{z} | {n} OV" for z, n in zones), sum(n for _, n in zones)


def _route(name, ov, bags, *, bag_count=None, pkgs=30, time="08:40", dur="01:30"):
    """bags: [(colour, number, zone)]. bag_count defaults to len(bags)."""
    return {"name": name, "ov": ov, "bags": bags, "pkgs": pkgs, "time": time,
            "dur": dur, "bag_count": len(bags) if bag_count is None else bag_count}


DAY1 = [
    ("BTR01", "MORGAN", [
        # QUIRK: the first route's bag zone differs from both of its OV zones,
        # and the OV cell carries the CR artefact.
        _route("WX01", _ov(("Z-8.9Z", 7), ("Z-8.3T", 9)),
               [("Yellow", "1101", "Z-9.1E"), ("Yellow", "1102", "Z-9.1E")]),
        # QUIRK: two bags of one route in DIFFERENT zones (rows 9 and 10).
        _route("WX02", _ov(("Z-9.2Y", 3), ("Z-9.5Y", 4)),
               [("Navy", "1201", "Z-9.2E"), ("Navy", "1202", "Z-9.4E")]),
        _route("WX03", _ov(("Z-7.1A", 5)), [("Green", "1301", "Z-7.2E")]),
    ]),
    ("BTR02", "ATLAS", [
        _route("WX18", _ov(("Z-6.1B", 2), ("Z-6.4C", 6)), [("Teal", "2101", "Z-6.2E")]),
        # QUIRK: a continuation row. Bag Count 2 is printed on the first row;
        # the second bag sits alone on the row below.
        _route("WX19", _ov(("Z-6.7D", 4)),
               [("Orange", "2201", "Z-6.5E"), ("Orange", "2202", "Z-6.5E")]),
        # QUIRK: one bag number under two colours. The sheet prints Bag Count 4;
        # parse_bag_labels dedupes on the number (ADR-290), so 3 survive.
        _route("WX23", _ov(("Z-6.9F", 1)),
               [("Yellow", "2301", "Z-6.8E"), ("Black", "2301", "Z-6.8E"),
                ("Navy", "2302", "Z-6.9E"), ("Green", "2303", "Z-6.9E")]),
    ]),
    ("BTR03", "VIKING", [
        _route("WX30", _ov(("Z-5.1G", 8)), [("Red", "3101", "Z-5.2E")]),
        _route("WX31", _ov(("Z-5.3H", 2), ("Z-5.4J", 2), ("Z-5.6K", 3)),
               [("Red", "3201", "Z-5.5E"), ("Blue", "3202", "Z-5.5E")]),
    ]),
    ("BTR04", "EAGLE", [
        _route("WX40", _ov(("Z-4.1L", 6)), [("Pink", "4101", "Z-4.2E")]),
        _route("WX41", _ov(("Z-4.3M", 5), ("Z-4.5N", 5)), [("Pink", "4201", "Z-4.4E")]),
    ]),
    ("BTR05", "TITAN", [
        _route("WX50", _ov(("Z-3.1P", 9)),
               [("Gray", "5101", "Z-3.2E"), ("Gray", "5102", "Z-3.3E"), ("Gray", "5103", "Z-3.3E")]),
    ]),
    ("BTR06", "FALCON", [
        _route("WX60", _ov(("Z-2.1R", 4)), [("Purple", "6101", "Z-2.2E")]),
        _route("WX61", _ov(("Z-2.4S", 7)), [("Purple", "6201", "Z-2.5E"), ("White", "6202", "Z-2.5E")]),
    ]),
]

# QUIRK: every label rotates between days while five of six anchors recur. Where
# a label appears on both days it points at a different anchor (ADR-410).
DAY2 = [
    ("BTR03", "MORGAN", [_route("WY01", _ov(("Z-8.1A", 3)), [("Yellow", "7101", "Z-8.2E")])]),
    ("BTR04", "ATLAS",  [_route("WY02", _ov(("Z-7.1B", 2)), [("Navy", "7201", "Z-7.2E")])]),
    ("BTR05", "NEW",    [_route("WY03", _ov(("Z-6.1C", 4)), [("Green", "7301", "Z-6.2E")])]),
    ("BTR06", "EAGLE",  [_route("WY04", _ov(("Z-5.1D", 1)), [("Teal", "7401", "Z-5.2E")])]),
    ("BTR07", "TITAN",  [_route("WY05", _ov(("Z-4.1E", 5)), [("Red", "7501", "Z-4.2E")])]),
    ("BTR08", "FALCON", [_route("WY06", _ov(("Z-3.1F", 2)), [("Pink", "7601", "Z-3.2E")])]),
]

HEADER_TOP = ["Route", "Service Type", "DSP", "Dispatch Time", "Anchor Point", None,
              "Total Routes", "Duration (H:M)", None]
HEADER_ROUTES = ["Dispatch Time", "Duration (H:M)", "Name", "Package Count", "Bag Count",
                 "OV Count", "OV Sort Zones", "Bag Labels", "Bag Sort Zones"]


def grid(label: str, anchor: str, routes: list[dict]) -> list[list]:
    """One worksheet as rows of cell values, exactly as written."""
    lat, lng = ANCHORS[anchor]
    rows = [
        HEADER_TOP,
        [label, "Box Truck Parcel (Medium)", "TSTD", "-", f"{lat:.5f}  {lng:.5f}", None,
         len(routes), "10:00", None],
        ["Stops for this Route", None, None, None, None, None, "Pick List", None, None],
        HEADER_ROUTES,
    ]
    for r in routes:
        ov_text, ov_count = r["ov"]
        first, *rest = r["bags"]
        # Numbers as numbers: the export stores Total Routes and the three counts
        # as integers, everything else as text (ADR-506, matched cell by cell).
        rows.append([r["time"], r["dur"], r["name"], r["pkgs"], r["bag_count"],
                     ov_count, ov_text, f"{first[0]} {first[1]}", first[2]])
        for colour, number, zone in rest:
            rows.append([None] * 7 + [f"{colour} {number}", zone])
        rows += [[None] * 9, [None] * 9]
    return rows


def build(day: list) -> "openpyxl.Workbook":
    import openpyxl
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for label, anchor, routes in day:
        ws = wb.create_sheet(label)
        for row in grid(label, anchor, routes):
            ws.append(row)
    return wb


def main() -> None:
    build(DAY1).save(HERE / "btr_workbook_day1.xlsx")
    build(DAY2).save(HERE / "btr_workbook_day2.xlsx")
    print("wrote btr_workbook_day1.xlsx, btr_workbook_day2.xlsx")


if __name__ == "__main__":
    main()

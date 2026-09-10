"""Parse an Amazon BTR sheet into a structured result (ADR-290).

Three sources, one result type — the same shape `ManifestIngestor` uses, so the
router does not care where a sheet came from:

    CSVBTRIngestor     dispatch exports a CSV        — preferred, cheapest, exact
    ImageBTRIngestor   a captain photographs it      — Textract TABLES + confirm
    ManualBTRIngestor  someone types it              — the always-available floor

WHY AN OCR READ IS NEVER A WRITE
The sample sheet is creased, skewed, and its Bag Labels column wraps mid-cell
("Orange" on one line, "4772" on the next). `label_ingestor` already records why
this matters: OCR on a bad surface is exactly where a misread becomes a phantom
package. A misread bag id here silently mis-assigns a whole tote, so
`ImageBTRIngestor` returns per-field confidence for a human to CONFIRM, and
nothing is persisted before that.

Bag labels are parsed by `parse_bag_label` — ADR-230's existing parser, unchanged.
The sheet prints exactly the `<Color> <number>` format it already handles.
"""
from __future__ import annotations

import csv
import io
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from app.core.bag_colors import parse_bag_label

logger = logging.getLogger(__name__)


# ── result types ──────────────────────────────────────────────────────────────

@dataclass
class BTRBagRead:
    bag_id: str
    bag_color: Optional[str] = None
    # ADR-405. Where the station staged this bag. Parallel to the label in its
    # own column, so it is zipped in by position rather than parsed out of the
    # label cell.
    sort_zone: Optional[str] = None


@dataclass
class BTROVZoneRead:
    zone_label: str
    ov_count: int


@dataclass
class BTRRouteRead:
    """One Amazon route row from the Pick List."""
    amazon_route_name: str
    # Nullable on purpose: an unread cell must be None, never 0. Zero is a
    # measurement and would make full-mode reconciliation report a discrepancy
    # that is really just a cell the camera missed.
    package_count: Optional[int] = None
    bag_count: Optional[int] = None
    ov_count: Optional[int] = None
    bags: list[BTRBagRead] = field(default_factory=list)
    ov_zones: list[BTROVZoneRead] = field(default_factory=list)


@dataclass
class BTRSheetRead:
    """A whole sheet: the header row plus its routes."""
    btr_loading_zone: Optional[str] = None      # "BTR31"
    service_type: Optional[str] = None          # "Box Truck Parcel (26ft) NYC"
    dsp: Optional[str] = None                   # "NYCD" — validated by the router
    amazon_route_count: Optional[int] = None    # Total Routes
    amazon_anchor_lat: Optional[float] = None
    amazon_anchor_lng: Optional[float] = None
    routes: list[BTRRouteRead] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # 0.0–1.0 mean OCR confidence; None for CSV and manual, which are exact.
    confidence: Optional[float] = None

    @property
    def bag_count(self) -> int:
        return sum(len(r.bags) for r in self.routes)


# ── shared parsing helpers ────────────────────────────────────────────────────

def _to_int(value) -> Optional[int]:
    """None on anything unparseable — never 0. See BTRRouteRead."""
    if value is None:
        return None
    try:
        return int(str(value).strip().replace(",", ""))
    except (TypeError, ValueError):
        return None


# "40.75643 -73.99744" — space or comma separated, second value negative in NYC.
_ANCHOR_RE = re.compile(r"(-?\d+\.\d+)[\s,]+(-?\d+\.\d+)")


def parse_anchor(text: str | None) -> tuple[Optional[float], Optional[float]]:
    """Pull (lat, lng) out of the Anchor Point cell, or (None, None)."""
    if not text:
        return None, None
    m = _ANCHOR_RE.search(str(text))
    if not m:
        return None, None
    try:
        return float(m.group(1)), float(m.group(2))
    except ValueError:
        return None, None


# "A-27.2W | 2" repeated, sometimes with a leading "OV" line between entries.
#
# The middle section is [A-Z0-9.]+, not [\d.]+. The verified export (2026-09-09)
# contains `H-2.AZ | 3 OV`, and a digits-only pattern dropped that entry
# SILENTLY — the route reported 7 OVs where the sheet said 10. Found by ADR-290's
# reconciliation check running over every route of a real file rather than the
# one route on the original photograph.
#
# A dropped zone is not a cosmetic loss: ADR-400 seeds one addressable OV unit
# per zone-count, so three OVs simply never existed for that route.
_OV_ZONE_RE = re.compile(r"([A-Z]-[A-Z0-9.]+[A-Z])\s*\|\s*(\d+)")


def _with_sort_zones(
    bags: list["BTRBagRead"], cell: str | None,
) -> list["BTRBagRead"]:
    """Attach ADR-405 sort zones to already-parsed bags, BY POSITION.

    Labels and zones are two parallel columns that wrap together — one label per
    line, one zone per line — so the nth zone belongs to the nth bag. There is no
    key linking them, which is why this is positional and why a length mismatch
    must not guess.

    A short or absent zone column leaves the remaining bags with `sort_zone=None`
    rather than shifting the alignment: a bag pointed at the wrong shelf is worse
    than a bag with no shelf, because the driver walks to it and finds someone
    else's tote.
    """
    if not cell:
        return bags
    zones = [z.strip() for z in str(cell).replace("_x000D_", "").splitlines() if z.strip()]
    for bag, zone in zip(bags, zones):
        bag.sort_zone = zone
    return bags


def parse_ov_zones(cell: str | None) -> list[BTROVZoneRead]:
    """Every "zone | count" pair in an OV Sort Zones cell.

    The cell stacks entries vertically and interleaves the word "OV", so this
    matches pairs anywhere in the text rather than splitting on lines.
    """
    if not cell:
        return []
    out: list[BTROVZoneRead] = []
    seen: set[str] = set()
    for label, count in _OV_ZONE_RE.findall(str(cell)):
        if label in seen:      # a duplicate label is a re-read, not a second zone
            continue
        seen.add(label)
        out.append(BTROVZoneRead(zone_label=label, ov_count=int(count)))
    return out


def parse_bag_labels(cell: str | None) -> list[BTRBagRead]:
    """Every bag in a Bag Labels cell.

    Entries are separated by commas or newlines, and a photographed cell often
    wraps one label across two lines ("Orange" / "4772"). Rejoining on the colour
    word is what makes the wrapped case parse.
    """
    if not cell:
        return []
    text = str(cell)
    # Split on commas and newlines, then stitch a bare colour word onto the
    # fragment that follows it.
    parts = [p.strip() for p in re.split(r"[,\n]+", text) if p.strip()]
    merged: list[str] = []
    for part in parts:
        if merged and re.fullmatch(r"[A-Za-z]+", merged[-1]):
            # Previous fragment was a lone colour word — this completes it.
            merged[-1] = f"{merged[-1]} {part}"
        else:
            merged.append(part)

    out: list[BTRBagRead] = []
    seen: set[str] = set()
    for label in merged:
        bag_id, color = parse_bag_label(label)
        if not bag_id or bag_id in seen:
            continue
        seen.add(bag_id)
        out.append(BTRBagRead(bag_id=bag_id, bag_color=color))
    return out


def reconcile(sheet: BTRSheetRead) -> list[str]:
    """Cross-check the sheet against itself. Returns warnings, never raises.

    Amazon's own printed totals are the check: OV zone counts should sum to the
    route's OV Count, and parsed bag labels should match its Bag Count. A
    mismatch means a cell was misread — worth surfacing, not worth refusing,
    because the operator can still confirm the values by eye.
    """
    warnings: list[str] = []
    for r in sheet.routes:
        if r.ov_count is not None and r.ov_zones:
            zone_total = sum(z.ov_count for z in r.ov_zones)
            if zone_total != r.ov_count:
                warnings.append(
                    f"{r.amazon_route_name}: OV zones sum to {zone_total} "
                    f"but OV Count says {r.ov_count}."
                )
        if r.bag_count is not None and r.bags and len(r.bags) != r.bag_count:
            warnings.append(
                f"{r.amazon_route_name}: {len(r.bags)} bag label(s) read "
                f"but Bag Count says {r.bag_count}."
            )
    # NOT checked: parsed route count vs Total Routes.
    #
    # On the real sheet Total Routes is 12 while the visible Pick List shows 3 —
    # the rest continue below the fold. A partial read is the NORMAL case for a
    # photograph, so warning on it would fire on almost every import and train
    # the operator to ignore the warnings that matter. Only warn when MORE routes
    # were parsed than Amazon says exist, which cannot be explained by a crop.
    if (
        sheet.amazon_route_count is not None
        and len(sheet.routes) > sheet.amazon_route_count
    ):
        warnings.append(
            f"Parsed {len(sheet.routes)} route(s) but Total Routes says "
            f"{sheet.amazon_route_count} — is this two sheets merged?"
        )
    return warnings


# ── ingestors ─────────────────────────────────────────────────────────────────

# Column names as dispatch's CSV export writes them. Matched case-insensitively
# and ignoring surrounding whitespace, because an exported header is rarely exact.
DEFAULT_COLUMN_MAP = {
    "route":         "Route",
    "service_type":  "Service Type",
    "dsp":           "DSP",
    "anchor_point":  "Anchor Point",
    "total_routes":  "Total Routes",
    "name":          "Name",
    "package_count": "Package Count",
    "bag_count":     "Bag Count",
    "ov_count":      "OV Count",
    "ov_sort_zones": "OV Sort Zones",
    "bag_labels":    "Bag Labels",
    # ADR-405. Column I of the verified export — per-bag station location.
    "bag_sort_zones": "Bag Sort Zones",
}


class BTRSheetIngestor(ABC):
    """Every source produces the same BTRSheetRead."""

    @abstractmethod
    def ingest(self) -> BTRSheetRead:
        ...


def _pick(row: dict, wanted: str) -> Optional[str]:
    """Case/whitespace-insensitive column read."""
    target = wanted.strip().lower()
    for k, v in row.items():
        if k and str(k).strip().lower() == target:
            return v
    return None


def _sheet_from_rows(rows: list[dict], cm: dict) -> BTRSheetRead:
    """Shared row->sheet assembly for the CSV and manual paths.

    The header fields (BTR zone, service type, DSP, anchor, total routes) repeat
    on every row of an export, so the first row carrying each one wins.
    """
    sheet = BTRSheetRead()
    for row in rows:
        if sheet.btr_loading_zone is None:
            sheet.btr_loading_zone = (_pick(row, cm["route"]) or None)
        if sheet.service_type is None:
            v = _pick(row, cm["service_type"])
            sheet.service_type = " ".join(str(v).split()) if v else None
        if sheet.dsp is None:
            v = _pick(row, cm["dsp"])
            sheet.dsp = str(v).strip() if v else None
        if sheet.amazon_route_count is None:
            sheet.amazon_route_count = _to_int(_pick(row, cm["total_routes"]))
        if sheet.amazon_anchor_lat is None:
            lat, lng = parse_anchor(_pick(row, cm["anchor_point"]))
            sheet.amazon_anchor_lat, sheet.amazon_anchor_lng = lat, lng

        name = _pick(row, cm["name"])
        if not name or not str(name).strip():
            continue        # a header-only row carries no route
        sheet.routes.append(BTRRouteRead(
            amazon_route_name=str(name).strip(),
            package_count=_to_int(_pick(row, cm["package_count"])),
            bag_count=_to_int(_pick(row, cm["bag_count"])),
            ov_count=_to_int(_pick(row, cm["ov_count"])),
            bags=_with_sort_zones(
                parse_bag_labels(_pick(row, cm["bag_labels"])),
                _pick(row, cm.get("bag_sort_zones", "Bag Sort Zones")),
            ),
            ov_zones=parse_ov_zones(_pick(row, cm["ov_sort_zones"])),
        ))

    sheet.warnings = reconcile(sheet)
    return sheet


class CSVBTRIngestor(BTRSheetIngestor):
    """Dispatch's CSV export. Exact — no confidence, no confirmation step."""

    def __init__(self, content: bytes | str, column_map: dict | None = None):
        self.content = content.decode("utf-8-sig") if isinstance(content, bytes) else content
        self.column_map = column_map or DEFAULT_COLUMN_MAP

    def ingest(self) -> BTRSheetRead:
        rows = list(csv.DictReader(io.StringIO(self.content)))
        return _sheet_from_rows(rows, self.column_map)


class XLSXBTRIngestor:
    """Dispatch's workbook export — ONE WORKSHEET PER TRUCK (ADR-411 D1).

    Deliberately not a BTRSheetIngestor: that base returns one BTRSheetRead, and a
    workbook returns many. A list-returning override of a scalar contract is a lie
    the type system cannot catch, so this is a sibling with its own signature.

    Each worksheet is laid out as:

        row 0   Route | Service Type | DSP | Dispatch Time | Anchor Point | ...
        row 1   BTR43 | Box Truck ... | NYCD| -             | 40.76066  -73.99086
        row 2   (section labels)
        row 3   Dispatch Time | Duration | Name | Package Count | ... | Bag Labels | ...
        row 4+  one BLOCK per route

    A block is the reason csv.DictReader cannot read this even after conversion: the
    first row of a block carries the route's fields, and the rows beneath carry ONLY
    additional Bag Labels / Bag Sort Zones with every other cell blank (ADR-411 D2).
    Flattening them yields routes with no name, which _sheet_from_rows skips — so the
    bags on those rows would vanish silently.

    Rows are re-emitted as dicts keyed by the row-3 header, which is exactly the
    shape _sheet_from_rows already consumes, so every parsing rule pinned by ADR-290
    and ADR-405 applies unchanged.
    """

    HEADER_ROW  = 3     # the route table's own header
    FIRST_DATA  = 4
    _TRUCK_HDR  = 1     # the row carrying Route / DSP / Anchor Point values

    def __init__(self, content: bytes, column_map: dict | None = None):
        self.content = content
        self.column_map = column_map or DEFAULT_COLUMN_MAP

    def ingest(self) -> list["BTRSheetRead"]:
        """One BTRSheetRead per worksheet, in workbook order."""
        import openpyxl

        wb = openpyxl.load_workbook(
            io.BytesIO(self.content), data_only=True, read_only=True,
        )
        try:
            return [self._sheet(ws) for ws in wb.worksheets]
        finally:
            wb.close()

    # ── one worksheet ─────────────────────────────────────────────────────────

    def _sheet(self, ws) -> "BTRSheetRead":
        grid = [list(r) for r in ws.iter_rows(values_only=True)]
        rows = self._rows_from_grid(grid)
        return _sheet_from_rows(rows, self.column_map)

    def _rows_from_grid(self, grid: list[list]) -> list[dict]:
        """Fold each route's continuation rows into the route that owns them.

        The truck-level header (row 1) repeats onto every emitted row because
        _sheet_from_rows reads those fields from "the first row carrying each".
        """
        if len(grid) <= self.FIRST_DATA:
            return []

        cm = self.column_map
        header = [str(c).strip() if c is not None else "" for c in grid[self.HEADER_ROW]]
        truck  = grid[self._TRUCK_HDR]

        def cell(r, i):
            return r[i] if i < len(r) else None

        # Column indexes on the truck header row are positional, not named: row 0's
        # labels are the ones that name them.
        top = [str(c).strip() if c is not None else "" for c in grid[0]]
        def top_idx(name):
            t = name.strip().lower()
            for i, c in enumerate(top):
                if c.strip().lower() == t:
                    return i
            return None

        truck_fields = {}
        for key in ("route", "service_type", "dsp", "anchor_point", "total_routes"):
            i = top_idx(cm[key])
            if i is not None:
                truck_fields[cm[key]] = cell(truck, i)

        def col(name):
            t = name.strip().lower()
            for i, c in enumerate(header):
                if c.strip().lower() == t:
                    return i
            return None

        i_name  = col(cm["name"])
        i_bag   = col(cm["bag_labels"])
        i_zone  = col(cm.get("bag_sort_zones", "Bag Sort Zones"))

        out: list[dict] = []
        for raw in grid[self.FIRST_DATA:]:
            name = cell(raw, i_name) if i_name is not None else None
            has_name = name is not None and str(name).strip() != ""

            if has_name:
                row = dict(truck_fields)
                for i, h in enumerate(header):
                    if h:
                        row[h] = cell(raw, i)
                out.append(row)
                continue

            # A continuation row: only its bag label and sort zone are real, and they
            # belong to the route above. Appending with a separator lets the existing
            # parse_bag_labels/_with_sort_zones handle them as if they had been in the
            # original cell.
            if not out:
                continue        # stray rows before the first route
            bag = cell(raw, i_bag) if i_bag is not None else None
            if bag is None or str(bag).strip() == "":
                continue        # a blank spacer row between blocks

            prev = out[-1]
            zone = cell(raw, i_zone) if i_zone is not None else None
            bag_key = header[i_bag]
            prev[bag_key] = f"{prev.get(bag_key) or ''}\n{bag}".strip()
            if i_zone is not None and zone is not None and str(zone).strip():
                zone_key = header[i_zone]
                prev[zone_key] = f"{prev.get(zone_key) or ''}\n{zone}".strip()

        return out


class ManualBTRIngestor(BTRSheetIngestor):
    """Typed by a human. The floor that always works, whatever the sheet looks like."""

    def __init__(self, rows: list[dict], column_map: dict | None = None):
        self.rows = rows
        self.column_map = column_map or DEFAULT_COLUMN_MAP

    def ingest(self) -> BTRSheetRead:
        return _sheet_from_rows(self.rows, self.column_map)


class ImageBTRIngestor(BTRSheetIngestor):
    """A photograph of the printed sheet, read with Textract TABLES.

    TABLES, not DetectDocumentText: this sheet IS a grid, which is exactly what
    AnalyzeDocument reconstructs. Same injectable-client shape as
    `ImageManifestIngestor` and `ScorecardIngestor`, so tests never call AWS.

    The result is a SUGGESTION. `confidence` exists so the UI can flag a shaky
    read, and the router must not persist before a human confirms.
    """

    def __init__(self, document_bytes: bytes, column_map: dict | None = None,
                 _textract_client=None):
        self.document_bytes = document_bytes
        self.column_map = column_map or DEFAULT_COLUMN_MAP
        self._client = _textract_client

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            import boto3
            from app.core.config import settings
            # region_name is REQUIRED: the container sets AWS_REGION but boto3
            # reads AWS_DEFAULT_REGION, so a bare client raises NoRegionError,
            # which a broad except then reports as "could not read the sheet".
            return boto3.client("textract", region_name=settings.aws_region)
        except ImportError as exc:
            raise RuntimeError(
                "boto3 is required for ImageBTRIngestor in production. "
                "Install it with: pip install boto3"
            ) from exc

    @staticmethod
    def extract_rows(response: dict) -> tuple[list[dict], Optional[float]]:
        """Textract TABLES response -> (row dicts, mean cell confidence).

        Reconstructs the grid by walking TABLE -> CELL -> WORD relationships,
        then treats the first row with any non-empty cell as the header.
        """
        blocks = {b["Id"]: b for b in response.get("Blocks", [])}
        confidences: list[float] = []

        def cell_text(cell: dict) -> str:
            words = []
            for rel in cell.get("Relationships", []):
                if rel["Type"] != "CHILD":
                    continue
                for cid in rel["Ids"]:
                    child = blocks.get(cid, {})
                    if child.get("BlockType") == "WORD":
                        words.append(child.get("Text", ""))
                        if "Confidence" in child:
                            confidences.append(float(child["Confidence"]))
            return " ".join(words).strip()

        rows: list[dict] = []
        for block in response.get("Blocks", []):
            if block.get("BlockType") != "TABLE":
                continue
            grid: dict[int, dict[int, str]] = {}
            for rel in block.get("Relationships", []):
                if rel["Type"] != "CHILD":
                    continue
                for cid in rel["Ids"]:
                    cell = blocks.get(cid, {})
                    if cell.get("BlockType") != "CELL":
                        continue
                    grid.setdefault(cell.get("RowIndex", 1), {})[
                        cell.get("ColumnIndex", 1)
                    ] = cell_text(cell)
            if not grid:
                continue

            ordered = [grid[r] for r in sorted(grid)]
            header, start = None, 0
            for i, r in enumerate(ordered):
                if any(v.strip() for v in r.values()):
                    header, start = r, i + 1
                    break
            if header is None:
                continue
            cols = max(header) if header else 0
            names = [header.get(c, "") for c in range(1, cols + 1)]
            for r in ordered[start:]:
                rows.append(dict(zip(names, [r.get(c, "") for c in range(1, cols + 1)])))

        mean = round(sum(confidences) / len(confidences) / 100.0, 3) if confidences else None
        return rows, mean

    def ingest(self) -> BTRSheetRead:
        client = self._get_client()
        response = client.analyze_document(
            Document={"Bytes": self.document_bytes},
            FeatureTypes=["TABLES"],
        )
        rows, confidence = self.extract_rows(response)
        sheet = _sheet_from_rows(rows, self.column_map)
        sheet.confidence = confidence
        return sheet

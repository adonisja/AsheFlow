from __future__ import annotations

import csv
import io
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

import openpyxl

logger = logging.getLogger(__name__)


@dataclass
class RawPackage:
    tba: str
    address: str | None = None
    bag_id: str | None = None
    tag_number: str | None = None
    package_type: str | None = None
    # Amazon may supply lat/lng; GeoClient is the primary source during enrichment.
    # These are optional — enrichment does not require them.
    lat: Optional[float] = None
    lng: Optional[float] = None


@dataclass
class PendingResolutionPackage:
    """A manifest row whose TBA barcode was missing or unreadable.

    Dispatch and the driver must supply the TBA via the UI before this package
    can be enriched and sorted. The raw address is preserved so they can
    cross-reference the physical package.
    """
    row_index: int
    raw_address: str | None
    bag_id: str | None


@dataclass
class ManifestCounts:
    """Header totals from the Amazon manifest preamble."""
    package_count: int | None = None
    bag_count: int | None = None
    ov_count: int | None = None
    ov_sort_zones: str | None = None


@dataclass
class IngestResult:
    packages: list[RawPackage]
    pending: list[PendingResolutionPackage]
    counts: ManifestCounts
    warnings: list[str]


# Column names from Amazon's Delivery Station manifest CSV.
# lat/lng are optional — Amazon may or may not include them.
DEFAULT_COLUMN_MAP = {
    "tba":          "Tracking ID",
    "lat":          "Latitude",
    "lng":          "Longitude",
    "address":      "Address",
    "bag_id":       "Bag ID",
    "tag_number":   "Tag Number",
    "package_type": "Package Type",
}

# Header preamble field names (first column of summary rows above the package table)
_HEADER_ALIASES = {
    "package count":  "package_count",
    "packages":       "package_count",
    "bag count":      "bag_count",
    "bags":           "bag_count",
    "ov count":       "ov_count",
    "ovs":            "ov_count",
    "ov sort zones":  "ov_sort_zones",
    "ov sort zone":   "ov_sort_zones",
}


def _parse_int(value) -> int | None:
    try:
        return int(str(value).strip().replace(",", ""))
    except (TypeError, ValueError):
        return None


def _extract_header_counts(rows: list[dict]) -> ManifestCounts:
    """Scan rows for preamble key-value pairs and return header totals.

    Amazon manifests often include summary rows at the top (e.g. a row where
    the first cell is "Package Count" and the second is "247"). These rows
    appear before or mixed with the package table and are identified by
    matching the first cell against known aliases.
    """
    counts = ManifestCounts()
    for row in rows:
        values = list(row.values())
        if not values:
            continue
        key = str(values[0] or "").strip().lower()
        mapped = _HEADER_ALIASES.get(key)
        if mapped and len(values) > 1:
            val = values[1]
            if mapped == "ov_sort_zones":
                counts.ov_sort_zones = str(val).strip() if val else None
            else:
                setattr(counts, mapped, _parse_int(val))
    return counts


def _reconcile(counts: ManifestCounts, packages: list[RawPackage], pending: list[PendingResolutionPackage]) -> list[str]:
    """Compare parsed totals against manifest header totals; return warning strings."""
    warnings: list[str] = []
    total_parsed = len(packages) + len(pending)

    if counts.package_count is not None and total_parsed != counts.package_count:
        warnings.append(
            f"Package count mismatch: manifest header says {counts.package_count}, "
            f"parsed {total_parsed} rows ({len(packages)} valid, {len(pending)} pending TBA)."
        )

    if counts.bag_count is not None:
        parsed_bags = len({p.bag_id for p in packages if p.bag_id})
        if parsed_bags != counts.bag_count:
            warnings.append(
                f"Bag count mismatch: manifest header says {counts.bag_count}, "
                f"found {parsed_bags} unique bag IDs."
            )

    if counts.ov_count is not None:
        parsed_ovs = sum(
            1 for p in packages
            if p.package_type and p.package_type.upper().startswith("OV")
        )
        if parsed_ovs != counts.ov_count:
            warnings.append(
                f"OV count mismatch: manifest header says {counts.ov_count}, "
                f"parsed {parsed_ovs} OV packages."
            )

    return warnings


class ManifestIngestor(ABC):
    """Abstract base for all manifest ingestion sources."""

    @abstractmethod
    def ingest(self) -> IngestResult:
        ...


class APIManifestIngestor(ManifestIngestor):
    """Receives a pre-parsed package list from an Amazon API feed."""

    def __init__(self, packages: list[dict], column_map: dict | None = None):
        super().__init__()
        self.packages = packages
        self.column_map = column_map or DEFAULT_COLUMN_MAP

    def ingest(self) -> IngestResult:
        packages: list[RawPackage] = []
        pending: list[PendingResolutionPackage] = []
        cm = self.column_map

        for i, row in enumerate(self.packages):
            try:
                raw_tba = str(row.get(cm["tba"], "") or "").strip()
                address = row.get(cm.get("address", "")) or None
                bag_id = row.get(cm.get("bag_id", "")) or None

                if not raw_tba:
                    pending.append(PendingResolutionPackage(
                        row_index=i,
                        raw_address=str(address) if address else None,
                        bag_id=str(bag_id) if bag_id else None,
                    ))
                    continue

                lat_raw = row.get(cm.get("lat", ""))
                lng_raw = row.get(cm.get("lng", ""))
                try:
                    lat = float(lat_raw) if lat_raw not in (None, "") else None
                    lng = float(lng_raw) if lng_raw not in (None, "") else None
                except (TypeError, ValueError):
                    lat, lng = None, None

                packages.append(RawPackage(
                    tba=raw_tba,
                    address=str(address) if address else None,
                    bag_id=str(bag_id) if bag_id else None,
                    tag_number=row.get(cm.get("tag_number", "")) or None,
                    package_type=row.get(cm.get("package_type", "")) or None,
                    lat=lat,
                    lng=lng,
                ))
            except Exception as exc:
                logger.warning(
                    "manifest_row_parse_failed",
                    extra={
                        "ingestor": "api",
                        "row_index": i,
                        "error_type": type(exc).__name__,
                        "error": str(exc)[:120],
                    },
                )
                continue

        counts = _extract_header_counts(self.packages)
        warnings = _reconcile(counts, packages, pending)
        return IngestResult(packages=packages, pending=pending, counts=counts, warnings=warnings)


class FileManifestIngestor(ManifestIngestor):
    def __init__(self, file_path: str, column_map: dict | None = None):
        super().__init__()
        self.file_path = file_path
        self.column_map = column_map or DEFAULT_COLUMN_MAP

    def ingest(self) -> IngestResult:
        ext = os.path.splitext(self.file_path)[1].lower()
        if ext == ".csv":
            rows = self._read_csv()
        elif ext in (".xlsx", ".xls"):
            rows = self._read_xlsx()
        else:
            raise ValueError(f"Unsupported file type: {ext}")

        packages: list[RawPackage] = []
        pending: list[PendingResolutionPackage] = []
        cm = self.column_map

        for i, row in enumerate(rows):
            try:
                raw_tba = str(row.get(cm["tba"], "") or "").strip()
                address = row.get(cm.get("address", "")) or None
                bag_id = row.get(cm.get("bag_id", "")) or None

                if not raw_tba:
                    pending.append(PendingResolutionPackage(
                        row_index=i,
                        raw_address=str(address) if address else None,
                        bag_id=str(bag_id) if bag_id else None,
                    ))
                    continue

                lat_raw = row.get(cm.get("lat", ""))
                lng_raw = row.get(cm.get("lng", ""))
                try:
                    lat = float(lat_raw) if lat_raw not in (None, "") else None
                    lng = float(lng_raw) if lng_raw not in (None, "") else None
                except (TypeError, ValueError):
                    lat, lng = None, None

                packages.append(RawPackage(
                    tba=raw_tba,
                    address=str(address) if address else None,
                    bag_id=str(bag_id) if bag_id else None,
                    tag_number=row.get(cm.get("tag_number", "")) or None,
                    package_type=row.get(cm.get("package_type", "")) or None,
                    lat=lat,
                    lng=lng,
                ))
            except Exception as exc:
                logger.warning(
                    "manifest_row_parse_failed",
                    extra={
                        "ingestor": "file",
                        "row_index": i,
                        "error_type": type(exc).__name__,
                        "error": str(exc)[:120],
                    },
                )
                continue

        counts = _extract_header_counts(rows)
        warnings = _reconcile(counts, packages, pending)
        return IngestResult(packages=packages, pending=pending, counts=counts, warnings=warnings)

    def _read_csv(self) -> list[dict]:
        with open(self.file_path, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def _read_xlsx(self) -> list[dict]:
        wb = openpyxl.load_workbook(self.file_path, read_only=True, data_only=True)
        ws = wb.active
        rows = ws.iter_rows(values_only=True)
        headers = [str(h).strip() if h is not None else "" for h in next(rows)]
        return [dict(zip(headers, row)) for row in rows]


class ImageManifestIngestor(ManifestIngestor):
    """Ingest a manifest from a scanned image or PDF using AWS Textract.

    Textract's AnalyzeDocument (TABLES feature) extracts tabular data from
    the document and returns rows that this class normalises into the same
    RawPackage / IngestResult format as FileManifestIngestor.

    Production:  boto3 Textract client (AWS).
    Local dev:   pass a ``_textract_client`` stub that returns pre-canned
                 Textract JSON — the actual AWS call is never made in tests.

    Cost note: AWS Textract TABLES mode costs ~$0.015/page. At 10 companies
    and 250 pages/year each that is ~$37.50/year — well within budget.
    """

    def __init__(
        self,
        document_bytes: bytes,
        column_map: dict | None = None,
        _textract_client=None,   # injected in tests; resolved lazily in prod
    ):
        super().__init__()
        self.document_bytes = document_bytes
        self.column_map = column_map or DEFAULT_COLUMN_MAP
        self._client = _textract_client

    # ------------------------------------------------------------------
    # Internal: Textract → list[dict] row extraction
    # ------------------------------------------------------------------

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            import boto3
            return boto3.client("textract")
        except ImportError as exc:
            raise RuntimeError(
                "boto3 is required for ImageManifestIngestor in production. "
                "Install it with: pip install boto3"
            ) from exc

    @staticmethod
    def _extract_rows_from_textract(response: dict) -> list[dict]:
        """Parse Textract AnalyzeDocument response into a list of row dicts.

        Textract returns Blocks — TABLE, ROW, CELL, WORD — linked by
        relationship IDs. We reconstruct the grid by following CHILD
        relationships from TABLE → ROW → CELL, then reading WORD text.
        The first non-empty row is treated as the header.
        """
        blocks_by_id: dict[str, dict] = {b["Id"]: b for b in response.get("Blocks", [])}

        def _cell_text(cell_block: dict) -> str:
            words = []
            for rel in cell_block.get("Relationships", []):
                if rel["Type"] == "CHILD":
                    for child_id in rel["Ids"]:
                        child = blocks_by_id.get(child_id, {})
                        if child.get("BlockType") == "WORD":
                            words.append(child.get("Text", ""))
            return " ".join(words).strip()

        rows: list[dict] = []

        for block in response.get("Blocks", []):
            if block.get("BlockType") != "TABLE":
                continue

            # Build grid: row_index → col_index → cell text
            grid: dict[int, dict[int, str]] = {}
            for rel in block.get("Relationships", []):
                if rel["Type"] != "CHILD":
                    continue
                for cell_id in rel["Ids"]:
                    cell = blocks_by_id.get(cell_id, {})
                    if cell.get("BlockType") != "CELL":
                        continue
                    row_idx = cell.get("RowIndex", 1)
                    col_idx = cell.get("ColumnIndex", 1)
                    grid.setdefault(row_idx, {})[col_idx] = _cell_text(cell)

            if not grid:
                continue

            sorted_rows = [grid[r] for r in sorted(grid)]
            # First row with at least one non-empty cell is the header
            header_row: dict[int, str] | None = None
            data_start = 0
            for idx, row_grid in enumerate(sorted_rows):
                if any(v.strip() for v in row_grid.values()):
                    header_row = row_grid
                    data_start = idx + 1
                    break

            if header_row is None:
                continue

            col_count = max(header_row) if header_row else 0
            headers = [header_row.get(c, "") for c in range(1, col_count + 1)]

            for row_grid in sorted_rows[data_start:]:
                values = [row_grid.get(c, "") for c in range(1, col_count + 1)]
                rows.append(dict(zip(headers, values)))

        return rows

    # ------------------------------------------------------------------
    # ManifestIngestor contract
    # ------------------------------------------------------------------

    def ingest(self) -> IngestResult:
        client = self._get_client()
        response = client.analyze_document(
            Document={"Bytes": self.document_bytes},
            FeatureTypes=["TABLES"],
        )
        rows = self._extract_rows_from_textract(response)

        packages: list[RawPackage] = []
        pending: list[PendingResolutionPackage] = []
        cm = self.column_map

        for i, row in enumerate(rows):
            try:
                raw_tba = str(row.get(cm["tba"], "") or "").strip()
                address = row.get(cm.get("address", "")) or None
                bag_id = row.get(cm.get("bag_id", "")) or None

                if not raw_tba:
                    pending.append(PendingResolutionPackage(
                        row_index=i,
                        raw_address=str(address) if address else None,
                        bag_id=str(bag_id) if bag_id else None,
                    ))
                    continue

                lat_raw = row.get(cm.get("lat", ""))
                lng_raw = row.get(cm.get("lng", ""))
                try:
                    lat = float(lat_raw) if lat_raw not in (None, "") else None
                    lng = float(lng_raw) if lng_raw not in (None, "") else None
                except (TypeError, ValueError):
                    lat, lng = None, None

                packages.append(RawPackage(
                    tba=raw_tba,
                    address=str(address) if address else None,
                    bag_id=str(bag_id) if bag_id else None,
                    tag_number=row.get(cm.get("tag_number", "")) or None,
                    package_type=row.get(cm.get("package_type", "")) or None,
                    lat=lat,
                    lng=lng,
                ))
            except Exception as exc:
                logger.warning(
                    "manifest_row_parse_failed",
                    extra={
                        "ingestor": "image",
                        "row_index": i,
                        "error_type": type(exc).__name__,
                        "error": str(exc)[:120],
                    },
                )
                continue

        counts = _extract_header_counts(rows)
        warnings = _reconcile(counts, packages, pending)
        return IngestResult(packages=packages, pending=pending, counts=counts, warnings=warnings)

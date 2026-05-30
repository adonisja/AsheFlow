from __future__ import annotations
from dataclasses import dataclass
from abc import ABC, abstractmethod
import csv
import os
import openpyxl

@dataclass
class RawPackage:
    tba: str
    lat: float
    lng: float
    address: str | None = None
    bag_id: str | None = None       # physical tote/bag ID from Amazon manifest
    tag_number: str | None = None   # sort-zone label, e.g. "A-12" — NOT a bag ID
    package_type: str | None = None

# Column names from Amazon's Delivery Station manifest CSV.
# Update these when a real manifest is available to verify.
# All values are case-sensitive and must match the CSV header row exactly.
DEFAULT_COLUMN_MAP = {
    "tba":          "Tracking ID",
    "lat":          "Latitude",
    "lng":          "Longitude",
    "address":      "Address",
    "bag_id":       "Bag ID",
    "tag_number":   "Tag Number",
    "package_type": "Package Type",
}

class ManifestIngestor(ABC):
    """Abstract base for all manifest ingestion sources.
    
    Subclasses implement ingest() for their specific source format.
    All implementations must return a list of RawPackage — the rest
    of the pipeline does not care how the data arrived.
    """

    @abstractmethod
    def ingest(self) -> list[RawPackage]:
        ...

class APIManifestIngestor(ManifestIngestor):
    """Receives a pre-parsed package list from an Amazon API feed (webhook or poll).

    The caller is responsible for fetching from Amazon's API and converting
    the response into a list of raw dicts. This ingestor validates each record
    and normalises it into RawPackage — the rest of the pipeline is identical
    to FileManifestIngestor.
    """

    def __init__(self, packages: list[dict], column_map: dict | None = None):
        super().__init__()
        self.packages = packages
        self.column_map = column_map or DEFAULT_COLUMN_MAP

    def ingest(self) -> list[RawPackage]:
        result: list[RawPackage] = []
        for row in self.packages:
            try:
                pkg = RawPackage(
                    tba          = str(row[self.column_map["tba"]]).strip(),
                    lat          = float(row[self.column_map["lat"]]),
                    lng          = float(row[self.column_map["lng"]]),
                    address      = row.get(self.column_map["address"]) or None,
                    bag_id       = row.get(self.column_map.get("bag_id", "")) or None,
                    tag_number   = row.get(self.column_map["tag_number"]) or None,
                    package_type = row.get(self.column_map["package_type"]) or None,
                )
                result.append(pkg)
            except (KeyError, ValueError, TypeError):
                continue
        return result


class FileManifestIngestor(ManifestIngestor):
    def __init__(self, file_path: str, column_map: dict | None = None):
        super().__init__()
        self.file_path = file_path
        self.column_map = column_map or DEFAULT_COLUMN_MAP

    def ingest(self) -> list[RawPackage]:
        ext = os.path.splitext(self.file_path)[1].lower()
        if ext == ".csv":
            rows = self._read_csv()
        elif ext in (".xlsx", ".xls"):
            rows = self._read_xlsx()
        else:
            raise ValueError(f"Unsupported file type: {ext}")
        
        packages = []
        for row in rows:
            try:
                pkg = RawPackage(
                    tba          = str(row[self.column_map["tba"]]).strip(),
                    lat          = float(row[self.column_map["lat"]]),
                    lng          = float(row[self.column_map["lng"]]),
                    address      = row.get(self.column_map["address"]) or None,
                    bag_id       = row.get(self.column_map.get("bag_id", "")) or None,
                    tag_number   = row.get(self.column_map["tag_number"]) or None,
                    package_type = row.get(self.column_map["package_type"]) or None,
                )
                packages.append(pkg)
            except (KeyError, ValueError, TypeError):
                continue

        return packages
    
    def _read_csv(self) -> list[dict]:
        with open(self.file_path, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
        

    def _read_xlsx(self) -> list[dict]:
        wb = openpyxl.load_workbook(self.file_path, read_only=True, data_only=True)
        ws = wb.active
        rows = ws.iter_rows(values_only=True)
        headers = [str(h).strip() if h is not None else "" for h in next(rows)]
        return [dict(zip(headers, row)) for row in rows]
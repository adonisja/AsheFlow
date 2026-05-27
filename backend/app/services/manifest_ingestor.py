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
    tag_number: str | None = None
    package_type: str | None = None

DEFAULT_COLUMN_MAP = {
    "tba":          "tracking_id",      # placeholder — Amazon's actual TBA column name TBD
    "lat":          "latitude",         # placeholder
    "lng":          "longitude",        # placeholder
    "address":      "address",          # placeholder — may not exist
    "tag_number":   "tag_number",       # placeholder
    "package_type": "package_type",     # placeholder
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
"""Parse an uploaded Amazon (NYCD) scorecard image into a structured draft
(ADR-204 Phase C). Reuses the existing AWS Textract integration pattern from
ImageManifestIngestor — no new OCR dependency.

Textract AnalyzeDocument (TABLES + FORMS) extracts the metric table; we map each
row to {key, label, value, flag}. The result is a DRAFT the manager reviews and
edits before saving via POST /scorecards — a misparse never writes an official
number unreviewed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


# Map the scorecard's human labels → stable machine keys (mirrors the entry
# template). Matching is case-insensitive substring on the label Textract reads.
_LABEL_KEYS = [
    ("packages delivered",          "packages_delivered"),
    ("dsb dpmo tier",               "dsb_dpmo_tier"),
    ("delivery success behavior",   "delivery_success_behavior"),
    ("delivery completion dpmo",    "delivery_completion_dpmo"),
    ("cdf",                         "cdf"),
    ("pod tier",                    "pod_tier"),
    ("pod score",                   "pod_score"),
    ("pod success",                 "pod_success"),
    ("pod rejects",                 "pod_rejects"),
]

_FLAG_WORDS = {
    "excellent": "excellent",
    "needs focus": "needs_focus",
    "needs-focus": "needs_focus",
}


@dataclass
class ScorecardDraftMetric:
    key: str
    label: str
    value: str
    flag: Optional[str] = None
    sort_order: int = 0


@dataclass
class ScorecardDraft:
    week: Optional[str] = None
    overall_standing: Optional[str] = None
    metrics: list[ScorecardDraftMetric] = field(default_factory=list)


def _key_for_label(label: str) -> Optional[str]:
    low = label.strip().lower()
    for needle, key in _LABEL_KEYS:
        if needle in low:
            return key
    return None


def _flag_for(text: str) -> Optional[str]:
    low = text.strip().lower()
    for needle, flag in _FLAG_WORDS.items():
        if needle in low:
            return flag
    return None


def _find_week(all_text: str) -> Optional[str]:
    # e.g. "2026-W28"
    m = re.search(r"\b(20\d{2})[-\s]?W\s?(\d{1,2})\b", all_text, re.IGNORECASE)
    if m:
        return f"{m.group(1)}-W{int(m.group(2)):02d}"
    return None


def _find_overall(all_text: str) -> Optional[str]:
    m = re.search(r"OVERALL\s+STANDING\s+([A-Z]+)", all_text, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    # tier words also appear standalone next to "Overall Standing"
    for tier in ("PLATINUM", "GOLD", "SILVER", "BRONZE"):
        if tier in all_text.upper():
            return tier
    return None


class ScorecardIngestor:
    """Textract-backed parser. Mirrors ImageManifestIngestor: lazy boto3 client,
    injectable stub for tests, 503-able RuntimeError when boto3 is absent."""

    def __init__(self, document_bytes: bytes, _textract_client=None):
        self.document_bytes = document_bytes
        self._client = _textract_client

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            import boto3
            return boto3.client("textract")
        except ImportError as exc:
            raise RuntimeError("boto3 is required for Textract scorecard parsing.") from exc

    @staticmethod
    def _all_words(response: dict) -> str:
        return " ".join(
            b.get("Text", "") for b in response.get("Blocks", []) if b.get("BlockType") in ("WORD", "LINE")
        )

    @staticmethod
    def _table_rows(response: dict) -> list[list[str]]:
        """Reconstruct table rows as lists of cell strings (reused grid logic)."""
        blocks_by_id = {b["Id"]: b for b in response.get("Blocks", [])}

        def _cell_text(cell):
            words = []
            for rel in cell.get("Relationships", []):
                if rel["Type"] == "CHILD":
                    for cid in rel["Ids"]:
                        ch = blocks_by_id.get(cid, {})
                        if ch.get("BlockType") == "WORD":
                            words.append(ch.get("Text", ""))
            return " ".join(words).strip()

        out: list[list[str]] = []
        for block in response.get("Blocks", []):
            if block.get("BlockType") != "TABLE":
                continue
            grid: dict[int, dict[int, str]] = {}
            for rel in block.get("Relationships", []):
                if rel["Type"] != "CHILD":
                    continue
                for cid in rel["Ids"]:
                    cell = blocks_by_id.get(cid, {})
                    if cell.get("BlockType") != "CELL":
                        continue
                    grid.setdefault(cell.get("RowIndex", 1), {})[cell.get("ColumnIndex", 1)] = _cell_text(cell)
            for r in sorted(grid):
                cols = grid[r]
                out.append([cols.get(c, "") for c in range(1, (max(cols) if cols else 0) + 1)])
        return out

    def parse(self) -> ScorecardDraft:
        client = self._get_client()
        response = client.analyze_document(
            Document={"Bytes": self.document_bytes},
            FeatureTypes=["TABLES"],
        )
        all_text = self._all_words(response)
        draft = ScorecardDraft(week=_find_week(all_text), overall_standing=_find_overall(all_text))

        order = 0
        for row in self._table_rows(response):
            if not row:
                continue
            label = row[0].strip()
            key = _key_for_label(label)
            if key is None:
                continue
            # The value is the numeric/tier cell; the flag is any Excellent/Needs-Focus cell.
            value = ""
            flag = None
            for cell in row[1:]:
                f = _flag_for(cell)
                if f:
                    flag = f
                    continue
                # first non-empty, non-flag cell that looks like a value
                if cell.strip() and not value:
                    value = cell.strip()
            draft.metrics.append(ScorecardDraftMetric(
                key=key, label=label or key.replace("_", " ").title(),
                value=value, flag=flag, sort_order=order,
            ))
            order += 1

        return draft

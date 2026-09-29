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


# Map the card's human labels -> the registry's machine keys (ADR-475 D1/D2).
#
# TAKEN FROM REAL CARDS, not from what we expect Amazon to call things. The
# previous list was nine labels from one station's layout as it looked when
# ADR-204 was written; it had never heard of a safety metric, so a driver's card
# lost its entire safety half.
#
# ORDER MATTERS. Matching is a case-insensitive substring, so a longer label must
# come before a shorter one it contains -- "customer delivery feedback -
# negative" before "customer delivery feedback", or the negative count is read
# as the DPMO.
#
# `fico` is the entry that proves the map has to come from cards: Amazon labels
# it "Safe Driving Metric", with "FICO" only as a sub-label. Nothing that
# searches for the word would ever find it.
_LABEL_KEYS = [
    # Safety (six on both walker and driver cards; walkers read "No Data")
    ("safe driving metric",                   "fico"),
    ("seatbelt-off rate",                     "seatbelt_rate"),
    ("seatbelt off rate",                     "seatbelt_rate"),
    ("speeding event rate",                   "speeding_rate"),
    ("distractions rate",                     "distractions_rate"),
    ("following distance rate",               "following_distance_rate"),
    ("sign/signal violations",                "signsignal_rate"),
    ("sign signal violations",                "signsignal_rate"),
    # Quality -- longest first where one label contains another
    ("customer delivery feedback - negative", "cdf_negative"),
    ("customer delivery feedback (cdf dpmo)", "cdf_dpmo"),
    ("customer delivery feedback",            "cdf_dpmo"),
    ("customer escalations defect",           "ces_dpmo"),
    ("delivery completion dpmo",              "dc_dpmo"),
    ("delivery success behaviors",            "dsb_dpmo"),
    ("delivery success behavior",             "dsb_dpmo"),
    ("pod acceptance rate",                   "pod"),
    # Context rows Amazon prints that are not scored metrics. Kept so they are
    # RECOGNISED rather than reported as unknown -- a reviewer should not have to
    # dismiss the same benign row on every card.
    ("packages delivered",                    "packages_delivered"),
]

# Recognised, but not a scored metric: no target, no direction, no verdict.
# Named so D3's unknown-row flag means "we could not read this", never "this is
# not a metric".
CONTEXT_KEYS = frozenset({"packages_delivered"})

# Amazon's literal words for an absent measurement (ADR-475 D4). Kept AS TEXT,
# never coerced to 0 -- a zero seatbelt rate is perfect and "No Data" means not
# measured, so conflating them makes an unmeasured walker look flawless.
NO_DATA = "No Data"
_NO_DATA_WORDS = ("no data", "n/a", "not available")


def is_no_data(text: Optional[str]) -> bool:
    """True when Amazon printed an absence rather than a number."""
    if text is None:
        return True
    low = text.strip().lower()
    return low == "" or low in _NO_DATA_WORDS


_FLAG_WORDS = {
    "excellent": "excellent",
    "needs focus": "needs_focus",
    "needs-focus": "needs_focus",
}


@dataclass
class ScorecardDraftMetric:
    """One parsed row, on its way to a human reviewer.

    `key` is OPTIONAL (ADR-475 D3): a row whose label matched nothing is kept
    with key=None rather than dropped, so the reviewer can name it or discard it
    deliberately. Typed `str` before, while the parser could already produce
    None -- the annotation said the drop could not happen and the code did it
    anyway.
    """

    key: Optional[str]
    label: str
    value: str
    flag: Optional[str] = None
    sort_order: int = 0

    @property
    def recognised(self) -> bool:
        return self.key is not None

    @property
    def is_context(self) -> bool:
        """Recognised, but not a scored metric (e.g. packages delivered)."""
        return self.key in CONTEXT_KEYS


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
            from app.core.config import settings
            # `region_name` is REQUIRED. The container sets AWS_REGION, but boto3 only
            # reads AWS_DEFAULT_REGION from the environment — so a bare
            # boto3.client("textract") raises NoRegionError, which the caller's
            # broad `except` then reports as "could not read the label".
            # Every other AWS client in the app already passes it (adp.py, email.py).
            return boto3.client("textract", region_name=settings.aws_region)
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
            # ADR-475 D3. An unrecognised row is KEPT, flagged, and shown to the
            # reviewer. It used to `continue`, so a card with rows we did not
            # know ingested "successfully" having quietly lost them -- invisible
            # by construction, because the reviewer sees a plausible card and has
            # no way to tell it is short.
            #
            # That matters most in the workflow this is actually used in:
            # management uploading many cards one at a time, where nobody
            # notices the fiftieth is missing a row.
            if key is None and not label:
                # A genuinely empty first cell is layout, not a metric.
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

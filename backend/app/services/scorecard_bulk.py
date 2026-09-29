"""Parse Amazon's DSP Overview Dashboard export (ADR-476).

One row per person per week -- exactly the grain of
`Scorecard(scope="individual", week, employee_id)` -- so a week of scorecards is
one upload rather than fifty.

TWO THINGS THE REAL FILE TAUGHT US, both about headers:

  "Sign/ Signal Violations Rate (per trip)"   a space INSIDE, after the slash
  "Delivery Associate "                       a TRAILING space, on the identity
                                              column itself

Either breaks a literal match, and the second is the more dangerous: invisible on
screen, and sitting on the column that carries the person's name. So every header
is normalised, not just the two we happened to notice -- ADR-475's lesson is that
a map built from the labels you saw fails on the next file.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from typing import Optional

from app.services.scorecard_ingestor import is_no_data

# Normalised header -> our registry key. Keys are what `_norm` produces, so the
# irregular spacing in the real file never has to be written out here.
_VALUE_COLUMNS: dict[str, str] = {
    "fico metric":                             "fico",
    "speeding event rate (per trip)":           "speeding_rate",
    "seatbelt-off rate (per trip)":             "seatbelt_rate",
    "distractions rate (per trip)":             "distractions_rate",
    "sign/ signal violations rate (per trip)":  "signsignal_rate",
    "sign/signal violations rate (per trip)":   "signsignal_rate",
    "following distance rate (per trip)":       "following_distance_rate",
    "cdf dpmo":                                 "cdf_dpmo",
    "delivery completion dpmo":                 "dc_dpmo",
    "dsb":                                      "dsb_dpmo",
    "pod":                                      "pod",
    # Named "CED Score" in the export, but it is the value column for Customer
    # Escalations Defect -- not a 0-100 contribution like the other *Score*
    # columns. Mapped explicitly so the name does not mislead the next reader.
    "ced score":                                "ces_dpmo",
    "packages delivered":                       "packages_delivered",
}

# Present in the export, deliberately not mapped: PSB (Pickup Success Behaviors)
# does not apply to AMZL, and renders "No Data" on every card we have seen.
# Named rather than silently unrecognised, so it is not reported as an unknown
# header on every single upload.
_IGNORED_COLUMNS = frozenset({
    "psb", "psb tier", "psb score", "psb weight applied",
})

# Value column -> its tier column, where the name is not derivable.
#
# Amazon is inconsistent in both directions: the rate metrics DROP "(per trip)"
# in the tier column, and "DSB" GAINS "DPMO". Deriving `f"{value} tier"` looks
# obviously correct and silently loses every rate tier, so the pairs that differ
# are written out.
_TIER_OVERRIDES: dict[str, str] = {
    "speeding event rate (per trip)":           "speeding event rate tier",
    "seatbelt-off rate (per trip)":             "seatbelt-off rate tier",
    "distractions rate (per trip)":             "distractions rate tier",
    "sign/ signal violations rate (per trip)":  "sign/ signal violations rate tier",
    "sign/signal violations rate (per trip)":   "sign/signal violations rate tier",
    "following distance rate (per trip)":       "following distance rate tier",
    "dsb":                                      "dsb dpmo tier",
    "ced score":                                "ced tier",
}


def _tier_header(value_header: str) -> str:
    return _TIER_OVERRIDES.get(value_header, f"{value_header} tier")


_IDENTITY = {"transporter id": "transporter_id",
             "delivery associate": "da_name",
             "week": "week",
             "overall standing": "overall_standing",
             "overall score": "overall_score"}


def _norm(header: str) -> str:
    """Strip, lowercase, collapse internal whitespace runs.

    Applied to EVERY header. `"Delivery Associate "` and
    `"Sign/ Signal Violations Rate (per trip)"` both come from one real file, so
    normalising only the case we noticed first would have failed on the other.
    """
    return re.sub(r"\s+", " ", (header or "").strip().lower())


def parse_value(raw: str) -> tuple[Optional[float], Optional[str]]:
    """Return (numeric value, unit) for a cell, or (None, unit) when absent.

    ABSENCE HAS TWO SPELLINGS. The export writes an empty string where the card
    UI writes "No Data" -- same meaning -- so both resolve to None here rather
    than to 0. A zero seatbelt rate is perfect; treating an absence as zero makes
    an unmeasured walker look flawless (ADR-475 D4).
    """
    if is_no_data(raw):
        return None, None
    text = raw.strip()
    unit = None
    if text.endswith("%"):
        unit, text = "%", text[:-1]
    try:
        return float(text.replace(",", "")), unit
    except ValueError:
        # A tier word or anything else non-numeric. Not a number, not an error:
        # the caller keeps the raw text.
        return None, unit


@dataclass
class BulkRow:
    week: str
    transporter_id: str
    da_name: Optional[str] = None
    overall_standing: Optional[str] = None
    # key -> {"value": str|None, "tier": str|None, "unit": str|None}
    metrics: dict[str, dict] = field(default_factory=dict)


@dataclass
class BulkParse:
    rows: list[BulkRow] = field(default_factory=list)
    # Headers we could not place. REPORTED, never ignored -- a silently unmapped
    # column is ADR-475's dropped row in a new place.
    unknown_headers: list[str] = field(default_factory=list)
    # Rows with no Transporter ID at all: they cannot be matched to anyone, and
    # discarding them quietly is the silent drop again.
    skipped_no_id: int = 0


def parse_export(content: bytes) -> BulkParse:
    """Parse the export into rows, grouped by nothing -- each row carries its own
    week.

    THE WEEK COLUMN IS THE AUTHORITY (ADR-476 D5), not the filename and not the
    first row. The file is named "Trailing Six Week" while Amazon exports weekly,
    so trusting either would write one week's numbers under another week's label
    -- an error nobody catches, because the numbers look plausible.
    """
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))

    try:
        raw_headers = next(reader)
    except StopIteration:
        return BulkParse()

    headers = [_norm(h) for h in raw_headers]
    out = BulkParse()

    seen_unknown: set[str] = set()
    for idx, h in enumerate(headers):
        if not h or h in _IDENTITY or h in _IGNORED_COLUMNS:
            continue
        if h in _VALUE_COLUMNS:
            continue
        if h.endswith((" tier", " score", " weight applied")):
            continue          # companion columns, handled beside their value
        if h not in seen_unknown:
            seen_unknown.add(h)
            out.unknown_headers.append(raw_headers[idx])

    col = {h: i for i, h in enumerate(headers)}

    for raw in reader:
        if not raw or len(raw) < 2:
            continue
        def cell(name: str) -> str:
            i = col.get(name)
            return raw[i].strip() if i is not None and i < len(raw) else ""

        tid = cell("transporter id")
        if not tid:
            out.skipped_no_id += 1
            continue

        row = BulkRow(
            week=cell("week"),
            transporter_id=tid,
            da_name=cell("delivery associate") or None,
            overall_standing=cell("overall standing") or None,
        )

        for header, key in _VALUE_COLUMNS.items():
            if header not in col:
                continue
            raw_value = cell(header)
            value, unit = parse_value(raw_value)
            # THE TIER COLUMN'S NAME IS NOT DERIVABLE FROM THE VALUE COLUMN'S.
            # "Speeding Event Rate (per trip)" pairs with "Speeding Event Rate
            # Tier" -- the "(per trip)" suffix is dropped, and "DSB" pairs with
            # "DSB DPMO Tier", which ADDS a word. Deriving it returned None for
            # every rate metric, silently: the value was right and the tier was
            # quietly lost.
            tier = cell(_tier_header(header)) or None
            # Kept even when BOTH are absent: "Amazon reported nothing for this
            # metric" is a fact worth storing, and is what lets the UI say
            # "No Data" rather than rendering a blank it cannot explain.
            row.metrics[key] = {
                "value": None if value is None else value,
                "raw": raw_value or None,
                "tier": tier,
                "unit": unit,
            }
        out.rows.append(row)

    return out

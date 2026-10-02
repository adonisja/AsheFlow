"""Free text: capped at the boundary, escaped at every sink (ADR-485 D14).

Free text is the highest-value field on a campaign and the highest-risk. Three
different failures, three different places to handle them:

    submit   -> cap and strip control characters
    export   -> escape spreadsheet formulas
    7 days   -> rewrite roster names to roles

WHY ESCAPING BELONGS AT EXPORT AND NOT AT SUBMIT
================================================

A walker who writes "-4 totes short" is recording data. Prefixing it with `'`
on the way in corrupts what they said for every reader — and the database has
readers that are not spreadsheets: this API, a trend query, the run detail
page. Only Excel and Sheets interpret a leading `=`, so only the writer
producing a file for them should defend against it (ADR-435 D10).

ONE HELPER, BECAUSE CSV AND XLSX DRIFT
======================================

They are separate code paths. `csv.writer` quotes but does not neutralise a
formula; a sheet writer emits the raw string and never sees the CSV quoter. Two
implementations means one of them is eventually missed, so there is one.
"""
from __future__ import annotations

import re

# Excel and Google Sheets execute a cell beginning with any of these. TAB, CR
# and LF are included because a leading one shifts the content into the next
# cell, where a following `=` is then at the start of a cell again.
_FORMULA_TRIGGERS = ("=", "+", "-", "@", "\t", "\r", "\n")

# Everything below 0x20 except newline and tab, plus DEL. A respondent cannot
# type these; a script can, and a NUL in a text column breaks Postgres clients
# and every downstream reader differently.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sanitise_submitted_text(value: str | None, max_length: int = 2000) -> str | None:
    """Clean free text on the way IN (ADR-115 D9).

    Caps length and removes control characters, keeping newline and tab, which
    a respondent legitimately produces by pressing Enter.

    Does NOT escape formulas — that is the export's job, and doing it here
    would rewrite what somebody said.
    """
    if value is None:
        return None
    cleaned = _CONTROL_CHARS.sub("", value).strip()
    if not cleaned:
        return None
    return cleaned[:max_length]


def escape_for_spreadsheet(value: object) -> str:
    """Neutralise a spreadsheet formula at EXPORT (ADR-435 D10).

    Prefixes with an apostrophe, which Excel and Sheets treat as "the rest is
    literal text" and do not display. NEVER strips the trigger character: a
    building genuinely named "-Riverside" is data, and a walker who wrote
    "-4 totes short" meant the minus sign.

    Every CSV and every XLSX writer must call this on every cell that can
    contain collected text. One helper so the two cannot drift.
    """
    if value is None:
        return ""
    text = str(value)
    if text.startswith(_FORMULA_TRIGGERS):
        return "'" + text
    return text

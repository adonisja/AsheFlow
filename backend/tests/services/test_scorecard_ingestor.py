"""ScorecardIngestor Textract parse (ADR-204 Phase C). Public — reuses the same
stub-client pattern as the manifest ingestor; the real AWS call is never made."""
from app.services.scorecard_ingestor import ScorecardIngestor


def _word(id_, text):
    return {"Id": id_, "BlockType": "WORD", "Text": text}


def _cell(id_, row, col, child_ids):
    return {"Id": id_, "BlockType": "CELL", "RowIndex": row, "ColumnIndex": col,
            "Relationships": [{"Type": "CHILD", "Ids": child_ids}]}


def _canned_response():
    """A minimal Textract AnalyzeDocument response for a 3-row scorecard table:
       Packages Delivered | 203 |
       Delivery Completion DPMO | 14492.7 | Needs Focus
       POD Score | 100.0% | Excellent
    plus loose LINE text for week + overall standing."""
    words = [
        _word("w-hdr1", "NYCD"), _word("w-hdr2", "SCORECARD"), _word("w-week", "2026-W28"),
        _word("w-os1", "OVERALL"), _word("w-os2", "STANDING"), _word("w-os3", "PLATINUM"),
        _word("w-l1a", "Packages"), _word("w-l1b", "Delivered"), _word("w-v1", "203"),
        _word("w-l2a", "Delivery"), _word("w-l2b", "Completion"), _word("w-l2c", "DPMO"),
        _word("w-v2", "14492.7"), _word("w-f2a", "Needs"), _word("w-f2b", "Focus"),
        _word("w-l3a", "POD"), _word("w-l3b", "Acceptance"), _word("w-l3c", "Rate"), _word("w-v3", "100.0%"), _word("w-f3", "Excellent"),
    ]
    cells = [
        _cell("c-1-1", 1, 1, ["w-l1a", "w-l1b"]), _cell("c-1-2", 1, 2, ["w-v1"]),
        _cell("c-2-1", 2, 1, ["w-l2a", "w-l2b", "w-l2c"]), _cell("c-2-2", 2, 2, ["w-v2"]),
        _cell("c-2-3", 2, 3, ["w-f2a", "w-f2b"]),
        _cell("c-3-1", 3, 1, ["w-l3a", "w-l3b", "w-l3c"]), _cell("c-3-2", 3, 2, ["w-v3"]), _cell("c-3-3", 3, 3, ["w-f3"]),
    ]
    table = {"Id": "t-1", "BlockType": "TABLE",
             "Relationships": [{"Type": "CHILD", "Ids": [c["Id"] for c in cells]}]}
    return {"Blocks": [table, *cells, *words]}


class _StubClient:
    def analyze_document(self, **_):
        return _canned_response()


def test_parses_week_overall_and_metrics():
    draft = ScorecardIngestor(b"fake-image", _textract_client=_StubClient()).parse()
    assert draft.week == "2026-W28"
    assert draft.overall_standing == "PLATINUM"

    by_key = {m.key: m for m in draft.metrics}
    assert by_key["packages_delivered"].value == "203"
    assert by_key["packages_delivered"].flag is None

    assert by_key["dc_dpmo"].value == "14492.7"
    assert by_key["dc_dpmo"].flag == "needs_focus"

    assert by_key["pod"].value == "100.0%"
    assert by_key["pod"].flag == "excellent"


def test_unknown_rows_are_surfaced_not_dropped():
    """REVERSED by ADR-475 D3, deliberately.

    This used to assert the junk row was dropped, with the comment "dropped (not
    guessed)" -- which conflated two different things. Not guessing is right; the
    row must not be silently assigned a key. Dropping is not: the reviewer then
    sees a plausible card with no way to know it is short, which is invisible by
    construction.

    It matters most in the workflow this is used in -- management uploading many
    cards one at a time, where nobody notices the fiftieth lost a row.

    So: kept, with key=None, for a human to name or discard.
    """
    resp = _canned_response()
    resp["Blocks"].append(_cell("c-9-1", 9, 1, ["w-junk"]))
    resp["Blocks"].append(_word("w-junk", "Gibberish"))
    resp["Blocks"][0]["Relationships"][0]["Ids"].append("c-9-1")

    class _S:
        def analyze_document(self, **_): return resp
    draft = ScorecardIngestor(b"x", _textract_client=_S()).parse()

    unknown = [m for m in draft.metrics if m.key is None]
    assert len(unknown) == 1, "the unrecognised row was dropped"
    assert unknown[0].label == "Gibberish"
    assert not unknown[0].recognised

    # And it is NOT guessed into a real key.
    assert all(m.key != "packages_delivered" or m.label != "Gibberish"
               for m in draft.metrics)

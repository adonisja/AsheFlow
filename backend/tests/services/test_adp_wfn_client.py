"""Workforce Now client — payload shape and response parsing (ADR-233 Phase 3).

Two things are pinned here because getting either wrong fails silently rather
than loudly:

  1. `_changeCode` must be "change". ADP's own examples use "modify" for
     hoursEntry and "change" for timePairEntry — both are valid literals, so
     sending the wrong one is not an obvious error. AsheFlow only writes
     timePairEntry.

  2. The response nests four deep and is a *team* payload. Entries belonging to
     other workers must be discarded, or a correction could be proposed against
     the wrong person's timecard.

Payloads below are shaped from ADP's published OpenAPI/JSON Schema and the
worked examples in their API Explorer.
"""
from datetime import date, datetime, timezone

import pytest

from app.services.adp import build_break_correction_payload, _index_time_entries_by_associate


AOID = "G3V2JFHYFPG9ZZVC"
PFID = "64711919N"
ENTRY = "8672975228284578|1"


def _payload():
    return build_break_correction_payload(
        associate_oid=AOID,
        work_assignment_id=PFID,
        entry_id=ENTRY,
        entry_date=date(2026, 7, 24),
        break_start_at=datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc),
        break_end_at=datetime(2026, 7, 24, 12, 30, tzinfo=timezone.utc),
    )


# ── write payload ────────────────────────────────────────────────────────────

def test_change_code_is_change_not_modify():
    """'modify' is the hoursEntry verb. Sending it for a timePairEntry is a
    valid-looking literal for the wrong entry type."""
    entry = _payload()["events"][0]["data"]["transform"]["timeEntries"][0]
    assert entry["_changeCode"] == "change"


def test_entry_type_is_time_pair():
    entry = _payload()["events"][0]["data"]["transform"]["timeEntries"][0]
    assert entry["entryTypeCode"] == {"codeValue": "timePairEntry"}


def test_single_event_keeps_the_write_synchronous():
    """>1 employee in a payload puts ADP on the async path (202 + polling).
    One event keeps the simple synchronous contract."""
    assert len(_payload()["events"]) == 1


def test_event_context_carries_both_identifiers():
    ctx = _payload()["events"][0]["data"]["eventContext"]
    assert ctx == {"associateOID": AOID, "workAssignmentID": PFID}


def test_entry_id_passes_through_verbatim():
    """ADP entry ids are opaque and inconsistently formatted ("-16", "456579",
    "8672975228284578|1"). They are never parsed or coerced."""
    entry = _payload()["events"][0]["data"]["transform"]["timeEntries"][0]
    assert entry["entryID"] == ENTRY


def test_both_period_bounds_are_tz_aware_iso():
    entry = _payload()["events"][0]["data"]["transform"]["timeEntries"][0]
    start = entry["startPeriod"]["startDateTime"]
    end = entry["endPeriod"]["endDateTime"]
    assert start == "2026-07-24T12:00:00+00:00"
    assert end == "2026-07-24T12:30:00+00:00"
    # a naive timestamp would make the correction ambiguous across DST
    assert datetime.fromisoformat(start).tzinfo is not None
    assert datetime.fromisoformat(end).tzinfo is not None


@pytest.mark.parametrize("field", ["timeDuration", "entryCode", "laborAllocations"])
def test_omits_fields_that_belong_to_other_entry_types(field):
    """timeDuration/entryCode are hoursEntry fields. laborAllocations is
    department/job coding AsheFlow does not own — echoing stale values risks
    overwriting correct ones."""
    entry = _payload()["events"][0]["data"]["transform"]["timeEntries"][0]
    assert field not in entry


def test_envelope_uses_correctly_spelled_lowercase_form():
    """ADP's hoursEntry samples carry a typo'd 'servericeCategoryCode' with
    uppercase TIME; the timePairEntry samples use the correct spelling."""
    event = _payload()["events"][0]
    assert event["serviceCategoryCode"] == {"codeValue": "time"}
    assert event["eventNameCode"] == {"codeValue": "timeEntries.modify"}
    assert "servericeCategoryCode" not in event


# ── response parsing ─────────────────────────────────────────────────────────
#
# team-time-cards is team-scoped: {aoid} is the MANAGER whose team to return, so
# one call covers every direct report. The result is indexed by associateOID so
# the caller can look up each employee, rather than re-requesting per head.

OTHER = "G-SOMEONE-ELSE"


def _team_payload(cards):
    """cards: list of (associateOID | None, [timeEntry, ...])"""
    return {
        "teamTimeCards": [
            {
                "associateOID": None,
                "timeCards": [
                    {"associateOID": oid, "dayEntries": [{"timeEntries": entries}]}
                    for oid, entries in cards
                ],
            }
        ]
    }


def test_indexes_every_team_member_from_one_response():
    """The whole point: one request yields all reports, keyed for lookup."""
    payload = _team_payload([
        (AOID, [{"entryID": "E1"}]),
        (OTHER, [{"entryID": "E2"}, {"entryID": "E3"}]),
    ])
    got = _index_time_entries_by_associate(payload)
    assert set(got) == {AOID, OTHER}
    assert [e["entryID"] for e in got[AOID]] == ["E1"]
    assert len(got[OTHER]) == 2


def test_absent_employee_simply_has_no_key():
    """No timecard that day is an absence from the mapping, not an error."""
    got = _index_time_entries_by_associate(_team_payload([(OTHER, [{"entryID": "E1"}])]))
    assert AOID not in got
    assert got.get(AOID, []) == []


def test_inner_associate_oid_wins_over_outer():
    """One team card can carry cards for several workers; the card-level id is
    the authoritative owner."""
    payload = {
        "teamTimeCards": [{
            "associateOID": OTHER,
            "timeCards": [{"associateOID": AOID, "dayEntries": [
                {"timeEntries": [{"entryID": "E1"}]}
            ]}],
        }]
    }
    got = _index_time_entries_by_associate(payload)
    assert AOID in got and OTHER not in got


def test_falls_back_to_outer_associate_oid():
    payload = {
        "teamTimeCards": [{
            "associateOID": AOID,
            "timeCards": [{"dayEntries": [{"timeEntries": [{"entryID": "E1"}]}]}],
        }]
    }
    assert AOID in _index_time_entries_by_associate(payload)


def test_drops_entries_with_no_resolvable_owner():
    """Attributing a timecard to the wrong employee would propose a payroll
    correction against the wrong person — better to drop and log."""
    payload = {"teamTimeCards": [{"timeCards": [{"dayEntries": [
        {"timeEntries": [{"entryID": "E1"}]}
    ]}]}]}
    assert _index_time_entries_by_associate(payload) == {}


def test_flattens_multiple_day_entries_for_one_worker():
    payload = {
        "teamTimeCards": [{
            "associateOID": AOID,
            "timeCards": [{
                "associateOID": AOID,
                "dayEntries": [
                    {"timeEntries": [{"entryID": "E1"}]},
                    {"timeEntries": [{"entryID": "E2"}, {"entryID": "E3"}]},
                ],
            }],
        }]
    }
    assert len(_index_time_entries_by_associate(payload)[AOID]) == 3


@pytest.mark.parametrize("payload", [
    {},
    {"teamTimeCards": []},
    {"teamTimeCards": [{"timeCards": []}]},
    {"teamTimeCards": [{"associateOID": AOID, "timeCards": [{"dayEntries": []}]}]},
    {"teamTimeCards": [{"associateOID": AOID, "timeCards": [{"dayEntries": [{}]}]}]},
    # ADP omits empty collections rather than sending []
    {"teamTimeCards": [{"associateOID": AOID, "timeCards": [{"dayEntries": [{"timeEntries": None}]}]}]},
])
def test_tolerates_missing_levels(payload):
    assert _index_time_entries_by_associate(payload) == {}

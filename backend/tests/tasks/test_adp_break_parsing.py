"""Break parsing helpers in adp_timecard_sync (ADR-233 Phase 3).

ADP's schema types these fields loosely, and two shapes bite:

  - breakTypeCode / breakStatus / overrideTypeCode are codeType_v02 *objects*.
    Reading them directly yields {"codeValue": "meal"}, not "meal" — and a dict
    compared against "meal" is silently False, which would make every break look
    untyped and defeat meal-preference in break selection.

  - startTime / endTime are timeType_v01, a bare string. Format is not
    guaranteed: ADP emits 'Z', and its own samples contain stray spaces.
"""
from datetime import datetime, timezone

import pytest

from app.tasks.adp_timecard_sync import _as_str, _code_value, _parse_adp_datetime


# ── code wrappers ────────────────────────────────────────────────────────────

def test_unwraps_code_value_object():
    assert _code_value({"codeValue": "meal", "shortName": "Meal"}) == "meal"


def test_tolerates_bare_string():
    assert _code_value("meal") == "meal"


@pytest.mark.parametrize("node", [None, {}, {"shortName": "Meal"}])
def test_returns_none_when_no_code_value(node):
    assert _code_value(node) is None


def test_does_not_return_the_dict_itself():
    """Regression: returning the wrapper makes `code == "meal"` silently False."""
    got = _code_value({"codeValue": "meal"})
    assert isinstance(got, str)


# ── identifiers ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("8672975228284578|1", "8672975228284578|1"),   # pipe-suffixed composite
    ("-16", "-16"),                                  # negative placeholder
    (456579, "456579"),                              # ADP sometimes sends ints
])
def test_ids_pass_through_as_strings(raw, expected):
    assert _as_str(raw) == expected


def test_none_id_stays_none():
    assert _as_str(None) is None


# ── timestamps ───────────────────────────────────────────────────────────────

def test_parses_z_suffix():
    """fromisoformat rejects 'Z' before Python 3.11."""
    assert _parse_adp_datetime("2026-07-24T12:00:00Z") == datetime(
        2026, 7, 24, 12, 0, tzinfo=timezone.utc
    )


def test_parses_explicit_offset():
    got = _parse_adp_datetime("2026-07-24T09:00:00-07:00")
    assert got.utcoffset().total_seconds() == -7 * 3600


def test_strips_stray_spaces_in_adp_samples():
    """ADP's own docs contain "2024-06-07T09: 00: 00-0700"."""
    got = _parse_adp_datetime("2024-06-07T09: 00: 00-07:00")
    assert got is not None
    assert got.hour == 9


def test_naive_timestamp_is_assumed_utc():
    """Break times are compared against tz-aware Flex records; a naive value
    would raise on comparison."""
    got = _parse_adp_datetime("2026-07-24T12:00:00")
    assert got.tzinfo is not None
    assert got.utcoffset().total_seconds() == 0


@pytest.mark.parametrize("bad", [None, "", "not-a-time", "12:00", 12345])
def test_unparseable_yields_none_rather_than_raising(bad):
    """One malformed timestamp must not abort a whole company's sync."""
    assert _parse_adp_datetime(bad) is None


# ── fetch volume ─────────────────────────────────────────────────────────────

def test_fetch_is_per_manager_not_per_employee():
    """Regression (ADR-233): the first Phase 3 draft called team-time-cards once
    per employee, passing each walker's own AOID as {aoid}. The endpoint is
    team-scoped — {aoid} is the manager whose team to return — so that was one
    request per head, each asking for the team reporting to a walker.

    Two managers and 50 walkers must produce two calls, not 52.
    """
    import uuid
    from unittest.mock import MagicMock, patch
    from app.models.adp_integration import ADPIntegration
    from app.tasks import adp_timecard_sync as m

    company_id = uuid.uuid4()
    integ = MagicMock()
    integ.company_id = company_id
    integ.is_enabled = True

    manager_oids = ["MGR-1", "MGR-2"]
    calls = []

    def _fetch(_integration, manager_oid, _work_date):
        calls.append(manager_oid)
        return {}

    db = MagicMock()

    def _query(model, *a, **k):
        q = MagicMock()
        if model is ADPIntegration:
            q.filter.return_value.all.return_value = [integ]
        else:
            q.filter.return_value.all.return_value = []      # no employees
            q.filter.return_value.first.return_value = None
        return q
    db.query = _query

    with patch.object(m, "SessionLocal", return_value=db), \
         patch.object(m, "fetch_company_timezones", return_value={}), \
         patch.object(m, "_team_manager_oids", return_value=manager_oids), \
         patch.object(m, "fetch_adp_team_timecards", side_effect=_fetch):
        m.sync_adp_timecards()

    assert calls == manager_oids


def test_one_manager_failing_does_not_block_the_others():
    """A single unreachable team must not cost the company its whole sync."""
    import uuid
    from unittest.mock import MagicMock, patch
    from app.models.adp_integration import ADPIntegration
    from app.tasks import adp_timecard_sync as m

    integ = MagicMock()
    integ.company_id = uuid.uuid4()
    integ.is_enabled = True

    seen = []

    def _fetch(_integration, manager_oid, _work_date):
        seen.append(manager_oid)
        if manager_oid == "MGR-1":
            raise RuntimeError("ADP unreachable")
        return {}

    db = MagicMock()

    def _query(model, *a, **k):
        q = MagicMock()
        if model is ADPIntegration:
            q.filter.return_value.all.return_value = [integ]
        else:
            q.filter.return_value.all.return_value = []
            q.filter.return_value.first.return_value = None
        return q
    db.query = _query

    with patch.object(m, "SessionLocal", return_value=db), \
         patch.object(m, "fetch_company_timezones", return_value={}), \
         patch.object(m, "_team_manager_oids", return_value=["MGR-1", "MGR-2"]), \
         patch.object(m, "fetch_adp_team_timecards", side_effect=_fetch):
        out = m.sync_adp_timecards()

    assert seen == ["MGR-1", "MGR-2"]     # second manager still attempted
    assert out == {"status": "ok"}

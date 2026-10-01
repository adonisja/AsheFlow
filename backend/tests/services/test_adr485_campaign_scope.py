"""Who may answer about whom (ADR-485 D3/D4).

    A response is valid only if respondent and subject shared ONE assignment
    on the RUN's date.

Everything the user specified falls out of that: no cross-truck contamination,
no cross-date contamination, no retroactive access, and nobody reviews
themselves.

These tests compile the SQL rather than only running it. The bug that prompted
them is invisible to a passing query: re-aliasing the subject in
`may_answer_about` produced a SECOND, unconstrained `assignment_members` in the
FROM clause -- `FROM assignment_members AS s, assignment_members AS s` -- which
is valid SQL, returns rows, and lets a respondent answer about anyone in the
company. Only the compiled statement shows it.
"""
import datetime
import re
import uuid
from unittest.mock import MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from app.models.campaign import Campaign, CampaignRun
from app.services import campaign_scope as cs

COMPANY = uuid.uuid4()
# Deliberately NOT today: a fixture date that happens to be today makes
# "did it bind the run's date, or today's?" unanswerable, and a probe
# swapping run.date for date.today() passes.
RUN_DATE = datetime.date(2019, 3, 14)


@pytest.fixture(autouse=True)
def _no_db_for_cutoff(monkeypatch):
    """_transfer_cutoff hits the DB; these tests are about the SQL shape."""
    monkeypatch.setattr(cs, "_transfer_cutoff", lambda *a, **k: None)


def _sql(subject_role="driver"):
    run = CampaignRun(company_id=COMPANY, date=RUN_DATE, campaign_id=uuid.uuid4())
    camp = Campaign(subject_role=subject_role, company_id=COMPANY)
    query, _ = cs._base_query(MagicMock(), run, camp, uuid.uuid4())
    return str(query.compile(dialect=postgresql.dialect()))


def _captured(fn_name, **kwargs):
    """Compile the SQL the REAL function emits, by capturing db.execute().

    An earlier version of this file re-implemented `may_answer_about`'s
    narrowing by hand and asserted on that -- so it passed whether or not the
    function did the same thing, and a probe that re-introduced the live alias
    bug did not fire. The test was testing itself.
    """
    captured = {}

    class _DB:
        def execute(self, stmt):
            captured["sql"] = str(stmt.compile(dialect=postgresql.dialect()))
            captured["params"] = stmt.compile(dialect=postgresql.dialect()).params

            class _R:
                def all(self_inner): return []
                def first(self_inner): return None
            return _R()

    run = CampaignRun(company_id=COMPANY, date=RUN_DATE, campaign_id=uuid.uuid4())
    camp = Campaign(subject_role="driver", company_id=COMPANY)
    getattr(cs, fn_name)(_DB(), run, camp, uuid.uuid4(), **kwargs)
    return captured


# ── the self-join is exactly two aliases ────────────────────────────────────

def test_the_subject_table_appears_exactly_once():
    """THE bug. A second unconstrained alias is a cartesian join and a silent
    authorisation hole."""
    assert _sql().count("assignment_members AS s") == 1


def test_may_answer_about_does_not_add_a_second_alias():
    """THE live bug, tested through the REAL function.

    `may_answer_about` must reuse the builder's subject alias. Re-aliasing adds
    `FROM assignment_members AS s, assignment_members AS s` -- valid SQL, rows
    returned, and a respondent may answer about anyone in the company."""
    sql = _captured("may_answer_about", subject_id=uuid.uuid4())["sql"]
    assert sql.count("assignment_members AS s") == 1
    assert sql.count("assignment_members AS r") == 1


def test_subjects_for_emits_the_same_join():
    sql = _captured("subjects_for")["sql"]
    assert sql.count("assignment_members AS s") == 1
    assert sql.count("assignment_members AS r") == 1


def test_the_respondent_table_appears_exactly_once():
    assert _sql().count("assignment_members AS r") == 1


def test_both_rows_are_joined_on_the_SAME_assignment():
    """This single predicate is what makes cross-truck contamination
    impossible -- there is no assignment containing both crews."""
    assert re.search(r"r\.assignment_id\s*=\s*s\.assignment_id", _sql())


# ── the three isolation guarantees ──────────────────────────────────────────

def test_it_scopes_to_the_runs_date_not_today():
    """A run opened late, read late or answered late still asks about the day
    it was about.

    Asserts the BOUND VALUE, not just the shape: `date == date.today()` also
    compiles to `truck_assignments.date = %(date_1)s`, so checking the SQL text
    alone cannot tell the two apart."""
    cap = _captured("subjects_for")
    assert "truck_assignments.date = " in cap["sql"]
    assert RUN_DATE in cap["params"].values(), (
        f"the bound date is not the run's: {cap['params']}")
    assert datetime.date.today() not in cap["params"].values(), (
        "today's date is bound somewhere — the run's date is being ignored")


def test_nobody_reviews_themselves():
    assert re.search(r"s\.employee_id\s*!=\s*r\.employee_id", _sql())


def test_the_subject_must_hold_the_campaigns_slot():
    assert "s.role = " in _sql()


# ── ADR-115 D1: every table carries its own company_id ──────────────────────

@pytest.mark.parametrize("table", ["truck_assignments", "r", "s"])
def test_every_joined_table_is_company_scoped(table):
    """The join alone would confine this, but 'it is implied by the join' is
    the reasoning that produces a cross-tenant read the next time someone
    edits the FROM clause."""
    assert f"{table}.company_id = " in _sql()


# ── D16: the role is a parameter, not a branch ──────────────────────────────

def test_driver_and_captain_compile_to_identical_sql():
    """One query serves every subject role, so a third needs no new code."""
    assert _sql("driver") == _sql("captain")


# ── D4: the transfer boundary ───────────────────────────────────────────────

def test_the_boundary_is_the_same_three_hours_the_survey_gate_uses():
    """Not a new number -- the same threshold activate_survey already uses to
    decide a survey may be sent. One boundary, one meaning."""
    assert cs.TRANSFER_COUNTS_AFTER == datetime.timedelta(hours=3)


def test_without_a_configured_shift_start_only_active_members_count(monkeypatch):
    """The boundary is unknowable, so a transferred member is EXCLUDED rather
    than guessed at: a response attributed to the wrong truck is worse than a
    response not collected."""
    monkeypatch.setattr(cs, "_transfer_cutoff", lambda *a, **k: None)
    sql = _sql()
    assert "r.status = " in sql
    assert "departed_at" not in sql


def test_with_a_boundary_a_late_transfer_is_included(monkeypatch):
    """After 3h they genuinely worked under that subject, so they answer about
    both trucks."""
    cutoff = datetime.datetime(2026, 10, 1, 11, 0, tzinfo=datetime.timezone.utc)
    monkeypatch.setattr(cs, "_transfer_cutoff", lambda *a, **k: cutoff)
    sql = " ".join(_sql().split())
    assert "r.departed_at >= " in sql
    # The status VALUE is a bound parameter, not a literal -- so assert the
    # shape (an OR between two status tests) rather than the word
    # "transferred", which correctly never appears in the SQL.
    assert "r.status = " in sql and " OR r.status = " in sql


# ── the two projections cannot drift ────────────────────────────────────────

def test_both_public_functions_build_from_the_same_query():
    """A list that offers a subject the submit path then refuses is a bug the
    user sees; a submit path laxer than the list is a bug nobody sees."""
    import inspect
    for fn in (cs.subjects_for, cs.may_answer_about):
        assert "_base_query(" in inspect.getsource(fn), f"{fn.__name__} builds its own query"

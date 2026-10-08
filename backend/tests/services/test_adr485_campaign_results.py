"""Reading what a campaign collected (ADR-485 D15).

The property that matters most is ANONYMITY, and it is asserted against the
compiled SQL rather than the response model: a query that fetches
`respondent_id` and trusts a caller to drop it is one careless serialisation
away from leaking who said what about a colleague. D13 makes attribution an
approved, audited exception; until that ships there is no way to see it at all.
"""
import ast
import datetime
import inspect
import textwrap
import uuid

import pytest
from sqlalchemy.dialects import postgresql

from app.models.campaign import CampaignRun
from app.routers import campaigns as C
from app.services import campaign_results as R

RUN = CampaignRun(id=uuid.uuid4(), company_id=uuid.uuid4(),
                  date=datetime.date(2019, 3, 14), notified_count=23)


def _code(fn) -> str:
    """Source with docstrings and comments stripped.

    Asserting "respondent" is absent from a function whose DOCSTRING explains
    why there is no respondent_id fails on correct code. Sixth prose-not-code
    match in this body of work: strip the prose before matching on source.
    """
    src = inspect.getsource(fn)
    tree = ast.parse(textwrap.dedent(src))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
                             ast.Module)) and ast.get_docstring(node):
            node.body = node.body[1:]
    return ast.unparse(tree)


def _answers_sql() -> str:
    return " ".join(
        str(R._answers_for_run(None, RUN).compile(dialect=postgresql.dialect())).split()
    )


# ── anonymity is structural ─────────────────────────────────────────────────

def test_the_answer_query_never_selects_the_respondent():
    """THE property. Not filtered out later — absent from the SELECT."""
    sql = _answers_sql()
    assert "respondent_id" not in sql
    assert "respondent" not in sql


def test_the_answer_query_never_joins_a_person():
    """Joining employees would put a name one column away from an answer."""
    assert "employees" not in _answers_sql()


def test_free_text_comes_back_unattributed():
    """The highest-risk field: a verbatim complaint beside a name is the thing
    D13 exists to gate."""
    src = _code(R.free_text)
    assert "respondent" not in src
    assert "_answers_for_run(" in src, "free_text must reuse the anonymous base"


def test_the_free_text_response_model_has_no_author_field():
    assert set(C.FreeTextOut.model_fields) == {"prompt", "text"}


def test_only_two_functions_name_a_person_and_both_are_justified():
    """`non_respondents` names who to chase; `subject_rollups` names the person
    the run is ABOUT. Neither carries answer content, which is what D13 gates.
    Any third function reaching for Employee.name is a leak."""
    naming = {
        name for name, fn in vars(R).items()
        if callable(fn) and not name.startswith("_")
        and getattr(fn, "__module__", "") == R.__name__
        and "Employee.name" in _code(fn)
    }
    assert naming == {"non_respondents", "subject_rollups"}, naming


def test_subject_rollups_names_only_the_SUBJECT():
    """The person being reviewed is not anonymous — the whole run is about
    them. The respondents are."""
    src = _code(R.subject_rollups)
    assert "CampaignResponse.subject_id" in src
    assert "respondent_id" not in src


# ── ADR-115 D1: company scoping on every table ──────────────────────────────

def test_the_answer_query_scopes_every_joined_table():
    sql = _answers_sql()
    for table in ("campaign_responses", "campaign_answers", "campaign_questions"):
        assert f"{table}.company_id = " in sql, f"{table} is unscoped"


@pytest.mark.parametrize("fn", [R.question_rollups, R.subject_rollups,
                                R.response_rate, R.non_respondents,
                                R.campaign_trend], ids=lambda f: f.__name__)
def test_every_result_function_is_company_scoped(fn):
    """`free_text` is excluded deliberately: it inherits all three company_id
    predicates from `_answers_for_run` and adds no WHERE of its own, so a
    source-text check reports it unscoped while the SQL is correct. The
    compiled query is the thing that matters, and
    test_the_answer_query_scopes_every_joined_table asserts it."""
    assert "company_id" in _code(fn), f"{fn.__name__} is unscoped"


# ── the numbers ─────────────────────────────────────────────────────────────

def test_the_rate_returns_both_numbers():
    """`17 / 23` tells a manager whether to chase; `74%` does not."""
    import typing
    hints = typing.get_type_hints(R.response_rate)
    assert hints["return"] == tuple[int, int]


def test_the_denominator_is_what_the_run_recorded_at_open():
    """A crew change afterwards must not move the denominator under a number
    somebody already read."""
    assert "run.notified_count" in inspect.getsource(R.response_rate)


def test_the_expected_set_comes_from_the_scoping_invariant():
    """Computing it any other way gives a denominator that disagrees with who
    was actually asked (D3/D4)."""
    src = inspect.getsource(R._expected_per_subject)
    assert "respondents_for(" in src and "subjects_for(" in src


def test_a_rate_is_withheld_below_the_minimum():
    """ADR-473: a metric computed from two responses reads as a judgement and
    is noise. Show the count instead."""
    assert R.MIN_RESPONSES_FOR_A_RATE >= 3
    assert "MIN_RESPONSES_FOR_A_RATE" in inspect.getsource(R.campaign_trend)


def test_choice_counts_are_index_aligned():
    """Storing the option INDEX means a renamed option cannot shift a past
    count onto a different label (D2)."""
    src = inspect.getsource(R.question_rollups)
    assert "option_counts[v] += 1" in src
    assert "0 <= v < width" in src, "an out-of-range index must not corrupt the counts"


# ── the endpoints ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("fn", [C.run_results, C.campaign_trend_endpoint],
                         ids=lambda f: f.__name__)
def test_results_endpoints_are_management_only(fn):
    """D5 is unconditional: the subject never sees responses about them, and
    that has to be the gate rather than the UI."""
    src = inspect.getsource(fn)
    assert "allow_management" in src
    assert "caller.company_id" in src


def test_run_results_separates_anonymous_answers_from_named_chasing():
    """Two different disclosure rules in one response, and the field names say
    which is which."""
    fields = set(C.RunDetailOut.model_fields)
    assert "free_text" in fields and "not_answered" in fields


def test_option_labels_are_resolved_at_read_time():
    """The counts are index-aligned; the labels come from the live question
    row, so the client renders names without a second round trip."""
    assert "choices=(questions[r.question_id].choices" in inspect.getsource(C.run_results)

"""Campaign endpoints (ADR-485 D5/D6/D7).

Source-level checks on the router's shape. The endpoints live behind
get_caller_employee and a real DB session, and the repo has no HTTP harness for
tenant-scoped routes, so what is pinned here is the SHAPE that must not
regress: the gates, the scoping call, the error codes, and the audit writes.

The scoping invariant itself is exercised in test_adr485_campaign_scope.py,
which compiles the SQL the real functions emit.
"""
import inspect
import re

import pytest

from app.routers import campaigns as C


def _src(fn) -> str:
    return inspect.getsource(fn)


# ── D7: who may design and activate ─────────────────────────────────────────

@pytest.mark.parametrize("fn", [
    C.create_campaign, C.list_campaigns, C.open_run, C.close_run, C.list_runs,
], ids=lambda f: f.__name__)
def test_management_endpoints_carry_the_gate(fn):
    assert "allow_management" in _src(fn), f"{fn.__name__} is ungated"


def test_the_gate_is_management_and_admin():
    """Same gate as the driver survey it replaces. Admins always have full
    access — never management-only."""
    src = inspect.getsource(C)
    assert 'RoleChecker(["management", "admin"])' in src


# ── D3: the field endpoints are gated by the INVARIANT, not a role list ─────

@pytest.mark.parametrize("fn", [C.my_open_runs, C.submit_response],
                         ids=lambda f: f.__name__)
def test_field_endpoints_have_no_role_gate(fn):
    """The old survey gated on ["trainer", "walker"], which excluded every
    driver from ever responding about anyone and never excluded the subject
    from their own review. Who may answer is a scoping question."""
    assert "allow_management" not in _src(fn)
    assert "RoleChecker" not in _src(fn)


def test_submit_rechecks_eligibility_server_side():
    """The client NAMES a subject; the server decides. Trusting the list the
    client was shown is trusting the client."""
    assert "may_answer_about(" in _src(C.submit_response)


def test_my_open_uses_the_same_scoping_service():
    assert "subjects_for(" in _src(C.my_open_runs)


def test_an_ineligible_subject_is_404_not_403():
    """403 confirms the run exists and that someone else was asked, which is a
    disclosure when the subject is a colleague."""
    src = _src(C.submit_response)
    block = src[src.index("may_answer_about("):]
    assert "HTTP_404_NOT_FOUND" in block
    assert "HTTP_403" not in block


# ── ADR-115 D1: every query is company-scoped ───────────────────────────────

@pytest.mark.parametrize("fn", [
    C.create_campaign, C.list_campaigns, C.open_run, C.close_run,
    C.list_runs, C.my_open_runs, C.submit_response,
], ids=lambda f: f.__name__)
def test_every_endpoint_scopes_to_the_callers_company(fn):
    assert "caller.company_id" in _src(fn), f"{fn.__name__} is not tenant-scoped"


def test_the_helpers_are_scoped_too():
    """An inner lookup that omits company_id is the shape that leaks."""
    for fn in (C._get_campaign, C._get_run, C._live_questions, C._truck_name):
        assert "company_id" in _src(fn), f"{fn.__name__} is unscoped"


# ── ADR-115 D2: one-way stamps are 409-guarded ──────────────────────────────

def test_closing_a_closed_run_is_409():
    src = _src(C.close_run)
    assert "closed_at is not None" in src and "HTTP_409_CONFLICT" in src


def test_a_second_run_for_the_same_date_is_409():
    """D1: the same campaign cannot run twice for one day. The DB enforces it;
    the router makes it readable."""
    assert "HTTP_409_CONFLICT" in _src(C.open_run)


# ── the flush-audit-commit sequence (CLAUDE.md) ─────────────────────────────

@pytest.mark.parametrize("fn", [C.create_campaign, C.open_run, C.close_run,
                                C.submit_response], ids=lambda f: f.__name__)
def test_write_endpoints_audit_before_commit(fn):
    """driver_surveys imported write_audit and never called it, so activating a
    survey left no trail at all."""
    src = _src(fn)
    assert "write_audit(" in src, f"{fn.__name__} writes without an audit row"
    assert src.index("write_audit(") < src.rindex("db.commit()"), \
        f"{fn.__name__} audits after committing"


def test_the_audit_row_does_not_copy_the_answers():
    """An audit row records that something happened. Copying a colleague
    review into it puts the content somewhere D13's attribution gate does not
    reach."""
    src = _src(C.submit_response)
    after = src[src.index("write_audit("):src.index("db.commit()", src.index("write_audit("))]
    assert "answers" not in after
    assert "bool_value" not in after and "text_value" not in after


# ── ADR-115 D9: typed request bodies ────────────────────────────────────────

@pytest.mark.parametrize("model", [C.QuestionIn, C.CampaignIn, C.RunIn,
                                   C.AnswerIn, C.ResponseIn],
                         ids=lambda m: m.__name__)
def test_request_models_forbid_unknown_keys(model):
    assert model.model_config.get("extra") == "forbid", \
        f"{model.__name__} silently accepts unknown keys"


def test_no_request_field_is_untyped():
    """No Any, no bare dict, at the trust boundary."""
    src = inspect.getsource(C)
    boundary = src[:src.index("# ----", src.index("class ResponseIn"))]
    assert not re.search(r":\s*(Any|dict|Dict)\b", boundary)


def test_free_text_and_lists_are_bounded():
    """Every free-text field capped, every list capped (ADR-115 D9)."""
    assert C.AnswerIn.model_fields["text_value"].metadata, "text_value is uncapped"
    assert C.ResponseIn.model_fields["answers"].metadata, "answers list is uncapped"
    assert C.CampaignIn.model_fields["questions"].metadata, "questions list is uncapped"


# ── D2: answers validated against THEIR OWN question ────────────────────────

def test_each_answer_is_checked_against_its_question():
    """Not against the shape that arrived — a client can send anything."""
    src = _src(C._validate_answers)
    assert "questions.get(a.question_id)" in src
    for kind in ("bool", "scale", "choice", "text"):
        assert f'"{kind}"' in src, f"{kind} answers are unvalidated"


def test_a_required_question_cannot_be_skipped():
    assert "missing" in _src(C._validate_answers)


def test_a_question_answered_twice_is_rejected():
    """The DB's uq_campaign_answer would reject it as an IntegrityError the
    operator cannot read."""
    assert "answered twice" in _src(C._validate_answers)


def test_the_value_column_is_chosen_by_the_questions_kind():
    """A bool answer must not land in int_value because the client said so."""
    src = _src(C.submit_response)
    assert 'q.kind == "bool"' in src and 'q.kind == "text"' in src


# ── D6: what a field user is shown ──────────────────────────────────────────

def test_an_open_run_carries_its_date_and_truck():
    """A daily campaign routinely has two runs open at once (D12). Two entries
    reading "Driver Survey" with no date is the one confusion this design can
    still produce."""
    fields = set(C.OpenRunOut.model_fields)
    assert {"date", "truck_name", "subject_name", "closes_at"} <= fields


def test_my_open_reports_whether_it_is_already_answered():
    """Without it the list cannot distinguish "to do" from "done", and a
    respondent re-opens a form they already submitted."""
    assert "answered" in C.OpenRunOut.model_fields


def test_a_closed_run_refuses_a_late_submission():
    src = _src(C.submit_response)
    assert "_is_open(" in src and "HTTP_409_CONFLICT" in src


# ── D16: a run nobody can answer does not open ──────────────────────────────

def test_opening_a_run_with_no_eligible_respondents_is_refused():
    """An open run that could never collect a response is indistinguishable,
    on the results page, from one everybody ignored."""
    src = _src(C.open_run)
    assert "if not respondents:" in src and "HTTP_409_CONFLICT" in src


def test_a_run_records_who_was_asked_and_what_was_skipped():
    src = _src(C.open_run)
    assert "notified_count" in src and "skipped_assignment_ids" in src
    assert "assignments_without_a_subject(" in src


# ── D18: dates are company-local ────────────────────────────────────────────

def test_the_run_window_is_built_in_company_time():
    """A naive UTC relabel here would close a New York run at 8pm (ADR-486)."""
    src = _src(C.open_run)
    assert "company_datetime(" in src and "company_tz(" in src
    assert "replace(tzinfo=timezone.utc)" not in src

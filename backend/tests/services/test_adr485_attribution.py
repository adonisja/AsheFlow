"""Unlocking who said what, by approved request (ADR-485 D13).

Anonymous by default; a manager requests, an ADMIN approves, and the grant
expires. A self-serve reveal would be anonymity in name only — a manager who
can click through whenever they like is a manager respondents must assume is
reading their name.

The tests that matter are the refusals, because the failure mode here is
silent: an unlock that works when it should not produces no error, no alert,
and a colleague's name beside their review.
"""
import ast
import datetime
import inspect
import pathlib
import textwrap
import uuid
from unittest.mock import MagicMock

import pytest

from app.models.campaign import AttributionRequest, CampaignRun
from app.models.employee import Employee
from app.routers import campaigns as C
from app.services import campaign_attribution as A

ROOT = pathlib.Path(__file__).resolve().parents[3]
COMPANY = uuid.uuid4()


def _code(fn) -> str:
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.Module)) \
                and ast.get_docstring(node):
            node.body = node.body[1:]
    return ast.unparse(tree)


def _emp(**kw):
    return Employee(id=kw.pop("id", uuid.uuid4()), company_id=COMPANY,
                    name=kw.pop("name", "Someone"), **kw)


def _req(**kw):
    return AttributionRequest(
        id=kw.pop("id", uuid.uuid4()), company_id=COMPANY,
        run_id=kw.pop("run_id", uuid.uuid4()),
        requested_by=kw.pop("requested_by", uuid.uuid4()),
        reason=kw.pop("reason", "x " * 12), **kw)


# ── the reason has to say something ─────────────────────────────────────────

def test_a_short_reason_is_refused():
    """"Following up" is three words. Ten is the smallest bar that forces an
    actual sentence about an actual situation."""
    run = CampaignRun(id=uuid.uuid4(), company_id=COMPANY)
    with pytest.raises(A.AttributionError) as e:
        A.request_attribution(MagicMock(), run, _emp(), "following up")
    assert e.value.status == 422


def test_the_word_count_is_words_not_characters():
    """A 200-character single word is not a reason."""
    assert A.reason_word_count("a" * 200) == 1
    assert A.reason_word_count("one two three four five six seven eight nine ten") == 10


def test_the_minimum_is_ten_words():
    assert A.MIN_REASON_WORDS == 10


# ── only an admin approves, and never their own ─────────────────────────────

def test_you_cannot_approve_your_own_request():
    """An admin who can approve their own request is a single-party unlock
    with two columns."""
    me = _emp()
    req = _req(requested_by=me.id)
    with pytest.raises(A.AttributionError) as e:
        A.approve(MagicMock(), req, me)
    assert e.value.status == 403


def test_approval_is_gated_to_admin_not_management():
    """Narrower than every other management endpoint here, deliberately."""
    src = _code(C.approve_attribution)
    assert "allow_admin_only" in src
    assert "allow_management" not in src


def test_denial_is_gated_the_same_way():
    assert "allow_admin_only" in _code(C.deny_attribution)


def test_the_admin_gate_is_admin_alone():
    src = inspect.getsource(C)
    assert 'RoleChecker(["admin"])' in src


# ── one-way stamps, 409-guarded ─────────────────────────────────────────────

@pytest.mark.parametrize("field", ["approved_at", "denied_at"])
def test_a_decided_request_cannot_be_decided_again(field):
    req = _req(**{field: datetime.datetime.now(datetime.timezone.utc)})
    for fn in (A.approve, A.deny):
        with pytest.raises(A.AttributionError) as e:
            fn(MagicMock(), req, _emp())
        assert e.value.status == 409


# ── the grant expires ───────────────────────────────────────────────────────

def test_the_window_is_short_and_fixed():
    """A tenant-tunable window would be set to a year by the first operator
    who found re-requesting annoying."""
    assert A.APPROVAL_WINDOW == datetime.timedelta(hours=48)


def test_approval_sets_an_expiry():
    src = _code(A.approve)
    assert "expires_at" in src and "APPROVAL_WINDOW" in src


def test_the_grant_is_checked_at_read_time_every_time():
    """An approval that has expired is not a grant."""
    src = _code(A.active_grant)
    assert "expires_at >" in src
    assert "approved_at.isnot(None)" in src
    assert "denied_at.is_(None)" in src


def test_a_grant_belongs_to_the_requester_not_the_run():
    """Another manager's approval is not this viewer's."""
    assert "requested_by == viewer.id" in _code(A.active_grant)


# ── reading is itself an event ──────────────────────────────────────────────

def test_viewing_an_unlocked_run_writes_its_own_audit_row():
    """An approval nobody acted on and one read eleven times are different
    events, and only the audit can tell them apart."""
    src = _code(A.attributed_responses)
    assert "attribution_viewed" in src


def test_reading_without_a_grant_RAISES(monkeypatch):
    """THE gate. Exercised, not inspected.

    An earlier version of this test asserted only that `active_grant(` appeared
    before `select(` in the source. A probe that neutered the refusal --
    `if grant is None:` -> `if False:` -- left that ordering intact and the test
    passed, which is the whole gate silently removed."""
    monkeypatch.setattr(A, "active_grant", lambda *a, **k: None)
    run = CampaignRun(id=uuid.uuid4(), company_id=COMPANY)
    with pytest.raises(A.AttributionError) as e:
        A.attributed_responses(MagicMock(), run, _emp())
    assert e.value.status == 403


def test_a_refused_read_queries_nothing_and_audits_nothing(monkeypatch):
    """The refusal must come before the work, or a denied viewer still
    generates a read that looks like an authorised one in the logs."""
    monkeypatch.setattr(A, "active_grant", lambda *a, **k: None)
    db = MagicMock()
    run = CampaignRun(id=uuid.uuid4(), company_id=COMPANY)
    with pytest.raises(A.AttributionError):
        A.attributed_responses(db, run, _emp())
    db.execute.assert_not_called()
    db.add.assert_not_called()


def test_a_granted_read_returns_rows_and_audits(monkeypatch):
    """The other half: with a live grant it must actually work."""
    grant = _req(approved_at=datetime.datetime.now(datetime.timezone.utc))
    monkeypatch.setattr(A, "active_grant", lambda *a, **k: grant)
    audited = {}
    monkeypatch.setattr(A, "write_audit",
                        lambda **kw: audited.update(kw))
    db = MagicMock()
    db.execute.return_value.all.return_value = [
        (uuid.uuid4(), "Dev", uuid.uuid4())]
    run = CampaignRun(id=uuid.uuid4(), company_id=COMPANY)
    rows = A.attributed_responses(db, run, _emp())
    assert len(rows) == 1
    assert audited["action_type"] == "campaign.attribution_viewed"


def test_the_view_endpoint_commits_so_the_audit_row_survives():
    """Rolling back a read would discard the only record that it happened."""
    assert "db.commit()" in _code(C.attributed_run)


@pytest.mark.parametrize("fn", [A.request_attribution, A.approve, A.deny,
                                A.attributed_responses],
                         ids=lambda f: f.__name__)
def test_every_step_is_audited(fn):
    assert "write_audit(" in _code(fn)


def test_the_approval_audit_names_both_parties():
    """"Who saw this, and who let them" must have one answer without joining
    three tables."""
    src = _code(A.approve)
    assert "requested_by" in src and "actor_id=str(approver.id)" in src


def test_a_denial_is_audited_too():
    """A denial that leaves no trace makes "nobody asked" and "somebody was
    told no" look identical later."""
    assert "attribution_denied" in _code(A.deny)


# ── this is the only door ───────────────────────────────────────────────────

def test_only_one_function_pairs_a_respondent_with_their_answer():
    """THE property, stated precisely.

    `respondent_id` appears in campaign_results three times and all three are
    legitimate: twice inside count(distinct(...)) for the response rate, and
    once in `non_respondents`, which fetches who answered only to SUBTRACT them
    and returns the complement. None of those pairs an identity with answer
    content.

    A blunter version of this test — "respondent_id appears nowhere" — failed
    on that correct code. The leak is a JOIN from an answer to a person, not
    the column's presence."""
    attributed = _code(A.attributed_responses)
    assert "Employee.name" in attributed and "respondent_id" in attributed

    results = (ROOT / "backend/app/services/campaign_results.py").read_text()
    tree = ast.parse(results)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            body = ast.unparse(node)
            pairs_identity_with_answers = (
                "respondent_id" in body
                and "Employee.name" in body
                and node.name != "non_respondents"
            )
            assert not pairs_identity_with_answers, (
                f"campaign_results.{node.name} joins a respondent to a name")


def test_the_results_surface_still_returns_nothing_attributed():
    """D15 is unchanged by this: the default read stays anonymous."""
    assert set(C.FreeTextOut.model_fields) == {"prompt", "text"}


def test_d5_is_untouched():
    """The SUBJECT never sees responses about them, approved or not. Every
    attribution endpoint is gated to management or admin, so a subject with a
    field role cannot reach any of them."""
    for fn in (C.attributed_run, C.request_attribution_endpoint,
               C.approve_attribution, C.deny_attribution):
        src = _code(fn)
        assert "allow_management" in src or "allow_admin_only" in src


# ── tenant scoping ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("fn", [A.request_attribution, A.active_grant,
                                A.attributed_responses],
                         ids=lambda f: f.__name__)
def test_every_query_is_company_scoped(fn):
    assert "company_id" in _code(fn)

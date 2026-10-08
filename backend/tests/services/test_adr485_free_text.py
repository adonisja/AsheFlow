"""Free text: capped, escaped, name-flagged, redacted (ADR-485 D14).

Four constraints for four different failures. The redaction one is exercised
rather than inspected: it rewrites rows irreversibly, so a bug in the matcher
destroys sentences permanently and there is nothing to restore from.
"""
import ast
import datetime
import inspect
import pathlib
import re
import textwrap
import uuid
from unittest.mock import MagicMock

import pytest

from app.models.employee import Employee
from app.services.free_text import escape_for_spreadsheet, sanitise_submitted_text
from app.tasks import campaign_redaction as R

ROOT = pathlib.Path(__file__).resolve().parents[3]


def _emp(name, role="walker"):
    return Employee(id=uuid.uuid4(), company_id=uuid.uuid4(), name=name, role=role)


def _code(fn) -> str:
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.Module)) \
                and ast.get_docstring(node):
            node.body = node.body[1:]
    return ast.unparse(tree)


# ── 1. capped and stripped at the boundary ──────────────────────────────────

def test_control_characters_are_removed():
    """A respondent cannot type these; a script can, and a NUL in a text column
    breaks every downstream reader differently."""
    assert sanitise_submitted_text("ok\x00bad\x07here") == "okbadhere"


def test_newlines_and_tabs_survive():
    """A respondent produces these by pressing Enter."""
    assert sanitise_submitted_text("line one\nline two") == "line one\nline two"


def test_it_caps_at_the_limit():
    assert len(sanitise_submitted_text("x" * 5000)) == 2000


def test_empty_after_cleaning_becomes_none():
    """An all-whitespace answer is not an answer, and D2's exactly-one-value
    constraint rejects a row whose only value is an empty string."""
    assert sanitise_submitted_text("   \n  ") is None
    assert sanitise_submitted_text(None) is None


def test_submitting_does_NOT_escape_formulas():
    """A walker who writes "-4 totes short" is recording data. Escaping on the
    way in corrupts it for every reader, and the database has readers that are
    not spreadsheets."""
    assert sanitise_submitted_text("-4 totes short") == "-4 totes short"
    assert sanitise_submitted_text("=sum of the day") == "=sum of the day"


def test_the_submit_path_uses_the_sanitiser():
    from app.routers import campaigns as C
    assert "sanitise_submitted_text(" in _code(C.submit_response)


# ── 2. escaped at every export sink ─────────────────────────────────────────

@pytest.mark.parametrize("trigger", ["=", "+", "-", "@", "\t", "\r", "\n"])
def test_every_formula_trigger_is_neutralised(trigger):
    out = escape_for_spreadsheet(f"{trigger}HYPERLINK(\"http://evil\")")
    assert out.startswith("'")


def test_escaping_prefixes_and_never_strips():
    """A building genuinely named "-Riverside" is data (ADR-435 D10)."""
    assert escape_for_spreadsheet("-Riverside") == "'-Riverside"
    assert "Riverside" in escape_for_spreadsheet("-Riverside")


def test_ordinary_text_is_untouched():
    assert escape_for_spreadsheet("ran out of totes") == "ran out of totes"


def test_none_becomes_empty_not_the_string_none():
    """A cell reading "None" is a bug a reader cannot distinguish from data."""
    assert escape_for_spreadsheet(None) == ""


# ── 3/4. redaction ──────────────────────────────────────────────────────────

def test_a_named_colleague_becomes_their_role():
    pats = R._name_patterns([_emp("Maria", "driver")])
    out, n = R.redact_names("Maria was late", pats)
    assert out == "[driver] was late" and n == 1


def test_matching_is_case_insensitive():
    """Somebody types "maria"."""
    pats = R._name_patterns([_emp("Maria", "driver")])
    out, _ = R.redact_names("maria was late", pats)
    assert out == "[driver] was late"


@pytest.mark.parametrize("text", [
    "the van was almost empty",     # contains "Al"
    "samples were short",           # contains "Sam"
    "we had to restart",            # contains "Art"
    "the problem was on route",     # contains "Rob"
])
def test_a_name_inside_an_ordinary_word_is_not_redacted(text):
    """THE hazard. Without word boundaries, case-insensitive matching turns
    "the van was almost empty" into "the van was [role]most empty" —
    a redaction that destroys the sentence and removes no name, irreversibly."""
    roster = [_emp(n) for n in ("Al", "Sam", "Art", "Rob")]
    out, n = R.redact_names(text, R._name_patterns(roster))
    assert out == text and n == 0


def test_a_full_name_is_replaced_whole():
    """Longest first, or "Maria Santos" leaves "[driver] Santos" behind — a
    partial redaction that still names somebody.

    Asserts the ORDER, not just one happy result: a single-employee roster
    happens to produce the right order without the sort, so the result alone
    cannot tell whether the sort exists. Two employees whose parts overlap
    make it observable."""
    pats = R._name_patterns([_emp("Maria Santos", "driver"),
                             _emp("Santos Lee", "walker")])
    lengths = [len(pat.pattern) for pat, _ in pats]
    assert lengths == sorted(lengths, reverse=True), (
        f"patterns are not longest-first: {[p.pattern for p, _ in pats]}")
    out, _ = R.redact_names("Maria Santos was late", pats)
    assert out == "[driver] was late"
    assert "Santos" not in out


def test_very_short_names_are_matched_only_in_full():
    """"Al" is a word as well as a name. A bare \bAl\b pattern redacts the
    sentence "Al said the route was fine" correctly but also every legitimate
    standalone "al" — and the employee is still reachable by their full name.

    The input matters: an earlier version asserted only that "Al Brown was
    late" redacts, which passes whether or not the short-name guard exists."""
    assert R.MIN_NAME_PART == 3
    pats = R._name_patterns([_emp("Al Brown", "driver")])
    # The full name is matched...
    assert R.redact_names("Al Brown was late", pats)[0] == "[driver] was late"
    # ...but the bare two-letter part is NOT a pattern, so a sentence using
    # "al" as a word is untouched. With the guard removed, this redacts.
    assert R.redact_names("al dente", pats)[0] == "al dente"
    assert all("\\bAl\\b" not in pat.pattern for pat, _ in pats)


def test_a_role_less_employee_still_redacts():
    pats = R._name_patterns([_emp("Maria", None)])
    out, _ = R.redact_names("Maria was late", pats)
    assert out == "[colleague] was late"


def test_the_window_is_seven_days():
    """Long enough for the follow-up that justified collecting it — an
    attribution grant lasts 48 hours (D13)."""
    assert R.REDACT_AFTER == datetime.timedelta(days=7)
    assert R.REDACT_AFTER > datetime.timedelta(hours=48)


def test_redaction_is_in_place_and_keeps_no_original():
    """Keeping the original anywhere — a shadow column, an audit payload —
    would make this retention theatre."""
    src = _code(R._redact_run)
    assert "answer.text_value = redacted" in src
    assert "original" not in src.lower()


def test_the_audit_row_carries_counts_not_the_names():
    """Putting redacted names in an audit row moves them from one table to
    another rather than removing them."""
    src = _code(R._redact_run)
    after = src[src.index("write_audit("):]
    assert "names_removed" in after
    assert "text_value" not in after


def test_structured_answers_are_untouched():
    """Redaction removes WHO; the separate retention horizon removes WHAT. A
    trend has to survive it intact."""
    src = _code(R._redact_run)
    assert "bool_value" not in src and "int_value" not in src


def test_every_answer_is_stamped_even_when_nothing_matched():
    """Or it is re-scanned forever against a roster that grows every week."""
    src = _code(R._redact_run)
    assert "answer.names_redacted_at = now" in src
    # the stamp is outside the `if n:` branch
    assert src.index("names_redacted_at = now") > src.index("if n:")


def test_one_companys_failure_does_not_stop_the_others():
    src = _code(R.redact_old_free_text)
    assert "db.rollback()" in src and "logger.exception" in src


# ── the client-side warning ─────────────────────────────────────────────────

def test_my_open_returns_only_the_crew_not_the_roster():
    """Handing a walker every employee's name to run a client-side check would
    be a larger disclosure than the one it prevents."""
    from app.routers import campaigns as C
    src = _code(C._crew_first_names)
    assert "AssignmentMember.assignment_id == assignment_id" in src
    assert "split()[0]" in src, "surnames must not be returned"


def test_the_warning_uses_word_boundaries_too():
    src = (ROOT / "frontend/src/pages/Campaigns.tsx").read_text()
    assert "namesACoworker" in src
    assert "\\\\b" in src, "the client regex has no word boundary"
    assert "name.length < 3" in src


def test_the_warning_does_not_block_submission():
    """A hard refusal on 2000 characters somebody just typed is how a report
    gets abandoned instead of rewritten."""
    src = (ROOT / "frontend/src/pages/Campaigns.tsx").read_text()
    submit = src[src.index("const submit = async"):src.index("// ---- the list")]
    assert "namesACoworker" not in submit, "the warning gates submission"

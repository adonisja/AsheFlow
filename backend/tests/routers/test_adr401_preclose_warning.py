"""ADR-401 D2 — the captain is warned before closing without a Flex count.

The close FREEZES `flex_package_count` (ADR-300 D5): a route closed without one
can never be given one, and its packages are missing from every figure the day
produces. That is the defect this whole thread started from — workforce
`delivered` was `None` for every tenant because no screen could record the count.

The SERVER deliberately does not refuse. A captain may have a real reason, and
ADR-400 A3 established that this system measures rather than enforces. So the
client is the only place the hole can be PREVENTED rather than reported weeks
later, which makes the warning load-bearing rather than cosmetic.
"""
import re
from pathlib import Path

import pytest

PAGE = (Path(__file__).resolve().parents[3]
        / "frontend" / "src" / "pages" / "WorkforceSort.tsx")


@pytest.fixture(scope="module")
def src() -> str:
    text = PAGE.read_text()
    assert "package-count" in text, "the page no longer records a Flex count"
    return text


def _code(src: str) -> str:
    """Source with comments stripped.

    A previous test in this repo asserted a feature's absence and matched the
    COMMENT explaining why it was absent. Comments describe; only code acts.
    """
    out = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"//[^\n]*", "", out)


class TestTheWarning:
    def test_closing_without_a_count_opens_a_confirmation(self, src: str) -> None:
        code = _code(src)
        assert "route.flex_package_count === null" in code, (
            "the close path no longer checks for a missing Flex count, so a "
            "captain can freeze a route's packages out of the day's totals "
            "with no warning (ADR-401 D2)"
        )
        assert "setCloseNoCount(route)" in code

    def test_the_check_is_null_not_falsy(self, src: str) -> None:
        """0 is a real count: a route that genuinely carried nothing. `!count`
        would warn about it and teach the captain to dismiss the warning."""
        code = _code(src)
        assert "!route.flex_package_count" not in code, (
            "the missing-count check became falsy, so a legitimate count of 0 "
            "triggers the warning"
        )

    def test_the_warning_says_what_is_lost(self, src: str) -> None:
        """A confirmation that does not state the consequence gets clicked
        through. This one has to say the count cannot be added later."""
        assert "cannot be added afterwards" in src

    def test_closing_is_still_possible(self, src: str) -> None:
        """ADR-400 A3: measure, do not enforce. The warning must not become a
        refusal — a confirmation nobody can accept is a block wearing a
        dialog."""
        assert "Close anyway" in src


class TestTheActions:
    def test_a_reserved_route_offers_no_actions(self, src: str) -> None:
        """ADR-406. Depart refuses a route that is not `assigned`, so buttons on
        a reserved route could only produce a 409."""
        code = _code(src)
        assert "!reserved && (r.status === 'assigned'" in code

    def test_the_count_can_be_edited_before_the_close(self, src: str) -> None:
        """ADR-291 D11 makes the count re-recordable right up to the close —
        a miscounted scan is corrected in the moment. The label has to say so,
        or a captain who sees "Record" assumes it is already final."""
        assert "'Edit count'" in src

    def test_only_an_in_progress_route_takes_a_count(self, src: str) -> None:
        """The count is read off Flex while the walker scans, which is after
        departure. Offering it on an assigned route invites a number nobody
        has seen yet."""
        code = _code(src)
        assert "r.status === 'in_progress' && (" in code

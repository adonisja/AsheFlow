"""ADR-400 A2 — the web client and the server must agree on what an OV is.

`is_ov_id` decides server-side whether a size is REQUIRED or REJECTED. The web
client makes the same decision to choose which controls to show and whether to
send `ov_size`. Two implementations of one rule drift, and the failure is a 422
the captain cannot act on: the form offered no size field, or offered one the
server refuses.

Source-text, because the client half is a regex literal in a .tsx file.
"""
import re
from pathlib import Path

import pytest

from app.services.workforce_ov_mint import is_ov_id

PAGE = (Path(__file__).resolve().parents[3]
        / "frontend" / "src" / "pages" / "ToteAddresses.tsx")


@pytest.fixture(scope="module")
def src() -> str:
    assert PAGE.exists(), f"ToteAddresses.tsx not found at {PAGE}"
    text = PAGE.read_text()
    # Vacuity guard: every assertion below passes trivially against a file that
    # no longer decides anything about OVs.
    assert "ov_size" in text, "the page no longer sends ov_size"
    return text


class TestOvIdRuleMatches:
    def test_the_client_regex_is_the_servers_rule(self, src: str) -> None:
        m = re.search(r"function isOv\(bagId: string\): boolean \{\s*return (.+?);", src, re.S)
        assert m, "isOv() is gone or changed shape — check it still mirrors is_ov_id"
        assert r"/^OV\d+$/" in m.group(1), (
            "the client's OV test drifted from the server's `^OV(\\d+)$`. A "
            "mismatch means the form asks for a size the server rejects, or "
            "omits one the server requires (ADR-400 A2)"
        )

    @pytest.mark.parametrize("bag_id,expected", [
        ("OV0012", True), ("OV1", True),
        ("6800", False),          # a real bag id: bare digits
        ("OVX", False), ("", False),
    ])
    def test_server_side_agrees_with_those_cases(self, bag_id, expected):
        """The client regex is asserted above; this pins the server half to the
        same answers, so the pair cannot drift in either direction."""
        assert is_ov_id(bag_id) is expected


class TestControlsMatchTheRule:
    def test_size_is_sent_only_for_an_ov(self, src: str) -> None:
        """A size on a tote is a 422. It must be impossible to send one."""
        assert "...(openIsOv ? { ov_size: size } : {})" in src, (
            "ov_size is no longer conditional on the bag being an OV"
        )

    def test_the_size_picker_is_ov_only(self, src: str) -> None:
        assert "{openIsOv && (" in src, "the size picker lost its OV guard"

    def test_the_count_picker_is_tote_only(self, src: str) -> None:
        """An OV is one package (A2), so a package count is meaningless for it
        and offering one invites a number that means nothing."""
        assert "{!openIsOv && (" in src, "the package-count picker lost its guard"

    def test_ov_entry_closes_after_one_address(self, src: str) -> None:
        """An OV takes exactly one address; the server 409s a second. Leaving
        the form open would invite the captain into that error."""
        assert "if (openIsOv) setOpenBag(null)" in src


class TestSizeVocabulary:
    def test_the_page_offers_exactly_the_server_tiers(self, src: str) -> None:
        from app.models.workforce_ov import OV_SIZES
        m = re.search(r"const OV_SIZES = \[(.+?)\] as const", src)
        assert m, "the page's size list is gone"
        offered = set(re.findall(r"'([A-Z]+)'", m.group(1)))
        assert offered == set(OV_SIZES), (
            f"the page offers {sorted(offered)} but the server accepts "
            f"{sorted(OV_SIZES)} — an offered size the server rejects is a 422 "
            f"on submit, and a missing one is a route that cannot be costed"
        )

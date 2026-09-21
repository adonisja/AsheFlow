"""ADR-449: an address starts at its house number.

Two bugs, one rule:

  PII     `John Smith 380 W 33rd St` was stored verbatim, while the
          data-handling record states standardisation strips customer PII
          before it reaches the server.
  DUPES   the same string keyed differently from `380 W 33rd St`, so the SAME
          doorway was collected twice and the duplicate check silently stopped
          working for exactly the typing habit this ADR is about.
"""
import datetime
import re

import pytest
from pydantic import ValidationError

from app.schemas.collection import CollectedProfileIn
from app.services.door_key import (
    AddressShapeError,
    door_key,
    normalise_submitted_address,
    strip_leading_non_number,
)

VALID = dict(building_type="elevator", workloads=["high_rise"],
             collected_on=datetime.date(2026, 9, 21))


class TestALeadingNameIsNotPartOfTheAddress:
    @pytest.mark.parametrize("raw,expected", [
        ("John Smith 380 W 33rd St", "380 W 33rd St"),
        ("Mrs. Lee 12 Main St",      "12 Main St"),
        ("  Dr. O'Brien 5 Elm Rd ",  "5 Elm Rd"),
        ("380 W 33rd St",            "380 W 33rd St"),   # already clean
    ])
    def test_everything_before_the_first_digit_is_dropped(self, raw, expected):
        assert normalise_submitted_address(raw) == expected

    def test_the_name_never_reaches_the_stored_address(self):
        """The PII half. The request schema is where this must happen — a fold
        applied only at key time would leave the name in the database."""
        p = CollectedProfileIn(address="John Smith 380 W 33rd St", **VALID)
        assert p.address == "380 W 33rd St"
        assert "John" not in p.address and "Smith" not in p.address

    def test_a_name_no_longer_splits_one_doorway_into_two(self):
        """The duplicate half, and the worse of the two bugs.

        Before ADR-449 these produced different keys, so a walker was sent to a
        building a coworker had already done.
        """
        assert door_key("John Smith 380 W 33rd St") == door_key("380 W 33rd St")


class TestASpelledOutNumberIsRefused:
    @pytest.mark.parametrize("raw", [
        "One Penn Plaza",
        "Fifty Fifth Ave",
        "Third Avenue",
    ])
    def test_it_raises_rather_than_guessing(self, raw):
        """"Fifty Fifth Ave" could be 50 5th, 55th, or a street named
        Fifty-Fifth. A server that guesses produces a confident wrong answer
        that nobody reviews; the collector is standing in front of the building.
        """
        with pytest.raises(AddressShapeError) as exc:
            normalise_submitted_address(raw)
        msg = str(exc.value)
        assert "digits" in msg, "the message must name the remedy, not just refuse"
        # The remedy is a LOOKUP. "Write it in digits" tells someone who does
        # not KNOW the number to invent one; naming where to find it does not.
        assert any(w in msg for w in ("entrance", "label", "map")), \
            "the message must say where to find the number, not only that one is needed"

    def test_the_schema_rejects_it_too(self):
        with pytest.raises(ValidationError) as exc:
            CollectedProfileIn(address="One Penn Plaza", **VALID)
        assert "digits" in str(exc.value)

    def test_a_number_word_inside_a_real_address_is_fine(self):
        """`12 Fifth Ave` has a house number; only the FIRST word is checked."""
        assert normalise_submitted_address("12 Fifth Ave") == "12 Fifth Ave"


class TestANameWithNoNumberIsADifferentMistake:
    def test_a_building_name_is_refused_with_its_own_message(self):
        """`Riverside Apartments` is not a mis-spelled number — the collector
        needs to FIND the number, not rewrite a word, so the remedy differs."""
        with pytest.raises(AddressShapeError) as exc:
            normalise_submitted_address("Riverside Apartments")
        msg = str(exc.value)
        assert "house number" in msg
        # Distinguished by what it does NOT say: there is no number word here
        # to convert, so offering "1 Penn Plaza" as the fix would be nonsense.
        assert "Penn Plaza" not in msg, \
            "this is the wrong remedy: there is no number word to rewrite"
        assert any(w in msg for w in ("entrance", "label")), \
            "the message must say where to find the number"


class TestFoldingStaysTotal:
    """door_key must never raise: it keys rows that predate this rule."""

    @pytest.mark.parametrize("raw", [
        "One Penn Plaza", "Riverside Apartments", "", "   ", "!!!",
    ])
    def test_it_returns_a_key_for_anything(self, raw):
        door_key(raw)          # must not raise

    def test_a_digitless_string_is_returned_unchanged_by_the_strip(self):
        """Deciding what to do about it is validation's job, not folding's."""
        assert strip_leading_non_number("Riverside Apartments") == "Riverside Apartments"


class TestTheClientImplementsTheSameRule:
    """ADR-417's two-implementation cost, kept honest.

    The client warns so it can warn OFFLINE; the server is what rejects. They
    must agree on where an address starts or the offline duplicate warning
    disagrees with what the server computes.
    """

    TS = (pathlib_ts := __import__("pathlib").Path(__file__).resolve().parents[2]
          / "frontend" / "src" / "utils" / "addressProfile.ts")

    def test_the_client_strips_the_same_prefix(self):
        src = self.TS.read_text()
        assert "stripLeadingNonNumber" in src
        assert re.search(r"replace\(/\^\\D\*/", src), \
            "the client does not strip to the first digit (ADR-449 D4)"

    def test_the_client_folds_after_stripping(self):
        """Order matters: stripping AFTER folding leaves the name in the key."""
        src = self.TS.read_text()
        fold = src.index("export function doorKey")
        body = src[fold:fold + 400]
        assert "stripLeadingNonNumber(address)" in body

    def test_the_client_knows_the_same_number_words(self):
        src = self.TS.read_text()
        for word in ("one", "fifty", "ninety", "third"):
            assert f"'{word}'" in src, f"client NUMBER_WORDS is missing {word!r}"


class TestTheRuleMatchesWhatGeoClientCanParse:
    """The validator and the geocoder must agree on what an address is.

    GeoClient takes SEPARATE houseNumber and street parameters, split by
    `_parse_house_and_street`, which requires the first token to be digits. If
    the validator accepted something that parser rejects, the profile would be
    stored looking collected and could never be enriched — geometry silently
    absent forever.
    """

    def _parses(self, address: str) -> bool:
        from app.tasks.enrich_manifest import _parse_house_and_street, strip_address_noise
        return _parse_house_and_street(strip_address_noise(address)) is not None

    @pytest.mark.parametrize("address", [
        "1 Penn Plaza",
        "12 Fifth Ave",          # spelled-out STREET is fine
        "411 W 36 St",
        "47-10 Vernon Blvd",     # Queens hyphenated house number
    ])
    def test_what_we_accept_geoclient_can_parse(self, address):
        assert normalise_submitted_address(address) == address
        assert self._parses(address), \
            f"{address!r} passes validation but cannot be geocoded"

    @pytest.mark.parametrize("address", [
        "One Penn Plaza",
        "Fifty Fifth Ave",
    ])
    def test_what_we_reject_geoclient_could_not_parse_anyway(self, address):
        """The rejection is not merely our preference — these are unusable."""
        assert not self._parses(address), (
            f"{address!r} IS parseable by GeoClient, so rejecting it may be "
            "wrong — re-check ADR-449 D2"
        )
        with pytest.raises(AddressShapeError):
            normalise_submitted_address(address)

    def test_a_stripped_name_leaves_something_geocodable(self):
        """The strip must not merely satisfy the validator — the result has to
        survive the parser too."""
        cleaned = normalise_submitted_address("John Smith 380 W 33rd St")
        assert self._parses(cleaned)

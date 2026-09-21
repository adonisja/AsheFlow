"""Loose address folding, for duplicate detection ONLY (ADR-417 D7).

NOT normalisation for storage. The address is stored exactly as the collector
typed it and GeoClient canonicalises later (ADR-277 D1) — guessing at a
canonical form here would produce addresses that match nothing downstream.

This exists for one question: "is this the same doorway as one we already
have?" A collector types `380 West 33rd Street`, a coworker typed
`380 W 33 ST`, and an exact-match check would send someone to a door that was
already done. Folding the handful of variations people actually type answers
that question; it is deliberately lossy and deliberately not authoritative.

MUST STAY IN STEP WITH `doorKey()` in frontend/src/utils/addressProfile.ts.
The client warns with its own copy so it can warn offline; the server is what
actually rejects. Two implementations of one rule is a real cost, accepted
because the alternative is a round trip on every keystroke. The shared test
vector below is what keeps them honest — add a case to both when either moves.
"""
from __future__ import annotations

import re

# Ordered: ordinals before direction words, so "33rd" is a number before
# "North" becomes "n" and could collide with an ordinal suffix.
_PUNCT      = re.compile(r"[.,#]")
_ORDINAL    = re.compile(r"\b(\d+)(st|nd|rd|th)\b")
_DIRECTION  = re.compile(r"\b(north|south|east|west)\b")
_UNIT_TAIL  = re.compile(r"\b(apartment|apt|unit|suite|ste)\b.*$")
_WHITESPACE = re.compile(r"\s+")

# ADR-449. A US street address begins with a house number, so anything before
# the first digit is not part of the address — it is a customer name typed ahead
# of it, which is both PII we must not store and, left in place, a prefix that
# gives the SAME doorway two different keys.
_BEFORE_FIRST_DIGIT = re.compile(r"^\D*")

# Spelled-out house numbers. Refused rather than converted (D2): "Fifty Fifth
# Ave" could be 50 5th, 55th, or a street named Fifty-Fifth, and a server that
# guesses produces a confident wrong answer nobody reviews.
NUMBER_WORDS = frozenset("""
one two three four five six seven eight nine ten eleven twelve thirteen
fourteen fifteen sixteen seventeen eighteen nineteen twenty thirty forty
fifty sixty seventy eighty ninety hundred
first second third fourth fifth sixth seventh eighth ninth tenth
""".split())


def strip_leading_non_number(address: str) -> str:
    """Drop everything before the first digit (ADR-449 D1).

    `John Smith 380 W 33rd St` -> `380 W 33rd St`.

    Returns the input unchanged when it holds no digit at all; deciding what to
    do about that is validation's job, not folding's, and door_key must stay
    total so it can key rows that predate this rule.
    """
    if not any(c.isdigit() for c in address):
        return address
    return _BEFORE_FIRST_DIGIT.sub("", address, count=1)

# A unit is not a door: two packages for different apartments are one building
# visit, so the unit must not make them look like two buildings.
_STREET_TYPES = [
    (re.compile(r"\b(street|st)\b"),        "st"),
    (re.compile(r"\b(avenue|ave|av)\b"),    "ave"),
    (re.compile(r"\b(boulevard|blvd)\b"),   "blvd"),
    (re.compile(r"\b(road|rd)\b"),          "rd"),
    (re.compile(r"\b(place|pl)\b"),         "pl"),
    (re.compile(r"\b(drive|dr)\b"),         "dr"),
    (re.compile(r"\b(lane|ln)\b"),          "ln"),
    (re.compile(r"\b(parkway|pkwy)\b"),     "pkwy"),
]


def door_key(address: str) -> str:
    """Fold an address to a comparison key. Lossy by design."""
    # ADR-449 D1 FIRST: a leading name must not reach the key, or one doorway
    # gets two keys and the duplicate check silently stops working.
    s = strip_leading_non_number(address).lower()
    s = _PUNCT.sub(" ", s)
    s = _ORDINAL.sub(r"\1", s)
    s = _DIRECTION.sub(lambda m: m.group(0)[0], s)
    for pattern, canon in _STREET_TYPES:
        s = pattern.sub(canon, s)
    s = _UNIT_TAIL.sub("", s)
    return _WHITESPACE.sub(" ", s).strip()


class AddressShapeError(ValueError):
    """The string is not an address. `message` is shown to the collector."""


def normalise_submitted_address(address: str) -> str:
    """Strip any leading name and require a house number (ADR-449 D1-D3).

    Raises AddressShapeError with a message naming the remedy. Used by the
    REQUEST schema so a customer name is never stored; door_key applies the
    same strip independently so rows that predate this still key correctly.
    """
    cleaned = strip_leading_non_number(address).strip()

    if cleaned and cleaned[0].isdigit():
        return cleaned

    # No digit anywhere. Two different mistakes, two different remedies.
    first = (address.strip().lower().split() or [""])[0].strip(".,#")
    if first in NUMBER_WORDS:
        # The remedy is a LOOKUP, not a rewrite. "Fifty Fifth Ave" could be
        # 50 5th, 55th, or a street named Fifty-Fifth, and the collector is
        # standing in front of the building with the door number on it.
        raise AddressShapeError(
            "Use the number on the building, in digits. Check the entrance, a "
            'package label, or a map. "One Penn Plaza" is entered as '
            '"1 Penn Plaza".'
        )
    raise AddressShapeError(
        "An address needs to start with its house number. Check the entrance "
        "or a package label. For example: 433 W 32 ST."
    )

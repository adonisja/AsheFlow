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
    s = address.lower()
    s = _PUNCT.sub(" ", s)
    s = _ORDINAL.sub(r"\1", s)
    s = _DIRECTION.sub(lambda m: m.group(0)[0], s)
    for pattern, canon in _STREET_TYPES:
        s = pattern.sub(canon, s)
    s = _UNIT_TAIL.sub("", s)
    return _WHITESPACE.sub(" ", s).strip()

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

import functools
import json
import pathlib
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


# ADR-495 D7 — the DISPLAY form, for a collected address entering
# `building_profiles`. Unlike door_key this is stored and read back, so it keeps
# the form GeoClient returns ("433 W 32 ST") rather than a lowercase key.
#
# MUST STAY IN STEP WITH `canonicalAddress()` in
# frontend/src/utils/addressProfile.ts (ADR-420 D4): rows submitted after
# ADR-420 were already rewritten by it on the page, and promotion must produce
# the same string for them, or a door collected before ADR-420 and one after
# would be stored as two buildings.
# The ONE list of unit/floor words (ADR-497 D2). derive_block_key.py (routing,
# and the GeoClient request) imports this pattern rather than keeping a copy:
# two lists drifted, and the routing copy cut `55 Front St` to `55` long after
# this one was fixed. A noise word followed by a street type is a street name.
NOISE_PATTERN = (
    r"\b(attn|attention|apt|unit|ground|floor|fl|host|suite|ste|basement|bsmt|lobby|rear|front)\b"
    r"(?!\s+(street|st|avenue|ave|av|boulevard|blvd|road|rd|place|pl|drive|dr|lane|ln|parkway|pkwy)\b)"
)
_NOISE = re.compile(NOISE_PATTERN, re.IGNORECASE)
_CANON_TYPES = [(re.compile(p.pattern, re.IGNORECASE), c.upper()) for p, c in _STREET_TYPES]


def _rule_fold(text: str) -> str:
    """The rule-based fold (ADR-495 D7): the fallback when the lexicon has no
    match, and what the web twin `canonicalAddress()` previews offline."""
    s = _NOISE.split(text)[0].strip().rstrip(",")
    s = _PUNCT.sub(" ", s)
    s = re.sub(r"\b(\d+)(st|nd|rd|th)\b", r"\1", s, flags=re.IGNORECASE)
    s = re.sub(r"\b(north|south|east|west)\b", lambda m: m.group(0)[0], s, flags=re.IGNORECASE)
    for pattern, canon in _CANON_TYPES:
        s = pattern.sub(canon, s)
    return _WHITESPACE.sub(" ", s).strip().upper()


# ── ADR-582: the city's own street names ─────────────────────────────────────
#
# The standard's target is AddressPoint's spelling, because PlaceType's doors
# come from AddressPoint. A rule cannot tell `WEST ST` (a street named West)
# from `West 32nd St` (a direction), or keep `HOLLIS CT BOULEVARD` whole; the
# city's list of names can. Input is folded to a key and matched against the
# same fold of every city name; the city's spelling is returned.

# House number: digits, optional -digits (Queens), each with an optional letter.
_HOUSE = re.compile(r"^\s*(\d+[A-Za-z]?(?:\s*-\s*\d+[A-Za-z]?)?)(?=\s|,|$)")

_ORDINAL_WORDS = {
    "first": "1", "second": "2", "third": "3", "fourth": "4", "fifth": "5", "sixth": "6",
    "seventh": "7", "eighth": "8", "ninth": "9", "tenth": "10", "eleventh": "11",
    "twelfth": "12",
}
# Fold-key street types: wider than _STREET_TYPES because the city uses more.
_FOLD_TYPES = {
    "street": "st", "avenue": "ave", "av": "ave", "boulevard": "blvd", "road": "rd",
    "place": "pl", "drive": "dr", "lane": "ln", "parkway": "pkwy", "court": "ct",
    "terrace": "ter", "plaza": "plz", "square": "sq", "circle": "cir",
    "expressway": "expy", "crescent": "cres", "highway": "hwy", "green": "grn",
    "alley": "aly", "saint": "st", "mount": "mt", "fort": "ft",
}
_DIRECTION_FOLD = {"north": "n", "south": "s", "east": "e", "west": "w"}


def _fold_tokens(text: str) -> list[str]:
    s = _PUNCT.sub(" ", text.lower())
    s = re.sub(r"\b(\d+)(st|nd|rd|th)\b", r"\1", s)
    out = []
    for t in s.split():
        t = _ORDINAL_WORDS.get(t, t)
        t = _DIRECTION_FOLD.get(t, t)
        out.append(_FOLD_TYPES.get(t, t))
    return out


_BOROUGH_CODES = {
    "1": "1", "manhattan": "1", "mn": "1", "new york": "1",
    "2": "2", "bronx": "2", "bx": "2",
    "3": "3", "brooklyn": "3", "bk": "3",
    "4": "4", "queens": "4", "qn": "4",
    "5": "5", "staten island": "5", "si": "5",
}


def borough_code(borough) -> str | None:
    """'manhattan' / 'MN' / 1 / '1' -> '1'. None when unknown."""
    if borough is None:
        return None
    return _BOROUGH_CODES.get(str(borough).strip().lower())


@functools.lru_cache(maxsize=1)
def _lexicon() -> tuple[dict, dict]:
    """({borough: {fold_key: name}}, {fold_key: name-or-None-if-ambiguous})."""
    path = pathlib.Path(__file__).resolve().parents[1] / "data" / "street_lexicon.json"
    data = json.loads(path.read_text())["boroughs"]
    by_boro: dict[str, dict[str, str]] = {}
    city: dict[str, str | None] = {}
    for boro, names in data.items():
        m = by_boro.setdefault(boro, {})
        for name in names:
            key = " ".join(_fold_tokens(name))
            # Same key twice in one borough: keep neither, so the fold never
            # silently picks one of two real streets.
            m[key] = None if key in m and m[key] != name else name
            city[key] = name if city.get(key, name) == name else None
    return by_boro, city


def _match_street(tokens: list[str], boro: str | None) -> str | None:
    by_boro, city = _lexicon()
    table = by_boro.get(boro) if boro else city
    if not table:
        return None
    # Exact spelling first: where two real streets fold to one key (the Bronx
    # has both NORTH ST and N ST), the fold refuses to choose, and the words as
    # written are the only honest tie-break.
    exact = _exact_names().get(boro) if boro else _exact_names().get(None)
    words = _PUNCT.sub(" ", " ".join(tokens)).upper().split()
    for k in range(len(words), 0, -1):
        cand = " ".join(words[:k])
        if exact and cand in exact:
            return cand
    folded = _fold_tokens(" ".join(tokens))
    for k in range(len(folded), 0, -1):          # longest run of words wins
        name = table.get(" ".join(folded[:k]))
        if name:
            return name
    return None


@functools.lru_cache(maxsize=1)
def _exact_names() -> dict:
    """{borough: set(names)} plus None -> every name in the city."""
    path = pathlib.Path(__file__).resolve().parents[1] / "data" / "street_lexicon.json"
    data = json.loads(path.read_text())["boroughs"]
    out = {b: set(v) for b, v in data.items()}
    out[None] = set().union(*out.values())
    return out


def canonical_address(address: str, borough=None) -> str:
    """The address standard (ADR-582).

    `Jane Sample 350 Fifth Avenue #4B` -> `350 5 AVE`;  `1 West Street` -> `1 WEST ST`;
    `455a W 32nd St, Apt 3` -> `455A W 32 ST`;  `123 - 45 145th Street` -> `123-45 145 ST`.

    House number plus the city's spelling of the street. Never a name before
    the number (ADR-449, enforced HERE, not only in one request schema), never a
    unit, floor or anything after the street. Falls back to the rule fold when
    the street is not in the city's list.
    """
    s = strip_leading_non_number(address or "")
    m = _HOUSE.match(s)
    if not m:
        return _rule_fold(s)
    house = re.sub(r"\s+", "", m.group(1)).upper()
    rest = _NOISE.split(s[m.end():])[0]
    street = _match_street(rest.split(), borough_code(borough))
    if street:
        return f"{house} {street}"
    folded = _rule_fold(rest)
    return f"{house} {folded}".strip()


def door_identity(borough, address: str) -> tuple[str | None, str]:
    """ADR-580 D2 / ADR-582 D3: one door, one key. BIN is an attribute."""
    code = borough_code(borough)
    return code, canonical_address(address, code)


# ADR-496 — does this address still name a street?
#
# Two different failures, one check. `street_lost` is OUR bug: the input names
# a street type and canonical_address() dropped it (how `55 Front St` became
# `55`). `no_street` is the input's: nothing after the house number names a
# street. MUST STAY IN STEP WITH `addressProblem()` in addressProfile.ts.
_STREET_WORD = re.compile(
    r"\b(street|st|avenue|ave|av|boulevard|blvd|road|rd|place|pl|drive|dr|lane|ln|parkway|pkwy)\b",
    re.IGNORECASE,
)
_DIRECTIONS = frozenset({"n", "s", "e", "w", "north", "south", "east", "west"})

STREET_LOST = "street_lost"
NO_STREET = "no_street"

ADDRESS_PROBLEM_TEXT = {
    STREET_LOST: "Part of this address was dropped while tidying it. Check the street name.",
    NO_STREET: "This address has no street name. Check the entrance or a package label.",
}


def address_problem(address: str) -> str | None:
    """`street_lost`, `no_street`, or None when the address names a street."""
    raw = strip_leading_non_number(address or "").strip()
    canon = canonical_address(raw)
    if _STREET_WORD.search(raw) and not _STREET_WORD.search(canon):
        return STREET_LOST
    words = canon.split()[1:]
    if not any(re.search(r"[A-Z]", w) and w.lower() not in _DIRECTIONS for w in words):
        return NO_STREET
    return None


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

"""ADR-296 D5 — the block key rendered as a sentence.

The point of these tests is the THIRD case. A hundred-floored key and a
hyphenated outer-borough key are the same shape, so a client that parses the
trailing number out of the string cannot tell them apart and will state a range
that does not exist. `100-15 Astoria Blvd` is the proof: it produces
`Astoria_Blvd_100`, byte-for-byte what a Manhattan hundred-block produces.
"""
import pytest

# derive_block_key.py is proprietary and gitignored — the public CI checkout does
# not have it, and a bare top-level import would fail COLLECTION and take the whole
# backend-test job with it, not just this file.
from app.services.derive_block_key import (
    ParsedBlock, derive_block_key, describe_stored_block,
)


# ── hundred-block addresses get a real range ─────────────────────────────────

@pytest.mark.parametrize("address, key, description", [
    ("411 W 36 St", "W_36_St_400",
     "Block spanning 400 to 499 along W 36 St"),
    ("123 Metropolitan Ave", "Metropolitan_Ave_100",
     "Block spanning 100 to 199 along Metropolitan Ave"),
    ("789 Broadway", "Broadway_700",
     "Block spanning 700 to 799 along Broadway"),
    ("100 West End Ave", "West_End_Ave_100",
     "Block spanning 100 to 199 along West End Ave"),
])
def test_hundred_block_reads_as_a_range(address, key, description):
    parsed = derive_block_key(address, "TBA1")
    assert isinstance(parsed, ParsedBlock)
    assert parsed.block_key == key
    assert parsed.description == description


# ── hyphenated addresses must NOT invent a range ─────────────────────────────

@pytest.mark.parametrize("address, key, cross", [
    ("47-10 Vernon Blvd", "Vernon_Blvd_47", 47),
    ("47-10 36 St",       "36_St_47",       47),
    ("100-15 Astoria Blvd", "Astoria_Blvd_100", 100),
])
def test_hyphenated_describes_a_cross_street_not_a_span(address, key, cross):
    parsed = derive_block_key(address, "TBA1")
    assert isinstance(parsed, ParsedBlock)
    assert parsed.block_key == key
    assert parsed.description == f"Block near cross-street {cross} along {_street(key)}"
    # The failure this guards: never claim a 99-wide span for a cross street.
    assert "spanning" not in parsed.description


def test_the_ambiguous_key_is_only_resolvable_from_the_address():
    """`Astoria_Blvd_100` is the shape of BOTH a hundred-block and a cross street.

    This is the entire justification for deriving the sentence server-side. If
    this assertion ever fails, the key has become self-describing and a client
    could safely parse it.
    """
    queens = derive_block_key("100-15 Astoria Blvd", "T")
    manhattan = derive_block_key("100 Astoria Blvd", "T")
    assert queens.block_key == manhattan.block_key == "Astoria_Blvd_100"
    assert queens.description != manhattan.description
    assert "cross-street" in queens.description
    assert "spanning" in manhattan.description


# ── read-time re-derivation ──────────────────────────────────────────────────

def test_stored_row_is_described_from_its_address():
    assert describe_stored_block("411 W 36 St", "W_36_St_400") == (
        "Block spanning 400 to 499 along W 36 St"
    )


@pytest.mark.parametrize("address, key", [
    (None, "W_36_St_400"),            # address nulled for PII (ADR-219)
    ("411 W 36 St", None),            # never parsed
    ("gibberish", "W_36_St_400"),     # no longer parses
    ("411 W 36 St", "Other_St_100"),  # stored key predates a parser change
])
def test_returns_none_rather_than_guessing(address, key):
    """Every degraded input falls back to showing the raw key, as before."""
    assert describe_stored_block(address, key) is None


def _street(key: str) -> str:
    """Street label back out of a key, for the expectation above."""
    return " ".join(key.split("_")[:-1])

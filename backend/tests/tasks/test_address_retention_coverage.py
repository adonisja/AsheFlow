"""Coverage guard for the 48h delivery-address nulling sweep (ADR-464 D2).

`test_null_delivery_addresses.py` tests the sweep's BEHAVIOUR — that it respects
`retention_hours=0` and scrubs the Route ARRAY plus the stops JSONB. It does not
test its COVERAGE: a new table that stores a customer delivery address is invisible
to it, and the address simply persists forever.

Same failure shape as the employee-name registry before ADR-464: the existing test
read the implementation rather than the schema, so it could only confirm the code
agrees with itself.

So this walks the models and requires every address-like column to be either
scrubbed by the sweep or explicitly exempted with a reason. The exemptions matter
more here than on the name side, because a plain reading of "48-hour address
retention" does not survive contact with `building_profiles` — and an auditor who
finds an indefinitely-retained address column we never described is entitled to
distrust the rest of the claim.

The distinction that justifies every exemption below:

  A CUSTOMER DELIVERY ADDRESS is where one package went on one day. It is
  ephemeral operational data and is nulled at 48h (ADR-219).

  A BUILDING PROFILE ADDRESS is durable institutional knowledge about a place —
  which door, which buzzer, whether the loading dock is usable. It is not tied to
  a delivery, a customer or a date, and nulling it would destroy the knowledge
  base the routing system is built on (ADR-135, ADR-277).

If a future column blurs that line, the answer is almost always to scrub it.
"""
import app.models  # noqa: F401  — registers every mapper on Base.registry
from app.models.base import Base


# Tables the ADR-219 sweep nulls. Mirrors null_expired_delivery_addresses() in
# app/tasks/cleanup.py — if the sweep gains a table, add it here.
SWEPT: dict[str, tuple[str, ...]] = {
    "routes":                 ("normalised_addresses",),   # + stops JSONB, scrubbed in-place
    "delivery_stops":         ("normalised_address",),
    "misrouted_package_flags": ("normalised_address",),
    "rts_packages":           ("normalised_address",),
    "missing_packages":       ("normalised_address",),
    "damaged_packages":       ("normalised_address",),
    "tote_addresses":         ("raw_address", "normalised_address"),
}

# Address-like columns the sweep deliberately does NOT touch, each with a reason.
EXEMPT: dict[tuple[str, str], str] = {
    # --- Durable building knowledge, not delivery history (ADR-135, ADR-277) ---
    ("building_profiles",          "normalised_address"): (
        "The building profile IS the address — it is the knowledge base key, not a "
        "record of a delivery. Nulling it destroys the profile."
    ),
    ("building_profile_library",   "normalised_address"): (
        "Global cross-tenant library key (ADR-220). Same reasoning, platform scope."
    ),
    ("collected_address_profiles", "address"): (
        "A building observation submitted via the public collection campaign "
        "(ADR-415/439) — an observation about a place, never tied to a package."
    ),

    # --- Not a customer address at all ---
    ("trucks", "initial_anchor_address"): (
        "Crew staging point (a street corner) set by dispatch — an operational "
        "meet-up location, not a delivery destination."
    ),
    ("trucks", "initial_anchor_display_address"): "Display form of the staging point.",
    ("trucks", "initial_anchor2_address"): "Second crew staging point.",
    ("trucks", "initial_anchor2_display_address"): "Display form of the second staging point.",

    # --- Reference data, no personal connection ---
    ("street_segments", "street_name"):         "NYC street-segment reference dataset.",
    ("street_segments", "first_cross_street"):  "NYC street-segment reference dataset.",
    ("street_segments", "second_cross_street"): "NYC street-segment reference dataset.",

    # --- Cross-streets on a swept table: block-level, not house-level ---
    # tote_addresses' own address columns ARE swept (see SWEPT). These two name a
    # block boundary, which is what a block_key encodes and what the sweep keeps
    # on purpose — the retained unit of work after the address is gone (ADR-297).
    ("tote_addresses", "first_cross_street"):  "Block boundary, not a house address (ADR-297).",
    ("tote_addresses", "second_cross_street"): "Block boundary, not a house address (ADR-297).",

    # --- Not an address: a status flag and structural counts/coordinates ---
    ("building_profiles", "address_status"):     "Resolution lifecycle state, not an address.",
    ("building_profile_library", "street_frontages"): "Integer count of entrances.",
    ("street_segments", "x_low_address_end"):   "Projected coordinate (integer).",
    ("street_segments", "y_low_address_end"):   "Projected coordinate (integer).",
    ("street_segments", "x_high_address_end"):  "Projected coordinate (integer).",
    ("street_segments", "y_high_address_end"):  "Projected coordinate (integer).",
}

_PATTERNS = ("address", "street", "cross_street")


def _address_like_columns() -> list[tuple[str, str]]:
    found = []
    for mapper in Base.registry.mappers:
        table = getattr(mapper.class_, "__tablename__", None)
        if not table:
            continue
        for col in mapper.columns:
            if any(p in col.key for p in _PATTERNS):
                found.append((table, col.key))
    return found


def test_every_address_column_is_swept_or_exempt():
    """No address-like column escapes the ADR-219 retention decision unnoticed.

    A new column here is not necessarily a bug — but it must be a DECISION. Add it
    to the sweep in app/tasks/cleanup.py and to SWEPT, or to EXEMPT with the reason
    it is not a customer delivery address.
    """
    unaccounted = [
        (t, c) for t, c in _address_like_columns()
        if c not in SWEPT.get(t, ()) and (t, c) not in EXEMPT
    ]
    assert not unaccounted, (
        "Address-like column(s) with no retention decision — if any holds a "
        "customer delivery address it persists forever, contradicting ADR-219:\n"
        + "\n".join(f"  {t}.{c}" for t, c in sorted(unaccounted))
        + "\n\nEither null it in null_expired_delivery_addresses() and add it to "
          "SWEPT, or add it to EXEMPT in this file with the reason it is not a "
          "customer delivery address."
    )


def test_swept_columns_still_exist():
    """SWEPT mirrors the sweep by hand. A renamed column would leave the sweep
    silently updating nothing, and this catches the drift."""
    live = {
        (getattr(m.class_, "__tablename__", None), c.key)
        for m in Base.registry.mappers
        for c in m.columns
    }
    missing = [
        (t, c) for t, cols in SWEPT.items() for c in cols if (t, c) not in live
    ]
    assert not missing, (
        "SWEPT names column(s) that no longer exist — the sweep may be nulling "
        "nothing:\n" + "\n".join(f"  {t}.{c}" for t, c in sorted(missing))
    )


def test_exempt_entries_still_exist():
    """A stale exemption silently covers a future column of the same name."""
    live = {
        (getattr(m.class_, "__tablename__", None), c.key)
        for m in Base.registry.mappers
        for c in m.columns
    }
    stale = [pair for pair in EXEMPT if pair not in live]
    assert not stale, (
        "EXEMPT lists column(s) that no longer exist — remove them:\n"
        + "\n".join(f"  {t}.{c}" for t, c in sorted(stale))
    )


def test_every_exemption_has_a_reason():
    """An unexplained exemption is how the allow-list becomes the leak."""
    blank = [pair for pair, reason in EXEMPT.items() if not reason or not reason.strip()]
    assert not blank, f"EXEMPT entries with no reason: {sorted(blank)}"


def test_sweep_and_exempt_do_not_overlap():
    """A column both swept and exempted is a contradiction — the sweep wins, so
    the exemption misleads the next reader."""
    swept = {(t, c) for t, cols in SWEPT.items() for c in cols}
    both = swept & set(EXEMPT)
    assert not both, (
        "Column(s) both SWEPT and EXEMPT — remove the EXEMPT entry:\n"
        + "\n".join(f"  {t}.{c}" for t, c in sorted(both))
    )

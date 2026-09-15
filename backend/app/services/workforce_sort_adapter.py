"""Turn captain-entered tote addresses into sort input (ADR-291 D5).

THIS IS AN ADAPTER, NOT A SECOND SORT.

`route_sort.py` is ~1,700 lines and the deepest IP in the product. Forking it
for workforce mode would put ADR-272's pinned seed, OV pairing and the F5
consolidation loop in two places, where they drift invisibly within a release.

Because both modes route on `block_key` (ADR-291 D1, upholding ADR-238 D4a's
measured rejection of segment routing), no keying parameterisation is needed
either. The only difference is how a tote acquires its addresses:

    workforce:  ToteAddress rows  ─► this adapter ─► PackageInput[] ─► run_sort()
    full:       manifest + enrichment ───────────────► PackageInput[] ─► run_sort()

`run_sort` never learns which it was handed.

SYNTHETIC IDENTIFIERS
`PackageInput.tba_number` is required, and route_sort threads it through
`_Tote.tba_numbers`, the bag-grouped stop view, misroute flagging and its own
`__unknown_{tba}` null-block sentinel. A workforce entry has no Amazon TBA, so
one is minted: `WF-{bag_id}-{n}`.

  * deterministic — a re-sort of the same entries yields the same ids, so the
    sort is reproducible;
  * prefixed — it can never be mistaken for a real TBA in a scorecard appeal or
    a future reconciliation against a manifest;
  * unique within its tote — so the `__unknown_` sentinel still separates
    entries that share a bag when geocoding failed.
"""
from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.btr_sheet import BTRBag, BTRSheet
from app.models.tote_address import ToteAddress
from app.models.workforce_ov import WorkforceOV
from app.schemas.walker_routes import PackageInput

logger = logging.getLogger(__name__)

# Marks an identifier this system invented rather than one Amazon issued.
WORKFORCE_TBA_PREFIX = "WF"


def synthetic_tba(bag_id: str, sequence: int) -> str:
    """A stable stand-in identifier for one captain-entered address."""
    return f"{WORKFORCE_TBA_PREFIX}-{bag_id}-{sequence}"


def is_synthetic_tba(tba: str | None) -> bool:
    """True for an id this system minted. Anything reporting to Amazon must check."""
    return bool(tba) and str(tba).startswith(f"{WORKFORCE_TBA_PREFIX}-")


@dataclass
class ToteBlockDisagreement:
    """One tote whose addresses do not agree on a block (ADR-291 D4).

    Real information, not noise: either Amazon bagged loosely, or an address was
    mistyped. Surfaced at ENTRY where it is cheap to fix, rather than discovered
    later as a bad route.
    """
    bag_id: str
    block_keys: list[str]
    winning_block_key: str


@dataclass
class AdapterResult:
    packages: list[PackageInput]
    # Totes physically on the truck with no usable address. NOT dropped — see
    # `unaddressed_bags` below.
    unaddressed_bags: list[str]
    disagreements: list[ToteBlockDisagreement]
    # Entries whose address would not parse into a block_key. They still reach
    # the sort (as __unknown_ sentinels) so the tote is not silently lost.
    unparseable: list[str]
    # ADR-302 D3: totes skipped because a RETAINED route already carries them —
    # out with a walker, or delivered. Distinct from `unaddressed_bags` (nobody
    # has typed an address) and `unparseable` (the address did not resolve).
    # Last because it is the only defaulted field.
    already_routed: list[str] = field(default_factory=list)


def build_packages(
    db: Session,
    company_id: UUID,
    truck_id: UUID,
    entry_date: date,
    exclude_bag_ids: set[str] | None = None,
) -> AdapterResult:
    """Assemble `run_sort` input from a truck's captain-entered addresses.

    Every tote KNOWN to be on the truck is represented. A tote with addresses
    becomes one PackageInput per address; a tote from the BTR sheet with no
    address yet is reported in `unaddressed_bags` for the captain to resolve.

    Dimension 5 — no silent drops. A tote nobody addressed is still physically
    on the truck and must reach a walker, so it is surfaced rather than omitted.
    A sort that quietly loses a tote strands real packages.

    `exclude_bag_ids` (ADR-302 D3) drops totes that are already spoken for by a
    route this re-sort RETAINED — out with a walker, or delivered. Without it a
    re-sort plans a second route for totes that are not in the truck, and a
    walker is sent to find them. They are reported in `already_routed`, NOT
    silently dropped: the same no-silent-drops rule as `unaddressed_bags`, since
    a captain seeing fewer totes than they entered needs to know why.
    """
    addresses = (
        db.query(ToteAddress)
        .filter(
            ToteAddress.company_id == company_id,
            ToteAddress.truck_id == truck_id,
            ToteAddress.entry_date == entry_date,
        )
        .order_by(ToteAddress.bag_id.asc(), ToteAddress.entry_sequence.asc())
        .all()
    )

    # ADR-400 A2 / ADR-404. An addressed OV already arrives here: it has a
    # ToteAddress row keyed by its OV#### id, so the loop below groups it as its
    # own bag. What is missing is its SIZE, and without a size the sort costs it
    # as an ordinary tote — 2 half-slots for everything from an envelope to an
    # XL. That is wrong in both directions: an XS envelope ends a route early
    # (too many routes), and an XL is charged half what it occupies, so the BFS
    # overfills and a walker gets a cart that does not physically hold it.
    ov_sizes: dict[str, str] = {
        ov_id: size
        for ov_id, size in db.query(WorkforceOV.ov_id, WorkforceOV.size)
        .filter(
            WorkforceOV.company_id == company_id,
            WorkforceOV.truck_id == truck_id,
            WorkforceOV.entry_date == entry_date,
            WorkforceOV.size.isnot(None),
        )
        .all()
    }

    by_bag: dict[str, list[ToteAddress]] = {}
    for a in addresses:
        by_bag.setdefault(a.bag_id, []).append(a)

    # ADR-302 D3. Reported, never silently omitted.
    already_routed: list[str] = []
    if exclude_bag_ids:
        already_routed = sorted(b for b in by_bag if b in exclude_bag_ids)
        for b in already_routed:
            by_bag.pop(b, None)

    packages: list[PackageInput] = []
    disagreements: list[ToteBlockDisagreement] = []
    unparseable: list[str] = []

    for bag_id, entries in by_bag.items():
        blocks = [e.block_key for e in entries if e.block_key]

        # ADR-291 D4: surface a split tote at entry. The sort still proceeds.
        #
        # ADR-403: the reported winner weights by PACKAGE COUNT, matching what
        # the sort will actually choose. Counting addresses here while the sort
        # counts packages would report one block and route to another — a
        # disagreement display that itself disagrees.
        #
        # A remaining TIE is reported as the alphabetically-first candidate and
        # may not be the block the sort picks: `resolve_dominant_blocks` breaks
        # ties with the rest of the truck, which this per-tote loop cannot see.
        # That is why the field is `winning_block_key` on a DISAGREEMENT record
        # — it names the leading candidate, and the disagreement is the point.
        if len(set(blocks)) > 1:
            weighted = Counter()
            for e in entries:
                if e.block_key:
                    weighted[e.block_key] += e.package_count or 1
            top = max(weighted.values())
            winner = sorted(b for b, n in weighted.items() if n == top)[0]
            disagreements.append(ToteBlockDisagreement(
                bag_id=bag_id,
                block_keys=sorted(set(blocks)),
                winning_block_key=winner,
            ))

        for i, e in enumerate(entries, start=1):
            if not e.block_key:
                unparseable.append(f"{bag_id}: {e.raw_address or '(no address)'}")

            # ADR-403 D1a. ONE PackageInput PER PACKAGE, not per address.
            #
            # A drop is several packages at one door, and the captain records
            # how many. Emitting one input per address would weight "8 packages
            # to W 36th" the same as "1 to Broadway" — a tie, when the captain
            # has just said it is 8-1. `_Tote.dominant_block_key` counts inputs,
            # so emitting the real number makes the count mean what its name
            # says.
            #
            # It also repairs `Route.package_count`, which ADR-298 records as
            # counting captain-entered ADDRESSES while reading like a parcel
            # count. With this it counts packages — still the captain's figure
            # rather than Flex's, but no longer a different unit wearing the
            # same name.
            for n in range(e.package_count or 1):
                packages.append(PackageInput(
                # Synthetic — see the module docstring. Sequence is 1-based
                # and taken from position within the tote, so it is stable
                # across re-sorts of the same rows. The `n` suffix keeps a
                # drop's packages distinct because downstream code puts these
                # ids in SETS — `flagged_out_tbas` and the misroute id sets in
                # route_sort collapse duplicates, so eight identical ids would
                # report one misroute where eight packages are affected.
                # Verified: there is no dedupe on the sort path itself, so the
                # suffix is for those sets rather than for the counting.
                tba_number=synthetic_tba(bag_id, i) + (f"-{n + 1}" if n else ""),
                bag_id=bag_id,
                block_key=e.block_key,
                normalised_address=e.normalised_address,
                lat=e.lat,
                lng=e.lng,
                first_cross_street=e.first_cross_street,
                second_cross_street=e.second_cross_street,
                # ADR-400 A2. `OV_{size}` for an OV, None for a tote.
                #
                # This is the whole capacity fix and it needs no new arithmetic:
                # `_pair_ovs` already scans for the OV_ prefix and adds
                # OV_HALF_SLOTS[tier], and `_Tote.half_slot_cost`'s all-OV
                # branch already gives a standalone OV its own cost instead of a
                # tote's base 2 — including the XS exemption (ADR-260), which
                # returns 0 rather than flooring at 1 because an envelope
                # genuinely occupies no cart slot.
                #
                # A captain enters geography, not contents, so a TOTE still gets
                # None. The earlier comment here said OV sizing "comes from the
                # BTR sheet, which the caller layers on separately" — no caller
                # ever did, and the sheet carries only zone and count, never a
                # size. The size comes from the captain at address entry.
                package_type=(
                    f"OV_{ov_sizes[bag_id]}" if bag_id in ov_sizes else None
                ),
            ))

    # Excluded totes count as ADDRESSED for this purpose: they are on a retained
    # route, not awaiting a captain. Passing only `by_bag` would resurface them
    # as unaddressed and tell the captain to go address a tote that is currently
    # out with a walker.
    accounted_for = set(by_bag) | set(already_routed)
    unaddressed = _unaddressed_bags(db, company_id, truck_id, entry_date, accounted_for)

    logger.info(
        "workforce_adapter_built",
        extra={
            "company_id": str(company_id),
            "truck_id": str(truck_id),
            "entry_date": entry_date.isoformat(),
            "totes_with_addresses": len(by_bag),
            "packages": len(packages),
            "unaddressed": len(unaddressed),
            "disagreements": len(disagreements),
            "unparseable": len(unparseable),
        },
    )
    return AdapterResult(
        packages=packages,
        unaddressed_bags=unaddressed,
        disagreements=disagreements,
        unparseable=unparseable,
        already_routed=already_routed,
    )


def _unaddressed_bags(
    db: Session,
    company_id: UUID,
    truck_id: UUID,
    entry_date: date,
    addressed: set[str],
) -> list[str]:
    """Bags on the truck's BTR sheet that nobody has addressed yet.

    Returns [] when no sheet was imported — then the addresses ARE the whole
    inventory and nothing is known to be missing. That is a real state, not a
    failure: the BTR sheet is a convenience, not a prerequisite (ADR-291 D5).
    """
    sheet = (
        db.query(BTRSheet)
        .filter(
            BTRSheet.company_id == company_id,
            BTRSheet.truck_id == truck_id,
            BTRSheet.sheet_date == entry_date,
        )
        .first()
    )
    if sheet is None:
        return []

    rows = (
        db.query(BTRBag.bag_id)
        .filter(
            BTRBag.company_id == company_id,
            BTRBag.btr_sheet_id == sheet.id,
        )
        .all()
    )
    return sorted({r[0] for r in rows} - addressed)

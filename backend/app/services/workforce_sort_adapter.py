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

        # ADR-291 D4: surface a split tote at entry. The sort still proceeds —
        # _Tote.dominant_block_key resolves it by majority vote exactly as it
        # does for forty package addresses (D2).
        if len(set(blocks)) > 1:
            winner = Counter(blocks).most_common(1)[0][0]
            disagreements.append(ToteBlockDisagreement(
                bag_id=bag_id,
                block_keys=sorted(set(blocks)),
                winning_block_key=winner,
            ))

        for i, e in enumerate(entries, start=1):
            if not e.block_key:
                unparseable.append(f"{bag_id}: {e.raw_address or '(no address)'}")
            packages.append(PackageInput(
                # Synthetic — see the module docstring. Sequence is 1-based and
                # taken from position within the tote, so it is stable across
                # re-sorts of the same rows.
                tba_number=synthetic_tba(bag_id, i),
                bag_id=bag_id,
                block_key=e.block_key,
                normalised_address=e.normalised_address,
                lat=e.lat,
                lng=e.lng,
                first_cross_street=e.first_cross_street,
                second_cross_street=e.second_cross_street,
                # No package_type: a captain enters a tote's geography, not its
                # contents. OV sizing comes from the BTR sheet (ADR-291 D6),
                # which the caller layers on separately.
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

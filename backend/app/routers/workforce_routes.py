"""Workforce-mode routing: captain enters addresses, sorts, assigns walkers (ADR-291).

The path a workforce tenant actually uses:

    POST   /workforce/tote-addresses          a captain types an address for a tote
    GET    /workforce/tote-addresses/{date}   what has been entered, with disagreements
    DELETE /workforce/tote-addresses/{id}     remove a mistyped entry
    POST   /workforce/commit-sort             build Route rows from those addresses
    PATCH  /workforce/routes/{id}/assign      captain gives a route to a walker  (D8)
    PATCH  /workforce/routes/{id}/package-count  the count Flex showed at scan  (D11)
    POST   /workforce/route-lookup            which route does this address belong to? (D9)

GATED TO WORKFORCE MODE. The mirror of walker_routes, which is gated to `full`.
A tenant with a package feed sorts from the manifest and must not have a second,
weaker path available; a tenant without one has this and nothing else.

The sort itself is NOT here. `workforce_sort_adapter` produces `PackageInput`
records and the genuine `route_sort.run_sort` consumes them unchanged (D5) —
this router is plumbing around an algorithm it does not duplicate.
"""
from __future__ import annotations

import logging
import uuid as _uuid
from datetime import date, datetime, timezone
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import RoleChecker, get_caller_employee
from app.database import get_db
from app.models.assignment_member import AssignmentMember
from app.models.employee import Employee
from app.core.bag_colors import canonical_hex, color_name_for_hex
from app.services.derive_block_key import describe_stored_block
from app.models.btr_sheet import BTRBag, BTRSheet, BTRRoute, BTROVZone
from app.models.workforce_ov import WorkforceOV, OV_SIZES
from app.services.workforce_ov_mint import mint as mint_ov, is_ov_id
from app.models.tote_address import ToteAddress
from app.models.truck_assignment import TruckAssignment
from app.models.walker_route import Route, RouteParticipant
from app.schemas.walker_routes import SortRequest
from app.services.audit import write_audit
from app.services.constants import DELETABLE_ON_RESORT, ROUTE_LEAD_ROLES
from app.services.package_intake import resolve_address
from app.services.route_sort import run_sort
from app.services.workforce_sort_adapter import build_packages

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workforce", tags=["workforce-routes"])

# Same authority as full mode's route work (ADR-256 D5): a captain leads the
# truck's routing, with the driver alongside and dispatch above.
_allow_route_lead = RoleChecker(list(ROUTE_LEAD_ROLES))

# Field staff read their own assignment but never build or assign routes.
_allow_read = RoleChecker(
    list(ROUTE_LEAD_ROLES) + ["walker", "trainer", "trainee"]
)


# ── request schemas (dim 9) ───────────────────────────────────────────────────

class ToteAddressIn(BaseModel):
    """One address a captain typed against one tote, or against one OV."""
    model_config = ConfigDict(extra="forbid")

    truck_id: UUID
    entry_date: date
    # A tote's bag id ("6800") or an OV's ("OV0012"). One field, because an OV
    # takes an address exactly as a tote does — the namespaces cannot collide,
    # since a bag id is bare digits once parse_bag_label strips the colour word.
    bag_id: str = Field(..., min_length=1, max_length=50)
    # A street address. Bounded because it lands in a String(300) column and is
    # attacker-controlled free text.
    raw_address: str = Field(..., min_length=3, max_length=300)

    # ADR-403 D1a. Packages in this tote going to THIS address. `ge=1` matters:
    # a zero would silently drop the block from the vote and a negative would
    # subtract from it. Capped well above any real tote so a fat-fingered entry
    # cannot swamp every other block.
    package_count: int = Field(default=1, ge=1, le=500)

    # ADR-400 A2. Required for an OV, forbidden for a tote — enforced in the
    # validator below rather than by the type, because which one applies depends
    # on another field.
    ov_size: Optional[Literal["XS", "S", "M", "L", "XL"]] = None

    @model_validator(mode="after")
    def _size_matches_the_unit(self) -> "ToteAddressIn":
        """An OV needs a size; a tote must not carry one.

        Both directions are errors rather than one being ignored. A missing OV
        size cannot be defaulted — `OV_HALF_SLOTS` spans 0 to 4 half-slots, so
        guessing "M" silently mis-costs the route in whichever direction the
        guess was wrong. A size on a tote would store a value nothing reads,
        which is how a field acquires a second meaning later.
        """
        if is_ov_id(self.bag_id) and self.ov_size is None:
            raise ValueError(
                "ov_size is required for an OV: the sort cannot cost a route "
                "without it."
            )
        if not is_ov_id(self.bag_id) and self.ov_size is not None:
            raise ValueError("ov_size applies to an OV, not a tote.")
        return self


class CommitWorkforceSortIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    truck_assignment_id: UUID
    route_date: date
    # DEPRECATED (ADR-400 A3). Overflow no longer needs permission — capacity
    # measures rather than enforces, and `overflowed_routes` in the response
    # reports it. Still ACCEPTED rather than removed so an older client sending
    # it gets its sort rather than a 422 on an unexpected key (extra="forbid").
    allow_overflow: bool = False

    # ADR-302 D2a. Re-planning a route someone was told is theirs is an
    # operational act, so the captain says so explicitly. Default is "nothing
    # happens": an assigned route present with no choice supplied is a 409 that
    # NAMES the routes, never a silent re-plan.
    #
    #   None  -> refuse if any route is assigned (the safe default)
    #   [...] -> clear exactly these assigned routes, keep the rest
    #   []    -> with clear_all_assigned=True, clear every assigned route
    clear_assigned_route_ids: Optional[list[UUID]] = Field(default=None, max_length=200)
    clear_all_assigned: bool = False


class AssignWalkerIn(BaseModel):
    """D8 — the captain assigns directly; wave distribution does not run here."""
    model_config = ConfigDict(extra="forbid")

    employee_id: UUID


class FlexPackageCountIn(BaseModel):
    """D11 — the count a captain read off Amazon Flex at scan time."""
    model_config = ConfigDict(extra="forbid")

    # A route is a walking load; 2000 is far above any real one and exists to
    # bound the write, not to express a business rule.
    package_count: int = Field(..., ge=0, le=2000)


class RouteLookupIn(BaseModel):
    """D9 — which of today's routes should carry this address?"""
    model_config = ConfigDict(extra="forbid")

    truck_assignment_id: UUID
    raw_address: str = Field(..., min_length=3, max_length=300)


# ── response schemas ──────────────────────────────────────────────────────────

class ToteAddressOut(BaseModel):
    id: UUID
    bag_id: str
    raw_address: Optional[str] = None
    normalised_address: Optional[str] = None
    block_key: Optional[str] = None
    # The block key as a sentence (ADR-296 D5). Null when the address is gone or
    # no longer parses; the client then shows the raw key, which is what it did
    # before this field existed.
    block_description: Optional[str] = None
    entry_sequence: int
    entered_by_name: Optional[str] = None
    # False when the address could not be parsed into a block_key. The entry is
    # still stored and still sorts — the captain can see and fix it.
    geocoded: bool = True
    # ADR-296 D4: the same colour the picker chip shows, so one physical tote
    # looks identical in both places. Null when the sheet carried no colour word.
    bag_color: Optional[str] = None
    bag_color_name: Optional[str] = None


class ToteDisagreementOut(BaseModel):
    bag_id: str
    block_keys: list[str]
    winning_block_key: str


def _bag_color(by_id: dict, bag_id: str) -> Optional[str]:
    """The sheet's colour hex for a bag, or None when no sheet listed it."""
    row = by_id.get(bag_id)
    return row.bag_color if row is not None else None


def _bags_by_id(
    db: Session, company_id: UUID, truck_id: UUID, entry_date: date,
    bag_ids: list[str],
) -> dict[str, "BTRBag"]:
    """The BTR sheet rows for these bags, keyed by bag id.

    One query for the whole response. Shared by the unaddressed picker and the
    entered-address cards (ADR-296 D4) so the two cannot disagree about a tote's
    colour — they are looking at the same physical bag.
    """
    if not bag_ids:
        return {}
    rows = (
        db.query(BTRBag)
        .join(BTRSheet, BTRSheet.id == BTRBag.btr_sheet_id)
        .filter(
            BTRBag.company_id == company_id,
            BTRSheet.truck_id == truck_id,
            BTRSheet.sheet_date == entry_date,
            BTRBag.bag_id.in_(bag_ids),
        )
        .all()
    )
    return {r.bag_id: r for r in rows}


def _enrich_unaddressed(
    db: Session, company_id: UUID, truck_id: UUID, entry_date: date,
    bag_ids: list[str],
) -> list["UnaddressedBagOut"]:
    """Attach colour and Amazon route to each unaddressed bag, from the sheet.

    One query, not one per bag. Returns bare entries when no BTR sheet exists —
    the bags are then only known because someone typed them, so there is nothing
    to enrich and the client renders neutral pills.
    """
    if not bag_ids:
        return []

    by_id = _bags_by_id(db, company_id, truck_id, entry_date, bag_ids)
    return [
        UnaddressedBagOut(
            bag_id=b,
            # canonical_hex, not the raw stored value: bag_color is written at
            # ingest, so one truck can hold bags from either side of a palette
            # change and would otherwise paint one physical colour two ways.
            bag_color=canonical_hex(by_id[b].bag_color if b in by_id else None),
            bag_color_name=color_name_for_hex(
                by_id[b].bag_color if b in by_id else None
            ),
            amazon_route_name=(by_id[b].amazon_route_name if b in by_id else None),
        )
        for b in bag_ids
    ]


class UnaddressedBagOut(BaseModel):
    """A tote on the truck that nobody has addressed yet."""
    bag_id: str
    # Resolved hex from ADR-230's label parse. Null when the sheet carried no
    # colour word — the client renders a neutral pill rather than inventing one.
    bag_color: Optional[str] = None
    # The colour WORD ("orange"), derived server-side from the hex so the client
    # can label and search by it. A hex alone is unsearchable — nobody types
    # "#F97316", they type "orange", which is what they are looking at.
    bag_color_name: Optional[str] = None
    # Which Amazon route the sheet listed it under. Reference only (ADR-290 D7):
    # our sort re-partitions freely. NOT a grouping key for the captain — they
    # cannot tell which Amazon route a physical tote belongs to by looking at it.
    amazon_route_name: Optional[str] = None


class ToteAddressListOut(BaseModel):
    addresses: list[ToteAddressOut]
    # D4: totes whose addresses point at different blocks — loose bagging or a
    # typo. Surfaced at entry where it is cheap to fix.
    disagreements: list[ToteDisagreementOut]
    # Totes the BTR sheet says are on the truck that nobody has addressed.
    unaddressed_bags: list[str]
    # ADR-291: the SAME bags, enriched from the BTR sheet (ADR-290).
    #
    # A flat id list is unusable at real scale — a 25-tote truck renders 25
    # identical four-digit chips and the captain hunts for one. Colour and
    # Amazon route are how a tote is actually found in a physical stack, and the
    # sheet already carries both, so withholding them makes the client guess.
    #
    # `unaddressed_bags` is kept alongside for any caller that only needs ids.
    unaddressed: list["UnaddressedBagOut"] = []


class RouteParticipantOut(BaseModel):
    """One person on a route (ADR-212).

    Exactly one `executor` — the walker, or the trainee in a training pair —
    plus zero-or-more `supervisor` (their trainer). A pair is therefore two rows
    on one route, which is what the captain sees on the floor and what the
    flattened `assigned_to_name` cannot express.
    """
    employee_id: UUID
    name: Optional[str] = None
    role: str                        # executor | supervisor


class WorkforceRouteOut(BaseModel):
    id: UUID
    route_number: int
    tote_ids: list[str]
    block_keys: list[str]
    package_count: int
    slot_cost: int
    capacity_limit: int
    overflow_half_slots: int
    status: str
    assigned_to: Optional[UUID] = None
    assigned_to_name: Optional[str] = None
    # D11. NULL = not recorded yet; 0 = genuinely carried nothing. package_count
    # above counts captain-entered ADDRESSES, which is not a parcel count.
    flex_package_count: Optional[int] = None

    # ADR-402 D2 — the mid-day view needs to say when a route left and came
    # back. Both are stored on Route already and were simply never returned.
    # Duration is DERIVED from the pair client-side: a stored duration would be
    # a second source for a fact these two timestamps already fix.
    departed_at: Optional[datetime] = None
    returned_at: Optional[datetime] = None
    # Every person on the route, not just the executor's flattened name.
    participants: list[RouteParticipantOut] = []

    # ADR-406 D1. "assigned" (take it now) or "reserved" (yours, but you are
    # carrying something else). Null when nobody holds it. Derived at read time
    # from whether the holder has a route out — never stored, because the flip
    # from reserved to assigned happens when ANOTHER route closes and has no
    # event of its own.
    assignment_kind: Optional[str] = None

    # `wave_number` is deliberately ABSENT (ADR-402 D3). It reads as a truck-wide
    # cycle and is a monotonic counter of re-issues across the truck, so a
    # walker's FIRST re-issue can be labelled wave 3. `AssignmentMember.trip_count`
    # is the honest per-person measure. A field absent from the payload cannot be
    # rendered by accident.


class TruckDayTotalsOut(BaseModel):
    """The truck-day's persisted record (ADR-299 D1/D4).

    OURS, not Amazon's. The morning reference (Amazon's BTR sums, surfaced on
    the Discord board) is a different number from a different source, and the
    two are deliberately never reconciled: a gap between them is operationally
    meaningful — packages that never made it onto a route, a wrong sheet, a tote
    nobody addressed.
    """
    route_date: date
    truck_assignment_id: UUID

    routes_total: int
    routes_closed: int

    # D4: sum of flex_package_count over the truck's routes. NULL — never a
    # partial sum — while any closed route is still unscanned: summing three of
    # five silently reports a smaller truck. The unrecorded count is both the
    # honest caveat and the operational nudge.
    packages_carried: Optional[int] = None
    routes_missing_flex_count: int = 0

    # `Route.package_count` appears nowhere: it counts captain-entered ADDRESSES
    # (ADR-298), and a field absent from the payload cannot be rendered by
    # accident.


class LoadRosterToteOut(BaseModel):
    """One tote the BTR sheet says belongs on this truck (ADR-307 D1a)."""
    bag_id: str
    # ADR-296's swatch rules apply unchanged — the driver is matching a physical
    # bag, so the colour is the find and the number confirms it.
    bag_color: Optional[str] = None
    bag_color_name: Optional[str] = None
    # Reference only: which Amazon route the sheet listed it under. NOT a
    # grouping key — a driver cannot tell a tote's Amazon route by looking.
    amazon_route_name: Optional[str] = None
    # ADR-405. Where the station staged this bag, e.g. "H-9.1E". The DRIVER's
    # field: it answers "where do I walk to find it", which colour alone cannot.
    # Null when the sheet predates the column or omits it.
    sort_zone: Optional[str] = None

    checked: bool = False
    checked_by_name: Optional[str] = None
    checked_at: Optional[datetime] = None


class WorkforceOVOut(BaseModel):
    """One oversized package on this truck-day (ADR-400 A4)."""
    ov_id: str
    # A5a: the DRIVER's field. Where the station staged it, for the person
    # loading the truck at 06:00. Null for a milk-run item, which never had one.
    zone_label: Optional[str] = None
    # Null until the captain measures it. The sort cannot cost the route without
    # it, so it is asked for at address entry rather than guessed.
    size: Optional[str] = None
    source: str                       # sheet | milk_run | captain
    # Null = expected from the sheet, not yet in hand. A presence fact, never a
    # loss claim (A5c).
    confirmed_at: Optional[datetime] = None
    addressed: bool = False


class AddOVIn(BaseModel):
    """A6a. An OV that is on the truck but not on the sheet."""
    model_config = ConfigDict(extra="forbid")

    truck_assignment_id: UUID
    entry_date: date
    # A6c. The CLIENT suggests from timing — the workday start is known, so an
    # OV added 3+ hours later is almost certainly a milk-run — and the captain
    # confirms. The SERVER never infers: a guessed origin would be unauditable,
    # since no later reader could tell an inference from a statement.
    #
    # "system" is reserved for automated creation and is rejected here: a
    # human-facing endpoint must not be able to claim a row was machine-made.
    source: Literal["milk_run", "captain"]
    # Optional. A milk-run item has no station zone, and a captain adding one
    # off the truck floor usually does not know it either.
    zone_label: Optional[str] = Field(default=None, max_length=30)


class SeedOVsOut(BaseModel):
    """What seeding found, and what it added."""
    expected: int          # OVs the sheet says belong on this truck
    created: int           # newly minted this call
    already_present: int   # already seeded — this endpoint is idempotent
    no_sheet: bool = False


class LoadRosterOut(BaseModel):
    """What SHOULD be on the truck, and what the driver has confirmed.

    One call answers both halves, because the driver's question is a comparison:
    "the sheet says 25 totes — which do I actually have?"
    """
    load_date: date
    truck_assignment_id: UUID
    btr_loading_zone: Optional[str] = None

    totes: list[LoadRosterToteOut] = []
    total: int = 0
    checked_count: int = 0

    # ADR-307 D1b: unchecked totes are REPORTED, never converted into removals.
    # Full mode turns an unchecked tote into a PackageRemoval because the
    # manifest says what was inside it. Workforce mode knows the bag id and its
    # colour and nothing else, so this is a presence count — not a claim about
    # what was lost.
    unchecked_count: int = 0

    # ADR-400 A5. OVs are their own units, not bags, so they are a separate list
    # rather than more entries in `totes` — a driver counting "25 totes" must not
    # find OVs inflating that number.
    #
    # Ordered ZONE THEN ID: the driver's task is spatial. Every B-27.2Y item
    # together, then B-27.3X, matching the walk through the station rather than
    # the order the ids were minted.
    ovs: list[WorkforceOVOut] = []
    ov_total: int = 0
    # Expected from the sheet, not yet in hand. Reported, never a loss claim —
    # the same treatment `unchecked_count` gets for totes (ADR-307 D1b), and it
    # never blocks the day close (A5c).
    ov_unconfirmed_count: int = 0

    # True when no BTR sheet was imported: the tote list is then unknowable, and
    # an empty roster must not read as "the truck is empty".
    no_sheet: bool = False


class ToteCheckIn(BaseModel):
    """Dimension 9: one bool, bounded, no free text."""
    model_config = ConfigDict(extra="forbid")

    truck_assignment_id: UUID
    checked: bool


class MyRouteToteOut(BaseModel):
    """One tote on the walker's route (ADR-297 D3).

    The TOTE is the unit of work here, not the stop. Full mode's walker works a
    list of stops and the tote is incidental packaging; in workforce mode the
    captain's entry unit was the tote, the sort's input was the tote, and the
    thing the walker physically picks up is the tote.
    """
    bag_id: str
    # ADR-296's swatch rules apply unchanged: a physical-object swatch, ringed,
    # theme-fixed. Null renders a neutral pill rather than inventing a colour.
    bag_color: Optional[str] = None
    bag_color_name: Optional[str] = None
    # The blocks this tote's addresses derived to, as sentences where possible
    # (ADR-296 D5) and as raw keys where the address is gone (ADR-219 nulling).
    block_keys: list[str] = []
    block_descriptions: list[str] = []


class ReservedRouteOut(BaseModel):
    """A route held for this walker, shown as reserved and never as startable.

    The depart endpoint already refuses a route whose status is not `assigned`,
    so a reserved route could not be started anyway — this keeps the SCREEN
    honest about a rule the server enforces, rather than offering an action that
    would 409.
    """
    route_id: UUID
    route_number: int
    tote_count: int
    # Block descriptions, never addresses: `block_key` survives the ADR-219
    # purge precisely because it is not PII (dim 7).
    block_keys: list[str] = []


class MyRouteOut(BaseModel):
    """The walker's own route for a day (ADR-297).

    D6: ONE shape whether or not a route exists. `no_route_assigned` is an
    explicit field rather than a 404, because a walker with no route is a normal
    state on a normal day — they are on a truck, not yet assigned — and a 404
    would force the client to distinguish that from "the endpoint is missing",
    which is the confusion RequireMode's 404 already occupies.
    """
    no_route_assigned: bool = False
    # ADR-406 D2. Routes waiting for this walker while they carry the one above.
    # Enough to know what is coming and where, without duplicating a full route
    # view for something they cannot start yet.
    reserved_routes: list["ReservedRouteOut"] = []
    route_id: Optional[UUID] = None
    route_number: Optional[int] = None
    status: Optional[str] = None
    truck_name: Optional[str] = None

    # D3: what the walker is carrying, and the ground it covers.
    totes: list[MyRouteToteOut] = []
    block_keys: list[str] = []

    # D5/D6: the REAL parcel count (ADR-291 D11), NULL until a captain records
    # it at scan time. Never 0 as a stand-in — 0 means "carried nothing".
    # `package_count` is deliberately absent from this payload entirely: in
    # workforce mode it counts captain-entered ADDRESSES, and a field that is
    # not in the response cannot be rendered by accident.
    flex_package_count: Optional[int] = None

    # Lifecycle (ADR-300). departed_at set + returned_at null IS "in progress".
    departed_at: Optional[datetime] = None
    returned_at: Optional[datetime] = None


class CommitWorkforceSortOut(BaseModel):
    routes: list[WorkforceRouteOut]
    # ADR-302 D3. Totes skipped because a RETAINED route already carries them.
    # NOT the same as `unaddressed_bags` — these are accounted for, and someone
    # is either carrying them right now or already delivered them.
    already_routed_bags: list[str] = []
    retained_routes: int = 0
    totes_sorted: int
    # Reported, never silently dropped (dim 5).
    unaddressed_bags: list[str]
    unparseable: list[str]
    disagreements: list[ToteDisagreementOut]
    overflowed_routes: int


class RouteLookupCandidate(BaseModel):
    route_id: UUID
    route_number: int
    # exact_block | adjacent_block | same_street. Absent from the list entirely
    # when nothing matched — the caller escalates to dispatch (D9).
    match: str
    block_key: Optional[str] = None
    assigned_to_name: Optional[str] = None


class RouteLookupOut(BaseModel):
    block_key: Optional[str] = None
    candidates: list[RouteLookupCandidate]
    # True when nothing matched: the captain escalates rather than guessing.
    escalate: bool


# ── helpers ───────────────────────────────────────────────────────────────────

def _assert_truck_member(caller: Employee, truck_id: UUID, entry_date: date,
                         db: Session) -> None:
    """A captain/driver may only touch their own truck (dim 2, object-level).

    Dispatch and above are station-side and see every truck, matching
    walker_routes._assert_truck_scope rather than inventing a second rule.
    """
    if caller.role in ("dispatch", "management", "admin", "field_supervisor"):
        return
    member = (
        db.query(AssignmentMember)
        .join(TruckAssignment, TruckAssignment.id == AssignmentMember.assignment_id)
        .filter(
            TruckAssignment.company_id == caller.company_id,
            TruckAssignment.truck_id == truck_id,
            TruckAssignment.date == entry_date,
            AssignmentMember.employee_id == caller.id,
            AssignmentMember.company_id == caller.company_id,
        )
        .first()
    )
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not assigned to this truck.",
        )


def _assignment(db: Session, caller: Employee, assignment_id: UUID) -> TruckAssignment:
    ta = (
        db.query(TruckAssignment)
        .filter(
            TruckAssignment.id == assignment_id,
            TruckAssignment.company_id == caller.company_id,
        )
        .first()
    )
    if ta is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Truck assignment not found.")
    return ta


# ── tote addresses ────────────────────────────────────────────────────────────

@router.post("/tote-addresses", response_model=ToteAddressOut,
             status_code=status.HTTP_201_CREATED)
def add_tote_address(
    payload: ToteAddressIn,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_route_lead),
    db: Session = Depends(get_db),
):
    """Record one delivery address for one tote.

    One address per tote is the minimum; more are welcome and vote via the
    existing `_Tote.dominant_block_key` majority (D2). The address is geocoded
    now so a failure surfaces while the captain is still standing at the tote,
    not at sort time.

    A geocode failure does NOT reject the entry. `resolve_address` never raises,
    and a tote with an unparseable address is still physically on the truck —
    storing it with a null block_key keeps it visible and fixable, whereas
    refusing it would lose the tote entirely (dim 5).
    """
    _assert_truck_member(caller, payload.truck_id, payload.entry_date, db)

    resolved = resolve_address(
        db=db,
        company_id=caller.company_id,
        raw_address=payload.raw_address,
        # resolve_address labels an unparseable address with this. No Amazon TBA
        # exists here, so the bag identifies it — which is what a captain would
        # be looking for anyway.
        tba=f"tote:{payload.bag_id}",
    )

    # Server-assigned, never client-supplied: ties break by first-entered so a
    # re-sort is stable (D2).
    next_seq = (
        db.query(ToteAddress)
        .filter(
            ToteAddress.company_id == caller.company_id,
            ToteAddress.truck_id == payload.truck_id,
            ToteAddress.entry_date == payload.entry_date,
            ToteAddress.bag_id == payload.bag_id,
        )
        .count()
    ) + 1

    # ADR-400 A2. An OV must EXIST before it can be addressed — seeded from the
    # sheet or added by the captain — because its id is minted, not typed. A
    # bare 404 would read as "wrong address"; this names the actual problem.
    ov_row = None
    if is_ov_id(payload.bag_id):
        ov_row = (
            db.query(WorkforceOV)
            .filter(
                WorkforceOV.company_id == caller.company_id,
                WorkforceOV.truck_id == payload.truck_id,
                WorkforceOV.entry_date == payload.entry_date,
                WorkforceOV.ov_id == payload.bag_id,
            )
            .first()
        )
        if ov_row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    f"{payload.bag_id} is not on this truck today. Add the OV "
                    f"first, then give it an address."
                ),
            )
        # One package, one address (A2). A tote takes several that vote on its
        # block; an OV has nothing to vote about, so a second address is a
        # mistake rather than more evidence.
        if next_seq > 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"{payload.bag_id} already has an address.",
            )

    row = ToteAddress(
        company_id=caller.company_id,
        truck_id=payload.truck_id,
        entry_date=payload.entry_date,
        bag_id=payload.bag_id,
        raw_address=payload.raw_address,
        package_count=payload.package_count,
        normalised_address=resolved.normalised_address,
        block_key=resolved.block_key,
        lat=resolved.lat,
        lng=resolved.lng,
        # Cross streets are deliberately NOT set here. ResolvedAddress does not
        # carry them (verified — it has lat/lng/normalised_address/block_key/
        # segment_id/geocoded and nothing else), so a getattr fallback would
        # write None forever while looking like a populated field.
        #
        # Consequence, stated rather than hidden: route_sort's cross-street
        # adjacency edges (cost 1) do not form in workforce mode, and the graph
        # falls back to same-street (2) and parallel (3) edges. Those are the
        # edges ADR-238 measured as the correct constraint anyway; a sparser
        # graph here means tighter routes, not broken ones.
        entry_sequence=next_seq,
        entered_by=caller.id,
        entered_by_name=(caller.name or "")[:100],
    )
    # ADR-403 D1a. The OV's size lives on the OV, not on the address: an address
    # row is identical for both units, and a size column there would be
    # meaningless for the great majority of rows.
    if ov_row is not None:
        ov_row.size = payload.ov_size
        # Addressing an OV means it is physically in hand, so confirm it if the
        # driver never did. A5c keeps confirmation reportable rather than
        # blocking, and this closes the case where a captain addresses an OV the
        # driver forgot to tick off.
        if ov_row.confirmed_at is None:
            ov_row.confirmed_at = datetime.now(timezone.utc)
            ov_row.confirmed_by = caller.id

    db.add(row)
    # ADR-403 D2. `uq_tote_addresses_bag_address` forbids the same address twice
    # for one tote, and the endpoint did not catch the violation — a captain
    # double-tapping on a phone got a 500.
    #
    # It is REFUSED rather than counted. Under D1a a duplicate would otherwise be
    # a way to weight the vote without saying so, and `package_count` is the
    # honest way to express "several packages here".
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError:
        existing = (
            db.query(ToteAddress)
            .filter(
                ToteAddress.company_id == caller.company_id,
                ToteAddress.truck_id == payload.truck_id,
                ToteAddress.entry_date == payload.entry_date,
                ToteAddress.bag_id == payload.bag_id,
                ToteAddress.raw_address == payload.raw_address,
            )
            .first()
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"That address is already recorded for {payload.bag_id}"
                + (f" (entry {existing.entry_sequence})." if existing else ".")
                + " Use the package count if several packages go there."
            ),
        )
    write_audit(
        db=db,
        company_id=str(caller.company_id),
        actor_id=str(caller.id),
        action_type="tote_address.create",
        target_table="tote_addresses",
        target_id=str(row.id),
        # No address in the audit detail (dim 7) — block_key is the durable,
        # non-identifying fact and is what the sort acts on.
        detail={
            "bag_id": payload.bag_id,
            "block_key": resolved.block_key,
            "geocoded": resolved.block_key is not None,
        },
    )
    db.commit()
    db.refresh(row)

    return ToteAddressOut(
        id=row.id, bag_id=row.bag_id, raw_address=row.raw_address,
        normalised_address=row.normalised_address, block_key=row.block_key,
        entry_sequence=row.entry_sequence, entered_by_name=row.entered_by_name,
        geocoded=row.block_key is not None,
    )


class MyTruckOut(BaseModel):
    """Which truck this caller is crewed on for a date.

    A captain should not have to pick their own truck out of a list — they are
    standing next to it. Dispatch legitimately has none (they are station-side),
    and that is a real answer rather than an error, which is why `truck_id` is
    nullable instead of this 404ing.
    """
    truck_id: Optional[UUID] = None
    truck_name: Optional[str] = None
    no_truck_assigned: bool = False


@router.get("/my-truck/{entry_date}", response_model=MyTruckOut)
def my_truck(
    entry_date: date,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_read),
    db: Session = Depends(get_db),
):
    """The truck this caller is crewed on, so the client need not ask them.

    Mirrors building_profiles.buildings_for_truck's resolution rather than
    inventing a second rule for the same question.
    """
    from app.models.truck import Truck

    row = (
        db.query(TruckAssignment, Truck)
        .join(AssignmentMember, AssignmentMember.assignment_id == TruckAssignment.id)
        .join(Truck, Truck.id == TruckAssignment.truck_id)
        .filter(
            TruckAssignment.company_id == caller.company_id,
            TruckAssignment.date == entry_date,
            AssignmentMember.employee_id == caller.id,
            AssignmentMember.company_id == caller.company_id,
        )
        .first()
    )
    if row is None:
        return MyTruckOut(no_truck_assigned=True)
    ta, truck = row
    return MyTruckOut(truck_id=truck.id, truck_name=truck.name)


@router.get("/tote-addresses/{entry_date}", response_model=ToteAddressListOut)
def list_tote_addresses(
    entry_date: date,
    truck_id: UUID,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_read),
    db: Session = Depends(get_db),
):
    """Everything entered for a truck-day, plus what still needs attention."""
    _assert_truck_member(caller, truck_id, entry_date, db)

    rows = (
        db.query(ToteAddress)
        .filter(
            ToteAddress.company_id == caller.company_id,
            ToteAddress.truck_id == truck_id,
            ToteAddress.entry_date == entry_date,
        )
        .order_by(ToteAddress.bag_id.asc(), ToteAddress.entry_sequence.asc())
        .all()
    )
    built = build_packages(db, caller.company_id, truck_id, entry_date)

    # One lookup for every bag that has an address, so each entered card can show
    # the same colour pill as the picker chip (ADR-296 D4).
    entered_bags = _bags_by_id(
        db, caller.company_id, truck_id, entry_date,
        sorted({r.bag_id for r in rows}),
    )

    return ToteAddressListOut(
        addresses=[
            ToteAddressOut(
                id=r.id, bag_id=r.bag_id, raw_address=r.raw_address,
                normalised_address=r.normalised_address, block_key=r.block_key,
                block_description=describe_stored_block(
                    r.normalised_address or r.raw_address, r.block_key
                ),
                entry_sequence=r.entry_sequence, entered_by_name=r.entered_by_name,
                geocoded=r.block_key is not None,
                bag_color=canonical_hex(_bag_color(entered_bags, r.bag_id)),
                bag_color_name=color_name_for_hex(_bag_color(entered_bags, r.bag_id)),
            )
            for r in rows
        ],
        disagreements=[
            ToteDisagreementOut(bag_id=d.bag_id, block_keys=d.block_keys,
                                winning_block_key=d.winning_block_key)
            for d in built.disagreements
        ],
        unaddressed_bags=built.unaddressed_bags,
        unaddressed=_enrich_unaddressed(
            db, caller.company_id, truck_id, entry_date, built.unaddressed_bags
        ),
    )


@router.delete("/tote-addresses/{address_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tote_address(
    address_id: UUID,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_route_lead),
    db: Session = Depends(get_db),
):
    """Remove a mistyped entry.

    A hard delete, not a soft one: this is a typo being corrected within the
    shift, and a tombstone would still vote in `dominant_block_key` unless every
    read learned to filter it. Correcting a mistake must not need a second rule.
    """
    row = (
        db.query(ToteAddress)
        .filter(
            ToteAddress.id == address_id,
            ToteAddress.company_id == caller.company_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Address entry not found.")
    _assert_truck_member(caller, row.truck_id, row.entry_date, db)

    write_audit(
        db=db,
        company_id=str(caller.company_id),
        actor_id=str(caller.id),
        action_type="tote_address.delete",
        target_table="tote_addresses",
        target_id=str(row.id),
        detail={"bag_id": row.bag_id, "block_key": row.block_key},
    )
    db.delete(row)
    db.commit()
    return None


# ── the sort ──────────────────────────────────────────────────────────────────

@router.post("/commit-sort", response_model=CommitWorkforceSortOut,
             status_code=status.HTTP_201_CREATED)
def commit_workforce_sort(
    payload: CommitWorkforceSortIn,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_route_lead),
    db: Session = Depends(get_db),
):
    """Build Route rows from captain-entered addresses.

    The adapter produces PackageInput records and the GENUINE `run_sort`
    consumes them (D5) — no forked algorithm, no keying parameterisation, because
    both modes route on block_key (D1).

    Re-running REPLACES this truck-day's routes, matching full mode's commit-sort.
    Routes already assigned or in progress block the re-run rather than being
    silently discarded: a walker holding a route must not have it deleted
    underneath them.
    """
    ta = _assignment(db, caller, payload.truck_assignment_id)
    _assert_truck_member(caller, ta.truck_id, payload.route_date, db)

    existing = (
        db.query(Route)
        .filter(
            Route.company_id == caller.company_id,
            Route.truck_assignment_id == ta.id,
            Route.route_date == payload.route_date,
        )
        .all()
    )
    # ADR-302 D2. WHAT MAY BE RE-PLANNED IS DECIDED BY WHERE THE TOTES ARE.
    #
    # The old guard asked "is someone holding this route" and blocked on both
    # `assigned` and `in_progress`. That was inverted on both counts:
    #
    #   assigned    -> the totes are still IN THE TRUCK. Nothing has moved; it is
    #                  a name attached to a plan, and re-planning it is exactly
    #                  what a captain re-sorting intends.
    #   in_progress -> `departed_at` is stamped. The walker has physically LEFT
    #                  with those totes; no re-sort can reach them.
    #   completed   -> delivered; the record is final (and six tables CASCADE off
    #                  `routes`, see ADR-304).
    #
    # So in_progress/completed are FILTERED OUT — excluded from the operation —
    # rather than refused. Blocking on `in_progress` defeats the purpose of a
    # mid-day re-sort, which exists precisely because some walkers are already
    # out.
    #
    # An allow-list, not a block-list: a status added later defaults to
    # PROTECTED. (ADR-304 is the same defect in full mode's commit-sort, where a
    # block-list let `completed` silently become deletable.)
    replaceable = [r for r in existing if r.status in DELETABLE_ON_RESORT]
    assigned    = [r for r in existing if r.status == "assigned"]
    out_of_reach = [
        r for r in existing
        if r.status not in DELETABLE_ON_RESORT and r.status != "assigned"
    ]

    # D2a: clearing an assigned route is a DECISION, never a side effect.
    if payload.clear_all_assigned:
        to_clear = list(assigned)
    elif payload.clear_assigned_route_ids:
        wanted = set(payload.clear_assigned_route_ids)
        to_clear = [r for r in assigned if r.id in wanted]
        unknown = wanted - {r.id for r in to_clear}
        if unknown:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    f"{len(unknown)} route(s) to clear are not assigned routes on "
                    f"this truck-day."
                ),
            )
    else:
        to_clear = []

    keeping_assigned = [r for r in assigned if r not in to_clear]
    if keeping_assigned:
        # Names them: "this walker is busy" is useless without "...on route 4".
        numbers = ", ".join(str(r.route_number) for r in sorted(
            keeping_assigned, key=lambda r: r.route_number or 0))
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Route(s) {numbers} are assigned to a walker. Clear them "
                f"explicitly to re-plan them, or re-sort without them."
            ),
        )

    stale = replaceable + to_clear
    retained = out_of_reach

    # ADR-302 D3. FILTERING THE ROUTES IS NOT ENOUGH — their totes must go too.
    #
    # build_packages reads ToteAddress and knows nothing about routes. Retain a
    # route without excluding its totes and the re-sort plans a SECOND route for
    # them: for `in_progress` that means sending a walker after totes another
    # walker is physically carrying, and for `completed` after totes already
    # delivered. That is worse than the deletion this guards, because it looks
    # like it worked.
    spoken_for: set[str] = {b for r in retained for b in (r.tote_ids or [])}

    built = build_packages(
        db, caller.company_id, ta.truck_id, payload.route_date,
        exclude_bag_ids=spoken_for or None,
    )
    if not built.packages:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="No tote addresses entered for this truck and date.",
        )

    result = run_sort(
        request=SortRequest(
            truck_assignment_id=ta.id,
            route_date=payload.route_date,
            packages=built.packages,
        ),
        address_workloads={},
        block_workloads={},
        difficulty_flags={},
    )

    # D7: a route over its lock is allowed but must be recorded. Computed from
    # what the sort produced rather than trusted from the client.
    #
    # ADR-400 A3 — capacity MEASURES, it does not ENFORCE. This block used to
    # 409 unless the client re-sent with allow_overflow=true. That gate was
    # never in D7, which asked only that overflow be *visible* (citing ADR-273:
    # routes closing for unrecorded reasons are invisible in production).
    #
    # It is removed because a cart's stated capacity is an estimate of a
    # physical object people routinely beat — a walker stacks above the cover,
    # hangs a light bag off the handle, carries an envelope. Those are normal
    # days. A confirmation nobody can meaningfully refuse gets clicked through
    # every time, and that habit erodes the confirmations that do matter.
    #
    # The NUMBERS still matter, and matter more without the gate: slot_cost,
    # capacity_limit and overflow_half_slots are the only record of what a
    # walker actually carried versus what a cart nominally holds. An enforced
    # cap produces no such data — every route sits under the limit by
    # construction, and the variance worth learning from is exactly what the
    # cap suppressed.
    overflowed = 0
    for r in result.routes:
        over = max(0, (r.slot_cost or 0) - (r.capacity_limit or 0))
        if over:
            overflowed += 1

    for old in stale:
        db.delete(old)
    db.flush()

    # ADR-302 D6 (mirrors ADR-304 D6): a re-sort that destroys rows says so.
    if stale:
        write_audit(
            db=db,
            company_id=str(caller.company_id),
            actor_id=str(caller.id),
            action_type="workforce_route.resort_replaced",
            target_table="routes",
            target_id=str(ta.id),
            detail={
                "deleted_route_ids": [str(r.id) for r in stale],
                "deleted_count": len(stale),
                "cleared_assigned_count": len(to_clear),
                "retained_count": len(retained),
                "route_date": payload.route_date.isoformat(),
            },
        )

    # ADR-302 D3a. run_sort always numbers from 1 and
    # `uq_routes_assignment_number` is UNIQUE on (truck_assignment_id,
    # route_number) — so emitting 1..n beside a retained route 1 raises
    # IntegrityError and fails the whole re-sort. Continue past the survivors.
    number_offset = max((r.route_number or 0) for r in retained) if retained else 0

    created: list[Route] = []
    for r in result.routes:
        over = max(0, (r.slot_cost or 0) - (r.capacity_limit or 0))
        route = Route(
            company_id=caller.company_id,
            truck_assignment_id=ta.id,
            route_date=payload.route_date,
            route_number=r.route_number + number_offset,   # ADR-302 D3a
            block_keys=r.block_keys,
            # No segments in workforce mode (D10) and no per-stop data, so these
            # are empty rather than fabricated.
            segment_ids=[],
            tote_ids=r.tote_ids,
            tba_numbers=r.tba_numbers,      # synthetic WF- ids, see the adapter
            normalised_addresses=[],        # addresses stay on ToteAddress (ADR-219)
            stops=None,                     # stop granularity does not exist here
            package_count=r.package_count,
            slot_cost=r.slot_cost,
            capacity_limit=r.capacity_limit,
            effort_class=r.effort_class,
            workload_source=r.workload_source,
            status="unassigned",
            seed_block_key=r.seed_block_key,
            blocks_walked=r.blocks_walked,
            closed_reason="overflow" if over else r.closed_reason,
            overflow_half_slots=over,
        )
        db.add(route)
        created.append(route)

    db.flush()
    write_audit(
        db=db,
        company_id=str(caller.company_id),
        actor_id=str(caller.id),
        action_type="workforce_sort.commit",
        target_table="routes",
        target_id=str(ta.id),
        detail={
            "route_date": payload.route_date.isoformat(),
            "routes_created": len(created),
            "routes_replaced": len(existing),
            "totes": len({p.bag_id for p in built.packages}),
            "overflowed_routes": overflowed,
            "unaddressed_bags": len(built.unaddressed_bags),
            "unparseable": len(built.unparseable),
        },
    )
    db.commit()
    for route in created:
        db.refresh(route)

    # ADR-402 D2. A freshly committed route has no participants yet, but the
    # lookup is done rather than assumed: commit-sort RETAINS in_progress routes
    # (ADR-302 D2), and a retained route very much has an executor.
    parts = _participants(db, caller.company_id, created)
    kinds = _assignment_kind(db, caller.company_id, created)   # ADR-406 D1

    return CommitWorkforceSortOut(
        routes=[
            WorkforceRouteOut(
                id=r.id, route_number=r.route_number, tote_ids=list(r.tote_ids or []),
                block_keys=list(r.block_keys or []), package_count=r.package_count,
                slot_cost=r.slot_cost, capacity_limit=r.capacity_limit,
                overflow_half_slots=r.overflow_half_slots, status=r.status,
                flex_package_count=r.flex_package_count,
                departed_at=r.departed_at, returned_at=r.returned_at,
                participants=parts.get(r.id, []),
                assignment_kind=kinds.get(r.id),
            )
            for r in created
        ],
        already_routed_bags=built.already_routed,      # ADR-302 D3
        retained_routes=len(retained),
        totes_sorted=len({p.bag_id for p in built.packages}),
        unaddressed_bags=built.unaddressed_bags,
        unparseable=built.unparseable,
        disagreements=[
            ToteDisagreementOut(bag_id=d.bag_id, block_keys=d.block_keys,
                                winning_block_key=d.winning_block_key)
            for d in built.disagreements
        ],
        overflowed_routes=overflowed,
    )


@router.post("/ovs/{entry_date}/{ov_id}/confirm", response_model=WorkforceOVOut)
def confirm_ov(
    entry_date: date,
    ov_id: str,
    truck_assignment_id: UUID,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_route_lead),
    db: Session = Depends(get_db),
):
    """The OV the sheet expected is physically in hand (ADR-400 A5c).

    Deliberately separate from address entry, though both touch the same row.
    They are different people at different hours: the DRIVER confirms while
    loading at the station, and the CAPTAIN addresses it later at the truck.
    Folding confirmation into addressing would mean an OV could not be counted
    as present until someone knew where it was going.

    Re-confirmable rather than a one-way stamp with a 409. A confirmation
    describes a current physical fact, and there is nothing to protect: no
    downstream record is frozen by it, unlike `returned_at` or a Flex count. A
    second tap re-stamps the time and the person, which is more useful than an
    error.
    """
    ta = _assignment(db, caller, truck_assignment_id)
    _assert_truck_member(caller, ta.truck_id, entry_date, db)

    ov = (
        db.query(WorkforceOV)
        .filter(
            WorkforceOV.company_id == caller.company_id,
            WorkforceOV.truck_id == ta.truck_id,
            WorkforceOV.entry_date == entry_date,
            WorkforceOV.ov_id == ov_id,
        )
        .first()
    )
    if ov is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{ov_id} is not on this truck today.",
        )

    ov.confirmed_at = datetime.now(timezone.utc)
    ov.confirmed_by = caller.id

    db.flush()
    write_audit(
        db=db,
        company_id=str(caller.company_id),
        actor_id=str(caller.id),
        action_type="workforce_ov.confirm",
        target_table="workforce_ovs",
        target_id=str(ov.id),
        detail={"ov_id": ov.ov_id, "zone_label": ov.zone_label},
    )
    db.commit()
    db.refresh(ov)

    addressed = (
        db.query(ToteAddress.id)
        .filter(
            ToteAddress.company_id == caller.company_id,
            ToteAddress.truck_id == ta.truck_id,
            ToteAddress.entry_date == entry_date,
            ToteAddress.bag_id == ov.ov_id,
        )
        .first()
        is not None
    )
    return WorkforceOVOut(
        ov_id=ov.ov_id, zone_label=ov.zone_label, size=ov.size,
        source=ov.source, confirmed_at=ov.confirmed_at, addressed=addressed,
    )


def _ovs_for_truck_day(
    db: Session, company_id: UUID, truck_id: UUID, entry_date: date,
) -> list["WorkforceOVOut"]:
    """Every OV on this truck-day, ordered the way a driver walks the station.

    ZONE THEN ID (A5a). The driver's question is spatial — pull everything from
    B-27.2Y, then move to B-27.3X — so grouping by zone matches the physical
    task, and the id orders within a zone so two items on one shelf are
    distinguishable. Minting order is irrelevant to anybody holding a package.

    A zoneless OV (a milk-run item, which never had a station zone) sorts LAST
    rather than first: an empty string would put unplaced items at the head of
    the list the driver reads top-down at 06:00, which is exactly wrong.
    """
    rows = (
        db.query(WorkforceOV)
        .filter(
            WorkforceOV.company_id == company_id,
            WorkforceOV.truck_id == truck_id,
            WorkforceOV.entry_date == entry_date,
        )
        .all()
    )
    # Sorted in Python, not SQL: "nulls last" differs between Postgres and the
    # SQLite used in tests, and a list this size does not need the database.
    rows.sort(key=lambda o: (o.zone_label is None, o.zone_label or "", o.ov_id))

    addressed = {
        a.bag_id
        for a in db.query(ToteAddress.bag_id).filter(
            ToteAddress.company_id == company_id,
            ToteAddress.truck_id == truck_id,
            ToteAddress.entry_date == entry_date,
        ).all()
    }
    return [
        WorkforceOVOut(
            ov_id=o.ov_id,
            zone_label=o.zone_label,
            size=o.size,
            source=o.source,
            confirmed_at=o.confirmed_at,
            addressed=o.ov_id in addressed,
        )
        for o in rows
    ]


@router.post("/ovs", response_model=WorkforceOVOut,
             status_code=status.HTTP_201_CREATED)
def add_ov(
    payload: AddOVIn,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_route_lead),
    db: Session = Depends(get_db),
):
    """Add an OV that the sheet did not list (ADR-400 A6a).

    Two calls rather than one: this mints the id and creates the row, then the
    captain addresses it through the normal address endpoint. Minting on the fly
    during address entry was rejected — it would overload an endpoint that
    otherwise only records addresses, and put id-generation in two places when
    one of them already handles the race.

    Confirmed on creation. Somebody is holding the package; there is nothing to
    confirm later, unlike a sheet-seeded OV which exists as an expectation
    before anyone has seen it.
    """
    ta = _assignment(db, caller, payload.truck_assignment_id)
    _assert_truck_member(caller, ta.truck_id, payload.entry_date, db)

    ov = mint_ov(
        db,
        company_id=caller.company_id,
        truck_id=ta.truck_id,
        entry_date=payload.entry_date,
        source=payload.source,
        zone_label=payload.zone_label,
        confirmed_at=datetime.now(timezone.utc),
        confirmed_by=caller.id,
    )
    write_audit(
        db=db,
        company_id=str(caller.company_id),
        actor_id=str(caller.id),
        action_type="workforce_ov.add",
        target_table="workforce_ovs",
        target_id=str(ov.id),
        detail={"ov_id": ov.ov_id, "source": payload.source,
                "entry_date": payload.entry_date.isoformat()},
    )
    db.commit()
    db.refresh(ov)

    return WorkforceOVOut(
        ov_id=ov.ov_id, zone_label=ov.zone_label, size=ov.size,
        source=ov.source, confirmed_at=ov.confirmed_at, addressed=False,
    )


@router.post("/ovs/{entry_date}/seed", response_model=SeedOVsOut)
def seed_ovs_from_sheet(
    entry_date: date,
    truck_assignment_id: UUID,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_route_lead),
    db: Session = Depends(get_db),
):
    """Create the OV units the BTR sheet says belong on this truck (ADR-400 A2).

    `BTROVZone` has been written at every BTR import since ADR-290 and read by
    NOTHING. This is what reads it: "4 OVs at B-27.2Y" becomes four addressable
    units, so a truck with forty OVs stops sorting as though it had none.

    IDEMPOTENT on the truck-day. A re-import, a double tap, or a second captain
    running it adds only what is missing — counted against the sheet's expected
    total, not against a marker. There is no "seeded" flag to get out of sync.

    Deliberately NOT automatic on BTR import: the sheet is imported by dispatch
    before the truck is crewed, and an OV is scoped to a truck-day the captain
    is standing at. Seeding at import would create rows for a truck-day that may
    never happen.
    """
    ta = _assignment(db, caller, truck_assignment_id)
    _assert_truck_member(caller, ta.truck_id, entry_date, db)

    sheet = (
        db.query(BTRSheet)
        .filter(
            BTRSheet.company_id == caller.company_id,
            BTRSheet.truck_id == ta.truck_id,
            BTRSheet.sheet_date == entry_date,
        )
        .first()
    )
    if sheet is None:
        # Same distinction the tote roster draws: "unknowable" is not "none".
        return SeedOVsOut(expected=0, created=0, already_present=0, no_sheet=True)

    # Every OV zone on every Amazon route on this sheet. Scoped on company_id at
    # BOTH levels — the join alone would let another tenant's route drag its
    # zones in if a sheet id were ever guessed (dim 1).
    zones = (
        db.query(BTROVZone)
        .join(BTRRoute, BTRRoute.id == BTROVZone.btr_route_id)
        .filter(
            BTROVZone.company_id == caller.company_id,
            BTRRoute.company_id == caller.company_id,
            BTRRoute.btr_sheet_id == sheet.id,
        )
        .order_by(BTROVZone.zone_label.asc())
        .all()
    )
    expected = sum(z.ov_count or 0 for z in zones)

    existing = (
        db.query(func.count(WorkforceOV.id))
        .filter(
            WorkforceOV.company_id == caller.company_id,
            WorkforceOV.truck_id == ta.truck_id,
            WorkforceOV.entry_date == entry_date,
            WorkforceOV.source == "sheet",
        )
        .scalar()
    ) or 0

    # Count sheet-sourced rows only. A milk-run OV is an ARRIVAL, not part of the
    # sheet's expectation (A5b) — counting it here would make the seed think it
    # had already done its job and skip a genuinely missing unit.
    to_create = max(0, expected - existing)
    created = 0
    if to_create:
        # Walk the zones in order so the FIRST unseeded unit takes the FIRST
        # zone. Re-running after a partial seed continues where it stopped
        # rather than re-labelling what is already there.
        slots: list[str] = []
        for z in zones:
            slots.extend([z.zone_label] * (z.ov_count or 0))
        for zone_label in slots[existing:existing + to_create]:
            mint_ov(
                db,
                company_id=caller.company_id,
                truck_id=ta.truck_id,
                entry_date=entry_date,
                source="sheet",
                zone_label=zone_label,
            )
            created += 1

        write_audit(
            db=db,
            company_id=str(caller.company_id),
            actor_id=str(caller.id),
            action_type="workforce_ov.seed",
            target_table="workforce_ovs",
            target_id=str(ta.truck_id),
            detail={"entry_date": entry_date.isoformat(), "created": created,
                    "expected": expected},
        )
        db.commit()

    return SeedOVsOut(
        expected=expected,
        created=created,
        already_present=existing,
    )


@router.get("/load-roster/{load_date}", response_model=LoadRosterOut)
def load_roster(
    load_date: date,
    truck_assignment_id: UUID,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_read),
    db: Session = Depends(get_db),
):
    """What the BTR sheet says is on this truck, and what has been checked off.

    ADR-307 D1a. The dock step is REAL work in workforce mode: a driver says
    which totes they received and which they did not, and that is the moment a
    missing bag gets caught. It happens whether or not the company has a package
    feed.

    Full mode's equivalent is `/sort/{date}/rosters`, which returns TruckZone
    rosters — the station sort's CLUSTERING OUTPUT. That does not exist here, so
    this is not a renamed endpoint: the BTR sheet supplies the same answer to the
    driver's question ("what should be on my truck?") from a different source.

    `ToteLoadCheck` is REUSED, not duplicated. It is keyed
    (company_id, load_date, truck_id, bag_id) with no zone, manifest or TBA
    reference — it was always mode-agnostic, and only its READERS were full-mode
    gated. A tenant that switches modes keeps one continuous history.
    """
    from app.models.tote_ops import ToteLoadCheck

    ta = _assignment(db, caller, truck_assignment_id)
    _assert_truck_member(caller, ta.truck_id, load_date, db)

    sheet = (
        db.query(BTRSheet)
        .filter(
            BTRSheet.company_id == caller.company_id,
            BTRSheet.truck_id == ta.truck_id,
            BTRSheet.sheet_date == load_date,
        )
        .first()
    )
    if sheet is None:
        # No sheet imported: the tote list is UNKNOWABLE, which is a different
        # fact from "this truck has no totes". The flag says which.
        #
        # OVs are still returned. `no_sheet` means the DRIVER has no signal to
        # load against — it does not mean there are no OVs, because a captain
        # can add one at any point (A5b) and those exist independently of any
        # sheet. Returning an empty list here would report captain-added OVs as
        # absent, which is a different lie from the one `no_sheet` tells.
        ovs = _ovs_for_truck_day(db, caller.company_id, ta.truck_id, load_date)
        return LoadRosterOut(
            load_date=load_date,
            truck_assignment_id=ta.id,
            no_sheet=True,
            ovs=ovs,
            ov_total=len(ovs),
            ov_unconfirmed_count=sum(1 for o in ovs if o.confirmed_at is None),
        )

    bags = (
        db.query(BTRBag)
        .filter(
            BTRBag.company_id == caller.company_id,
            BTRBag.btr_sheet_id == sheet.id,
        )
        .order_by(BTRBag.bag_id.asc())
        .all()
    )
    checks = {
        c.bag_id: c
        for c in db.query(ToteLoadCheck).filter(
            ToteLoadCheck.company_id == caller.company_id,
            ToteLoadCheck.load_date == load_date,
            ToteLoadCheck.truck_id == ta.truck_id,
        ).all()
    }

    totes = []
    for b in bags:
        chk = checks.get(b.bag_id)
        hexv = canonical_hex(b.bag_color)
        totes.append(LoadRosterToteOut(
            bag_id=b.bag_id,
            bag_color=hexv,
            bag_color_name=color_name_for_hex(hexv),
            amazon_route_name=b.amazon_route_name,
            sort_zone=b.sort_zone,
            checked=chk is not None,
            checked_by_name=chk.checked_by_name if chk else None,
            checked_at=chk.checked_at if chk else None,
        ))

    checked_count = sum(1 for t in totes if t.checked)
    ovs = _ovs_for_truck_day(db, caller.company_id, ta.truck_id, load_date)
    return LoadRosterOut(
        load_date=load_date,
        truck_assignment_id=ta.id,
        btr_loading_zone=sheet.btr_loading_zone,
        totes=totes,
        total=len(totes),
        checked_count=checked_count,
        unchecked_count=len(totes) - checked_count,
        ovs=ovs,
        ov_total=len(ovs),
        ov_unconfirmed_count=sum(1 for o in ovs if o.confirmed_at is None),
    )


@router.post("/load-roster/{load_date}/totes/{bag_id}/check",
             response_model=LoadRosterOut)
def check_tote(
    load_date: date,
    bag_id: str,
    payload: ToteCheckIn,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_route_lead),
    db: Session = Depends(get_db),
):
    """Tick a tote onto the truck, or untick it (ADR-307 D1a).

    Mirrors `sort.py::check_tote`'s guards deliberately: 409 on double-check and
    409 on unchecking something unchecked, so a double-tap on a phone in a
    warehouse cannot silently produce a second row or a confusing no-op.

    D1b — THIS RECORDS PRESENCE ONLY. Full mode turns an unchecked tote into a
    PackageRemoval (ADR-176) because the manifest says which packages were in it
    and where they were going. Workforce mode has no per-package address data —
    a missing tote is a bag id and a colour, and nothing about its contents. So
    an unchecked bag is reported as unchecked and nothing else: no removal, no
    custody chain, no claim about what was lost. Inventing a removal from a bag
    id would fabricate the one thing this mode does not observe.
    """
    from app.models.tote_ops import ToteLoadCheck

    ta = _assignment(db, caller, payload.truck_assignment_id)
    _assert_truck_member(caller, ta.truck_id, load_date, db)

    # The bag must be on this truck's sheet — otherwise a typo silently creates a
    # check for a tote nobody expects, and the counts stop reconciling.
    on_sheet = (
        db.query(BTRBag.id)
        .join(BTRSheet, BTRSheet.id == BTRBag.btr_sheet_id)
        .filter(
            BTRBag.company_id == caller.company_id,
            BTRSheet.company_id == caller.company_id,
            BTRSheet.truck_id == ta.truck_id,
            BTRSheet.sheet_date == load_date,
            BTRBag.bag_id == bag_id,
        )
        .first()
    )
    if on_sheet is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tote {bag_id} is not on this truck's sheet for {load_date}.",
        )

    existing = (
        db.query(ToteLoadCheck)
        .filter(
            ToteLoadCheck.company_id == caller.company_id,
            ToteLoadCheck.load_date == load_date,
            ToteLoadCheck.truck_id == ta.truck_id,
            ToteLoadCheck.bag_id == bag_id,
        )
        .first()
    )

    if payload.checked:
        if existing is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail="Tote is already checked off.")
        db.add(ToteLoadCheck(
            company_id=caller.company_id,
            load_date=load_date,
            truck_id=ta.truck_id,
            bag_id=bag_id,
            checked_by=caller.id,
            checked_by_name=caller.name,
        ))
        action = "workforce.tote_checked"
    else:
        if existing is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail="Tote is not checked off.")
        db.delete(existing)
        action = "workforce.tote_unchecked"

    db.flush()
    write_audit(
        db=db,
        company_id=str(caller.company_id),
        actor_id=str(caller.id),
        action_type=action,
        target_table="tote_load_checks",
        target_id=bag_id,
        detail={"load_date": load_date.isoformat(), "truck_id": str(ta.truck_id)},
    )
    db.commit()

    # Return the whole roster: the driver's next decision depends on the updated
    # counts, and a second round-trip on a warehouse connection is a real cost.
    return load_roster(
        load_date=load_date,
        truck_assignment_id=payload.truck_assignment_id,
        caller=caller, _={}, db=db,
    )


@router.get("/day-totals/{entry_date}", response_model=TruckDayTotalsOut)
def truck_day_totals(
    entry_date: date,
    truck_assignment_id: UUID,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_route_lead),
    db: Session = Depends(get_db),
):
    """The truck-day's own numbers, from OUR routes (ADR-299 D1/D4).

    The end-of-day counterpart to the morning board. The board shows Amazon's
    BTR figure, labelled as Amazon's, for the people loading the truck; this is
    the number that gets persisted and reported, and it comes from
    `flex_package_count` — the real parcel count a captain reads off Amazon Flex
    while the walker scans (ADR-291 D11).

    D5: the two are never reconciled. A gap between Amazon's morning claim and
    our close-out is a real signal — packages that never made it onto a route, a
    sheet that was wrong, a tote nobody addressed — and averaging or silently
    preferring one destroys it.
    """
    ta = _assignment(db, caller, truck_assignment_id)
    _assert_truck_member(caller, ta.truck_id, entry_date, db)

    routes = (
        db.query(Route.flex_package_count, Route.returned_at)
        .filter(
            Route.company_id == caller.company_id,
            Route.truck_assignment_id == ta.id,
            Route.route_date == entry_date,
        )
        .all()
    )

    closed = [r for r in routes if r.returned_at is not None]
    unscanned = [r for r in closed if r.flex_package_count is None]

    # D4. A partial sum reports a smaller truck than actually went out, so the
    # total is withheld until every closed route has a count. Zero closed routes
    # is also NULL, not 0 — the day has not produced a number yet.
    carried: Optional[int] = None
    if closed and not unscanned:
        carried = sum(r.flex_package_count for r in closed)

    return TruckDayTotalsOut(
        route_date=entry_date,
        truck_assignment_id=ta.id,
        routes_total=len(routes),
        routes_closed=len(closed),
        packages_carried=carried,
        routes_missing_flex_count=len(unscanned),
    )


@router.get("/my-route/{entry_date}", response_model=MyRouteOut)
def my_route(
    entry_date: date,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_read),
    db: Session = Depends(get_db),
):
    """The caller's own route for a day (ADR-297).

    D1: a new endpoint on this router rather than a mode-branch inside
    `walker_routes.py`. That file is the proprietary bundle and is gated
    wholesale under `_full_mode`; ungating it to serve one read would expose the
    package-coupled reads beside it, and a mode-branching read inside a full-mode
    router is exactly the "off switch with nothing behind it" shape ADR-290 was
    written to correct.

    D2: THE CALLER IS THE KEY. No route_id in the path and no client-supplied
    employee id — the server resolves `RouteParticipant.employee_id == caller.id`
    with `role="executor"`. A walker asking "what is my route" must not be able
    to ask it about somebody else, and an id in the path is an object-level
    ownership check waiting to be forgotten.

    Gated with the existing `_allow_read` (route leads + walker/trainer/trainee),
    already described in this router as "field staff read their own assignment
    but never build or assign routes" — precisely this endpoint. A route lead
    passing through still sees only their OWN route, because the resolution is by
    caller id: a captain who also walks a route is a real case, and the
    truck-wide view is a separate concern (`GET /workforce/routes/{date}`).
    """
    # ADR-406 D2. This was `.order_by(route_number).first()` with NO status
    # filter, which is two live bugs:
    #
    #   - a walker who finished route 2 and was given route 7 saw ROUTE 2, a
    #     completed route, because it sorts lower;
    #   - a walker OUT on route 7 with route 4 assigned saw ROUTE 4, not the one
    #     in their hands.
    #
    # Route number reflects sort order, not sequence of work. So: live statuses
    # only, and in_progress first — what they are physically carrying wins over
    # anything merely assigned.
    mine = (
        db.query(Route)
        .join(RouteParticipant, RouteParticipant.route_id == Route.id)
        .filter(
            Route.company_id == caller.company_id,
            Route.route_date == entry_date,
            Route.status.in_(("assigned", "in_progress")),
            RouteParticipant.company_id == caller.company_id,
            RouteParticipant.employee_id == caller.id,
            RouteParticipant.role == "executor",
        )
        .order_by(Route.route_number.asc())
        .all()
    )
    in_progress = [r for r in mine if r.status == "in_progress"]
    assigned = [r for r in mine if r.status == "assigned"]
    route = (in_progress or assigned or [None])[0]
    # Everything else they hold is waiting on this one (D1a caps it at one).
    reserved = [r for r in mine if route is not None and r.id != route.id]
    if route is None:
        # D6: a real state, not an error. Same shape, flag set.
        return MyRouteOut(no_route_assigned=True)

    ta = (
        db.query(TruckAssignment)
        .filter(
            TruckAssignment.id == route.truck_assignment_id,
            TruckAssignment.company_id == caller.company_id,
        )
        .first()
    )
    truck_name = None
    if ta is not None:
        # Local import matches this module's existing style (see my_truck).
        from app.models.truck import Truck

        truck = (
            db.query(Truck)
            .filter(Truck.id == ta.truck_id, Truck.company_id == caller.company_id)
            .first()
        )
        truck_name = truck.name if truck is not None else None

    bag_ids = list(route.tote_ids or [])
    by_id = _bags_by_id(
        db, caller.company_id, ta.truck_id, entry_date, bag_ids
    ) if ta is not None else {}

    # D4: block descriptions are re-derived from the ADDRESS, because the key
    # alone is ambiguous — "100-15 Astoria Blvd" and a Manhattan hundred-block
    # both produce Astoria_Blvd_100. `describe_stored_block` returns None when
    # the address is gone (ADR-219 nulls them after the retention window), when
    # it no longer parses, or when the re-derived key disagrees with the stored
    # one. None is EXPECTED here, not exceptional: the row falls back to the raw
    # key, which is what the captain-facing list already does.
    #
    # D7: the descriptions are what ships. `raw_address` and
    # `normalised_address` never enter this payload — the describer takes an
    # address as INPUT and it must not leak out beside its output.
    addr_rows = (
        db.query(ToteAddress)
        .filter(
            ToteAddress.company_id == caller.company_id,
            ToteAddress.entry_date == entry_date,
            ToteAddress.bag_id.in_(bag_ids),
        )
        .all()
    ) if bag_ids else []

    by_bag: dict[str, list] = {}
    for a in addr_rows:
        by_bag.setdefault(a.bag_id, []).append(a)

    totes: list[MyRouteToteOut] = []
    for bag_id in bag_ids:
        entries = by_bag.get(bag_id, [])
        keys, descs = [], []
        for e in entries:
            if e.block_key and e.block_key not in keys:
                keys.append(e.block_key)
                d = describe_stored_block(
                    e.normalised_address or e.raw_address, e.block_key
                )
                descs.append(d or e.block_key)
        hexv = canonical_hex(_bag_color(by_id, bag_id))
        totes.append(MyRouteToteOut(
            bag_id=bag_id,
            bag_color=hexv,
            bag_color_name=color_name_for_hex(hexv),
            block_keys=keys,
            block_descriptions=descs,
        ))

    return MyRouteOut(
        route_id=route.id,
        route_number=route.route_number,
        status=route.status,
        truck_name=truck_name,
        totes=totes,
        block_keys=list(route.block_keys or []),
        flex_package_count=route.flex_package_count,
        departed_at=route.departed_at,
        returned_at=route.returned_at,
        reserved_routes=[
            ReservedRouteOut(
                route_id=r.id,
                route_number=r.route_number,
                tote_count=len(r.tote_ids or []),
                block_keys=list(r.block_keys or []),
            )
            for r in reserved
        ],
    )


@router.get("/routes/{entry_date}", response_model=list[WorkforceRouteOut])
def list_workforce_routes(
    entry_date: date,
    truck_assignment_id: UUID,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_route_lead),
    db: Session = Depends(get_db),
):
    """The truck-day's routes, WITHOUT rebuilding them (ADR-302 D1).

    Until this existed, `POST /commit-sort` was the only thing that returned a
    truck's routes — and it REBUILDS them to do so. A captain wanting to review
    the sort they just ran had exactly one option: run it again, destructively.

    Returns the same `WorkforceRouteOut` shape commit-sort returns, so the
    captain surface renders one shape whether it just sorted or is reviewing an
    earlier sort. Deliberately NOT the full `CommitWorkforceSortOut`: totes_sorted
    / unparseable / disagreements describe a sort RUN, not the routes, and
    re-deriving them here would re-parse addresses that may since have been
    PII-nulled (ADR-219) — giving different answers on different days for the
    same routes.
    """
    ta = _assignment(db, caller, truck_assignment_id)
    _assert_truck_member(caller, ta.truck_id, entry_date, db)

    routes = (
        db.query(Route)
        .filter(
            Route.company_id == caller.company_id,
            Route.truck_assignment_id == ta.id,
            Route.route_date == entry_date,
        )
        .order_by(Route.route_number.asc())
        .all()
    )
    names = _participant_names(db, caller.company_id, routes)
    parts = _participants(db, caller.company_id, routes)      # ADR-402 D2
    kinds = _assignment_kind(db, caller.company_id, routes)   # ADR-406 D1

    return [
        WorkforceRouteOut(
            id=r.id,
            route_number=r.route_number,
            tote_ids=list(r.tote_ids or []),
            block_keys=list(r.block_keys or []),
            package_count=r.package_count,
            slot_cost=r.slot_cost,
            capacity_limit=r.capacity_limit,
            overflow_half_slots=r.overflow_half_slots,
            status=r.status,
            assigned_to=None,
            assigned_to_name=names.get(r.id),
            flex_package_count=r.flex_package_count,
            departed_at=r.departed_at, returned_at=r.returned_at,
            participants=parts.get(r.id, []),
            assignment_kind=kinds.get(r.id),
        )
        for r in routes
    ]


@router.patch("/routes/{route_id}/depart", response_model=WorkforceRouteOut)
def depart_route(
    route_id: UUID,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_route_lead),
    db: Session = Depends(get_db),
):
    """The walker has left the truck with this route's totes (ADR-300 D2).

    Stamps `departed_at` and moves the route to `in_progress`. That pair —
    departed set, returned NULL — IS what "in progress" means, and it is what
    makes two other things correct:

      * a re-sort steps around this route instead of planning its totes onto a
        new one (ADR-302 D2/D3): those totes are physically gone
      * the captain cannot hand this walker a second route until it closes
        (D2b)

    Never back-filled. A departure that was not observed stays NULL rather than
    being invented at close to make a duration look computable.
    """
    route = (
        db.query(Route)
        .filter(Route.id == route_id, Route.company_id == caller.company_id)
        .first()
    )
    if route is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Route not found.")

    ta = _assignment(db, caller, route.truck_assignment_id)
    _assert_truck_member(caller, ta.truck_id, route.route_date, db)

    # One-way stamp (CLAUDE.md dim 2). Re-tapping must not move the clock.
    if route.departed_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Route {route.route_number} already departed.",
        )
    if route.status != "assigned":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Route {route.route_number} is {route.status} — assign it to a "
                f"walker before recording a departure."
            ),
        )

    route.departed_at = datetime.now(timezone.utc)
    route.status = "in_progress"

    db.flush()
    write_audit(
        db=db,
        company_id=str(caller.company_id),
        actor_id=str(caller.id),
        action_type="workforce_route.departed",
        target_table="routes",
        target_id=str(route.id),
        detail={"route_number": route.route_number,
                "route_date": route.route_date.isoformat()},
    )
    db.commit()
    db.refresh(route)

    names = _participant_names(db, caller.company_id, [route])
    parts = _participants(db, caller.company_id, [route])
    kinds = _assignment_kind(db, caller.company_id, [route])   # ADR-406 D1   # ADR-402 D2
    return WorkforceRouteOut(
        id=route.id, route_number=route.route_number,
        tote_ids=list(route.tote_ids or []), block_keys=list(route.block_keys or []),
        package_count=route.package_count, slot_cost=route.slot_cost,
        capacity_limit=route.capacity_limit,
        overflow_half_slots=route.overflow_half_slots, status=route.status,
        assigned_to=None, assigned_to_name=names.get(route.id),
        flex_package_count=route.flex_package_count,
        departed_at=route.departed_at, returned_at=route.returned_at,
        participants=parts.get(route.id, []),
        assignment_kind=kinds.get(route.id),
    )


@router.patch("/routes/{route_id}/close", response_model=WorkforceRouteOut)
def close_route(
    route_id: UUID,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_route_lead),
    db: Session = Depends(get_db),
):
    """The walker is back at the truck; the route's day is over (ADR-300).

    D1: the CAPTAIN closes it, not the walker. The captain is at the truck, the
    walker is arriving with whatever came back, and the close is that handover.
    A walker self-closing from the field would settle the route before the
    packages are physically accounted for — the one thing the close exists to
    prevent.

    D2: `status="completed"` and `returned_at` are set TOGETHER. Full mode
    separates them because it knows per-stop when work finished, independently
    of when the walker got back. Workforce mode knows neither: there is no stop
    grain, so the only observable event is *the walker is standing here*.
    Modelling two states from one signal invents a distinction we cannot fill.

    D4: closing is the moment exceptions are recorded — the returns endpoints
    (ADR-292) are keyed by route_id and the CLIENT prompts for them before
    calling this. A route with zero returns closes cleanly: a clean route is a
    real and common outcome, so nothing is required here.

    D5: the close FREEZES `flex_package_count`. Until now it is deliberately
    re-recordable (a miscounted scan is corrected in the moment); afterwards it
    is the day's record (ADR-299 D4) and further writes are refused.
    """
    route = (
        db.query(Route)
        .filter(Route.id == route_id, Route.company_id == caller.company_id)
        .first()
    )
    if route is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Route not found.")

    ta = _assignment(db, caller, route.truck_assignment_id)
    _assert_truck_member(caller, ta.truck_id, route.route_date, db)

    # D3 — one-way stamp with a 409, matching full mode's back-at-truck guard.
    # Closing twice must not re-open a settled number.
    if route.returned_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Route {route.route_number} is already closed.",
        )
    if route.status not in ("assigned", "in_progress"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Route {route.route_number} is {route.status} — only a route "
                f"that is out or assigned can be closed."
            ),
        )

    route.returned_at = datetime.now(timezone.utc)
    route.status = "completed"

    db.flush()
    write_audit(
        db=db,
        company_id=str(caller.company_id),
        actor_id=str(caller.id),
        action_type="workforce_route.closed",
        target_table="routes",
        target_id=str(route.id),
        detail={
            "route_number": route.route_number,
            "route_date": route.route_date.isoformat(),
            # The number this close FREEZES (D5). NULL means it was never
            # scanned — recorded as such rather than as 0.
            "flex_package_count": route.flex_package_count,
            "departed_at": route.departed_at.isoformat() if route.departed_at else None,
        },
    )
    db.commit()
    db.refresh(route)

    names = _participant_names(db, caller.company_id, [route])
    parts = _participants(db, caller.company_id, [route])
    kinds = _assignment_kind(db, caller.company_id, [route])   # ADR-406 D1   # ADR-402 D2
    return WorkforceRouteOut(
        id=route.id, route_number=route.route_number,
        tote_ids=list(route.tote_ids or []), block_keys=list(route.block_keys or []),
        package_count=route.package_count, slot_cost=route.slot_cost,
        capacity_limit=route.capacity_limit,
        overflow_half_slots=route.overflow_half_slots, status=route.status,
        assigned_to=None, assigned_to_name=names.get(route.id),
        flex_package_count=route.flex_package_count,
        departed_at=route.departed_at, returned_at=route.returned_at,
        participants=parts.get(route.id, []),
        assignment_kind=kinds.get(route.id),
    )


# ── walker assignment (D8) ────────────────────────────────────────────────────

@router.patch("/routes/{route_id}/assign", response_model=WorkforceRouteOut)
def assign_walker(
    route_id: UUID,
    payload: AssignWalkerIn,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_route_lead),
    db: Session = Depends(get_db),
):
    """Give a route to a walker.

    D8: the captain decides. ADR-189's banded-urgency matcher needs per-stop
    timing that workforce mode does not have, so wave distribution does not run
    — and a matcher fed empty timing would rank on nothing while looking
    authoritative.
    """
    route = (
        db.query(Route)
        .filter(Route.id == route_id, Route.company_id == caller.company_id)
        .first()
    )
    if route is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Route not found.")

    ta = _assignment(db, caller, route.truck_assignment_id)
    _assert_truck_member(caller, ta.truck_id, route.route_date, db)

    if route.status == "in_progress":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This route is already out. Reassigning it now would strand the walker.",
        )

    walker = (
        db.query(Employee)
        .filter(
            Employee.id == payload.employee_id,
            Employee.company_id == caller.company_id,
            Employee.is_active.is_(True),
        )
        .first()
    )
    if walker is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found.")

    # ADR-300 D2b. IS THIS WALKER ALREADY OUT?
    #
    # The guard above protects the ROUTE ("this route is already out"); nothing
    # protected the WALKER. A captain could hand a second route to someone still
    # walking their first, and nothing objected — verified: zero queries of the
    # assignee's other routes.
    #
    # `departed_at` set with `returned_at` NULL IS "in progress". That pair is
    # the route lifecycle, and this is what it is for: a multi-wave day means
    # assigning a new route once the first is done, which requires knowing
    # whether they are done.
    #
    # Scoped to the same route_date: yesterday's unclosed route is a data-hygiene
    # problem, not a reason to block today's assignment.
    # ADR-406 D0. This asked "is this WALKER out on anything" and refused if so.
    # Two different fears were tangled in that one question: reassigning the
    # route someone is CARRYING (a real hazard, and they cannot see it happen),
    # and giving them a DIFFERENT route for later (strands nobody, because
    # nothing has moved). Only the first deserves refusing, and the
    # `status == "in_progress"` check above already covers it from the other
    # direction — so narrowing here opens no gap.
    #
    # What the walker's other work still constrains is the RESERVATION CAP.
    held = (
        db.query(Route.route_number)
        .join(RouteParticipant, RouteParticipant.route_id == Route.id)
        .filter(
            Route.company_id == caller.company_id,
            Route.route_date == route.route_date,
            Route.id != route.id,
            Route.status == "assigned",
            RouteParticipant.company_id == caller.company_id,
            RouteParticipant.employee_id == walker.id,
            RouteParticipant.role == "executor",
        )
        .order_by(Route.route_number.asc())
        .all()
    )
    # D1a — at most ONE route waiting. Enforced here, not in the UI: a
    # client-side limit is a suggestion that survives until someone calls the
    # API directly, or two captains assign at the same moment.
    #
    # "route 7 is yours" is a promise, and four promises are a backlog nobody
    # reads — which is the whole reason a reservation is worth showing.
    if held:
        numbers = ", ".join(str(r.route_number) for r in held)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"{walker.name} already has route {numbers} waiting. A walker "
                f"can hold one route at a time plus one more."
            ),
        )

    # Exactly one executor per route (ADR-212, enforced by a partial unique
    # index). Replacing means clearing the old one first, not adding a second.
    db.query(RouteParticipant).filter(
        RouteParticipant.route_id == route.id,
        RouteParticipant.company_id == caller.company_id,
        RouteParticipant.role == "executor",
    ).delete(synchronize_session=False)

    db.add(RouteParticipant(
        id=_uuid.uuid4(),
        company_id=caller.company_id,
        route_id=route.id,
        employee_id=walker.id,
        role="executor",
    ))
    route.status = "assigned"

    db.flush()
    write_audit(
        db=db,
        company_id=str(caller.company_id),
        actor_id=str(caller.id),
        action_type="workforce_route.assign",
        target_table="routes",
        target_id=str(route.id),
        detail={"employee_id": str(walker.id), "route_number": route.route_number},
    )
    db.commit()
    db.refresh(route)

    # ADR-402 D2. Re-read after the assign so the row reflects the participant
    # this call just created, rather than the state before it.
    parts = _participants(db, caller.company_id, [route])
    kinds = _assignment_kind(db, caller.company_id, [route])   # ADR-406 D1

    return WorkforceRouteOut(
        id=route.id, route_number=route.route_number, tote_ids=list(route.tote_ids or []),
        block_keys=list(route.block_keys or []), package_count=route.package_count,
        slot_cost=route.slot_cost, capacity_limit=route.capacity_limit,
        overflow_half_slots=route.overflow_half_slots, status=route.status,
        assigned_to=walker.id, assigned_to_name=walker.name,
        flex_package_count=route.flex_package_count,
        departed_at=route.departed_at, returned_at=route.returned_at,
        participants=parts.get(route.id, []),
        assignment_kind=kinds.get(route.id),
    )


# ── per-route package count (D11) ─────────────────────────────────────────────

@router.patch("/routes/{route_id}/package-count", response_model=WorkforceRouteOut)
def record_flex_package_count(
    route_id: UUID,
    payload: FlexPackageCountIn,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_route_lead),
    db: Session = Depends(get_db),
):
    """Record the package count Amazon Flex showed while the walker scanned.

    D11: `Route.package_count` is derived by the sort as the number of packages
    it carried — and a workforce "package" is one captain-entered ADDRESS. A
    route holding one tote with three addresses reports 3 while that tote
    physically holds fifty, and both `dashboard_summaries` and
    `assignment_history` read that field. Flex shows the real number at scan
    time, so the captain records it here.

    Deliberately RE-RECORDABLE, unlike the one-way stamps elsewhere in this
    codebase. A miscounted scan is corrected in the moment, and a 409 on the
    second attempt would leave a known-wrong number in the reporting rather than
    protecting anything. Every write is audited with the previous value, so the
    correction is traceable.
    """
    route = (
        db.query(Route)
        .filter(Route.id == route_id, Route.company_id == caller.company_id)
        .first()
    )
    if route is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Route not found.")

    ta = _assignment(db, caller, route.truck_assignment_id)
    _assert_truck_member(caller, ta.truck_id, route.route_date, db)

    # ADR-300 D5. Re-recordable RIGHT UP TO the close, then frozen: after that
    # it is the day's persisted record (ADR-299 D4), and a late re-record
    # silently changes a number the day was already reported on.
    if route.returned_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Route {route.route_number} is closed — its package count is "
                f"the day's record and cannot be changed."
            ),
        )

    previous = route.flex_package_count
    route.flex_package_count = payload.package_count
    route.flex_count_recorded_by = caller.id
    route.flex_count_recorded_at = datetime.now(timezone.utc)

    db.flush()
    write_audit(
        db=db,
        company_id=str(caller.company_id),
        actor_id=str(caller.id),
        action_type="workforce_route.flex_count",
        target_table="routes",
        target_id=str(route.id),
        before={"flex_package_count": previous},
        after={"flex_package_count": payload.package_count},
        detail={"route_number": route.route_number, "corrected": previous is not None},
    )
    db.commit()
    db.refresh(route)

    names = _participant_names(db, caller.company_id, [route])
    parts = _participants(db, caller.company_id, [route])
    kinds = _assignment_kind(db, caller.company_id, [route])   # ADR-406 D1   # ADR-402 D2
    return WorkforceRouteOut(
        id=route.id, route_number=route.route_number, tote_ids=list(route.tote_ids or []),
        block_keys=list(route.block_keys or []), package_count=route.package_count,
        slot_cost=route.slot_cost, capacity_limit=route.capacity_limit,
        overflow_half_slots=route.overflow_half_slots, status=route.status,
        assigned_to_name=names.get(route.id),
        flex_package_count=route.flex_package_count,
        departed_at=route.departed_at, returned_at=route.returned_at,
        participants=parts.get(route.id, []),
        assignment_kind=kinds.get(route.id),
    )


# ── route lookup (D9) ─────────────────────────────────────────────────────────

@router.post("/route-lookup", response_model=RouteLookupOut)
def route_lookup(
    payload: RouteLookupIn,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(_allow_route_lead),
    db: Session = Depends(get_db),
):
    """Which of today's routes should carry this address?

    The workforce twin of full mode's package transfer. A captain reading a
    walker's Flex itinerary sees an address that does not look like their route
    and asks where it belongs.

    Ranks on BLOCK adjacency, not segment (D9/D10): workforce mode has no
    populated segment map, and block_key is the graph the sort already built.
    Tiers degrade like `package_intake.resolve_address` — exact block, then a
    neighbouring hundred on the same street, then the same street anywhere.
    Nothing matched means escalate to dispatch rather than guess.
    """
    ta = _assignment(db, caller, payload.truck_assignment_id)
    _assert_truck_member(caller, ta.truck_id, ta.date, db)

    resolved = resolve_address(
        db=db, company_id=caller.company_id,
        raw_address=payload.raw_address, tba="lookup",
    )
    if not resolved.block_key:
        return RouteLookupOut(block_key=None, candidates=[], escalate=True)

    routes = (
        db.query(Route)
        .filter(
            Route.company_id == caller.company_id,
            Route.truck_assignment_id == ta.id,
            Route.route_date == ta.date,
        )
        .order_by(Route.route_number.asc())
        .all()
    )

    target = resolved.block_key
    # "W_36_St_400" -> ("W_36_St", 400). A block_key's trailing segment is its
    # hundred-block; the rest identifies the street.
    parts = target.rsplit("_", 1)
    street = parts[0] if len(parts) == 2 else target
    try:
        hundred = int(parts[1]) if len(parts) == 2 else None
    except ValueError:
        hundred = None

    names = _participant_names(db, caller.company_id, routes)
    candidates: list[RouteLookupCandidate] = []
    for r in routes:
        blocks = list(r.block_keys or [])
        match: Optional[str] = None
        hit: Optional[str] = None

        if target in blocks:
            match, hit = "exact_block", target
        elif hundred is not None:
            for b in blocks:
                bp = b.rsplit("_", 1)
                if len(bp) != 2 or bp[0] != street:
                    continue
                try:
                    if abs(int(bp[1]) - hundred) == 100:
                        match, hit = "adjacent_block", b
                        break
                except ValueError:
                    continue
        if match is None:
            same_street = next((b for b in blocks if b.rsplit("_", 1)[0] == street), None)
            if same_street:
                match, hit = "same_street", same_street

        if match:
            candidates.append(RouteLookupCandidate(
                route_id=r.id, route_number=r.route_number, match=match,
                block_key=hit, assigned_to_name=names.get(r.id),
            ))

    rank = {"exact_block": 0, "adjacent_block": 1, "same_street": 2}
    candidates.sort(key=lambda c: (rank[c.match], c.route_number))

    return RouteLookupOut(
        block_key=target,
        candidates=candidates,
        escalate=not candidates,
    )


def _assignment_kind(
    db: Session, company_id: UUID, routes: list[Route],
) -> dict[UUID, str]:
    """route_id -> "assigned" | "reserved", for routes someone holds (ADR-406 D1).

    A reserved route is not a fourth status. It is what an `assigned` route LOOKS
    LIKE while its walker is carrying something else:

        walker has an in_progress route  ->  their assigned route is RESERVED
        walker has none                  ->  it is ASSIGNED, take it now

    Derived, never stored, because the flip has no event of its own. Closing the
    in-progress route stamps `returned_at`, and the same row now reads
    `assigned` because the condition that made it reserved is gone. A stored
    value would need a writer on every close, and a close that forgot would
    leave a route reserved for a walker standing free at the truck.

    NOT ordered by route number. An earlier draft made the lowest-numbered route
    "next", which would tell a walker out with route 7 that route 4 was theirs to
    start. Route number reflects sort order, not sequence of work.
    """
    assigned = [r for r in routes if r.status == "assigned"]
    if not assigned:
        return {}

    # Who holds each assigned route.
    holder = {
        rid: emp
        for rid, emp in db.query(RouteParticipant.route_id, RouteParticipant.employee_id)
        .filter(
            RouteParticipant.company_id == company_id,
            RouteParticipant.route_id.in_([r.id for r in assigned]),
            RouteParticipant.role == "executor",
        )
        .all()
    }
    if not holder:
        return {}

    # Which of those people are physically out. ADR-300 D2b's pair, read here
    # rather than in the assign guard: departed and not yet returned.
    dates = {r.route_date for r in assigned}
    out = {
        emp
        for (emp,) in db.query(RouteParticipant.employee_id)
        .join(Route, Route.id == RouteParticipant.route_id)
        .filter(
            Route.company_id == company_id,
            Route.route_date.in_(dates),
            Route.departed_at.isnot(None),
            Route.returned_at.is_(None),
            RouteParticipant.company_id == company_id,
            RouteParticipant.employee_id.in_(set(holder.values())),
            RouteParticipant.role == "executor",
        )
        .all()
    }
    return {
        r.id: ("reserved" if holder.get(r.id) in out else "assigned")
        for r in assigned
        if r.id in holder
    }


def _participants(
    db: Session, company_id: UUID, routes: list[Route],
) -> dict[UUID, list["RouteParticipantOut"]]:
    """route_id -> every participant, executor AND supervisor (ADR-402 D2).

    The sibling `_participant_names` returns only the executor, which is right
    for a one-line summary and wrong for the mid-day view: a training pair is a
    trainee executing with a trainer supervising, and showing only the executor
    hides half of who is on that route.

    Scoped on `company_id` for BOTH tables — the RouteParticipant filter and the
    Employee join — because an unscoped join here would surface another tenant's
    employee name against this tenant's route (dim 1).
    """
    if not routes:
        return {}
    rows = (
        db.query(
            RouteParticipant.route_id,
            RouteParticipant.employee_id,
            RouteParticipant.role,
            Employee.name,
        )
        .join(
            Employee,
            (Employee.id == RouteParticipant.employee_id)
            & (Employee.company_id == company_id),
        )
        .filter(
            RouteParticipant.company_id == company_id,
            RouteParticipant.route_id.in_([r.id for r in routes]),
        )
        .all()
    )
    out: dict[UUID, list[RouteParticipantOut]] = {}
    for route_id, employee_id, role, name in rows:
        out.setdefault(route_id, []).append(
            RouteParticipantOut(employee_id=employee_id, name=name, role=role)
        )
    # Executor first, then supervisors — the person who ran it leads the row.
    for v in out.values():
        v.sort(key=lambda p: (p.role != "executor", p.name or ""))
    return out


def _participant_names(db: Session, company_id: UUID, routes: list[Route]) -> dict:
    """route_id -> executor name, resolved by join (never denormalised, ADR-212)."""
    if not routes:
        return {}
    rows = (
        db.query(RouteParticipant.route_id, Employee.name)
        .join(Employee, Employee.id == RouteParticipant.employee_id)
        .filter(
            RouteParticipant.company_id == company_id,
            RouteParticipant.route_id.in_([r.id for r in routes]),
            RouteParticipant.role == "executor",
        )
        .all()
    )
    return {rid: name for rid, name in rows}

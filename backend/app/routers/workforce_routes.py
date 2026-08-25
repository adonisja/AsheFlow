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
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.deps import RoleChecker, get_caller_employee
from app.database import get_db
from app.models.assignment_member import AssignmentMember
from app.models.employee import Employee
from app.models.tote_address import ToteAddress
from app.models.truck_assignment import TruckAssignment
from app.models.walker_route import Route, RouteParticipant
from app.schemas.walker_routes import SortRequest
from app.services.audit import write_audit
from app.services.constants import ROUTE_LEAD_ROLES
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
    """One address a captain typed against one tote."""
    model_config = ConfigDict(extra="forbid")

    truck_id: UUID
    entry_date: date
    bag_id: str = Field(..., min_length=1, max_length=50)
    # A street address. Bounded because it lands in a String(300) column and is
    # attacker-controlled free text.
    raw_address: str = Field(..., min_length=3, max_length=300)


class CommitWorkforceSortIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    truck_assignment_id: UUID
    route_date: date
    # D7: the captain may knowingly exceed the capacity lock. Off by default so
    # an overflow is always a deliberate act, never a silent side effect.
    allow_overflow: bool = False


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
    entry_sequence: int
    entered_by_name: Optional[str] = None
    # False when the address could not be parsed into a block_key. The entry is
    # still stored and still sorts — the captain can see and fix it.
    geocoded: bool = True


class ToteDisagreementOut(BaseModel):
    bag_id: str
    block_keys: list[str]
    winning_block_key: str


class ToteAddressListOut(BaseModel):
    addresses: list[ToteAddressOut]
    # D4: totes whose addresses point at different blocks — loose bagging or a
    # typo. Surfaced at entry where it is cheap to fix.
    disagreements: list[ToteDisagreementOut]
    # Totes the BTR sheet says are on the truck that nobody has addressed.
    unaddressed_bags: list[str]


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


class CommitWorkforceSortOut(BaseModel):
    routes: list[WorkforceRouteOut]
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

    row = ToteAddress(
        company_id=caller.company_id,
        truck_id=payload.truck_id,
        entry_date=payload.entry_date,
        bag_id=payload.bag_id,
        raw_address=payload.raw_address,
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
    db.add(row)
    db.flush()
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

    return ToteAddressListOut(
        addresses=[
            ToteAddressOut(
                id=r.id, bag_id=r.bag_id, raw_address=r.raw_address,
                normalised_address=r.normalised_address, block_key=r.block_key,
                entry_sequence=r.entry_sequence, entered_by_name=r.entered_by_name,
                geocoded=r.block_key is not None,
            )
            for r in rows
        ],
        disagreements=[
            ToteDisagreementOut(bag_id=d.bag_id, block_keys=d.block_keys,
                                winning_block_key=d.winning_block_key)
            for d in built.disagreements
        ],
        unaddressed_bags=built.unaddressed_bags,
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
    live = [r for r in existing if r.status in ("assigned", "in_progress")]
    if live:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"{len(live)} route(s) are already assigned or out. Unassign them "
                f"before re-sorting, or a walker loses the route they are holding."
            ),
        )

    built = build_packages(db, caller.company_id, ta.truck_id, payload.route_date)
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
    overflowed = 0
    for r in result.routes:
        over = max(0, (r.slot_cost or 0) - (r.capacity_limit or 0))
        if over and not payload.allow_overflow:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "This sort produces at least one route above its capacity limit. "
                    "Re-send with allow_overflow=true to accept it."
                ),
            )
        if over:
            overflowed += 1

    for old in existing:
        db.delete(old)
    db.flush()

    created: list[Route] = []
    for r in result.routes:
        over = max(0, (r.slot_cost or 0) - (r.capacity_limit or 0))
        route = Route(
            company_id=caller.company_id,
            truck_assignment_id=ta.id,
            route_date=payload.route_date,
            route_number=r.route_number,
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

    return CommitWorkforceSortOut(
        routes=[
            WorkforceRouteOut(
                id=r.id, route_number=r.route_number, tote_ids=list(r.tote_ids or []),
                block_keys=list(r.block_keys or []), package_count=r.package_count,
                slot_cost=r.slot_cost, capacity_limit=r.capacity_limit,
                overflow_half_slots=r.overflow_half_slots, status=r.status,
                flex_package_count=r.flex_package_count,
            )
            for r in created
        ],
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

    return WorkforceRouteOut(
        id=route.id, route_number=route.route_number, tote_ids=list(route.tote_ids or []),
        block_keys=list(route.block_keys or []), package_count=route.package_count,
        slot_cost=route.slot_cost, capacity_limit=route.capacity_limit,
        overflow_half_slots=route.overflow_half_slots, status=route.status,
        assigned_to=walker.id, assigned_to_name=walker.name,
        flex_package_count=route.flex_package_count,
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
    return WorkforceRouteOut(
        id=route.id, route_number=route.route_number, tote_ids=list(route.tote_ids or []),
        block_keys=list(route.block_keys or []), package_count=route.package_count,
        slot_cost=route.slot_cost, capacity_limit=route.capacity_limit,
        overflow_half_slots=route.overflow_half_slots, status=route.status,
        assigned_to_name=names.get(route.id),
        flex_package_count=route.flex_package_count,
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

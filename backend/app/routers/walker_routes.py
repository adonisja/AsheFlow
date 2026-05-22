"""Walker route distribution router.

Endpoints:
  POST /walker-routes/sort           — run the sort algorithm, return preview (nothing stored)
  POST /walker-routes/commit         — persist a sort result to the DB, binding walker IDs
  GET  /walker-routes/{id}           — fetch one WalkerRoute with its trips
  GET  /walker-routes/assignment/{id} — all routes for a truck assignment
  PATCH /walker-routes/trips/{id}/status — driver/walker updates trip status
  GET  /walker-routes/difficulty-flags  — list all blocks flagged for this company
  POST /walker-routes/difficulty-flags  — captain/dispatch flags a block
  PATCH /walker-routes/misroutes/{id}/resolve — captain resolves a misrouted package
"""

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.api.deps import RoleChecker, get_caller_employee
from app.models.employee import Employee
from app.models.truck_assignment import TruckAssignment
from app.models.walker_route import (
    LocationDifficultyFlag,
    MisroutedPackageFlag,
    WalkerRoute,
    WalkerTrip,
)
from app.schemas.walker_routes import (
    AssignWalkersRequest,
    LocationDifficultyFlagCreate,
    LocationDifficultyFlagResponse,
    MisroutedPackageFlagResponse,
    SortRequest,
    SortResult,
    WalkerRouteResponse,
    WalkerTripResponse,
    WalkerTripStatusPatch,
)
from app.services.route_sort import run_sort

router = APIRouter(prefix="/walker-routes", tags=["walker-routes"])

allow_dispatch  = RoleChecker(["dispatch", "management", "admin"])
allow_captain   = RoleChecker(["trainer", "dispatch", "management", "admin"])
allow_field     = RoleChecker(["walker", "trainer", "trainee", "driver", "dispatch", "management", "admin"])


# ---------------------------------------------------------------------------
# Sort preview — pure computation, nothing stored
# ---------------------------------------------------------------------------

@router.post("/sort", response_model=SortResult)
def sort_manifest(
    body: SortRequest,
    db: Session = Depends(get_db),
    caller: Employee = Depends(allow_dispatch),
):
    """Run the route sort algorithm and return a preview.

    Addresses in the request body are used only during this call and are never
    written to the database, logs, or the response.  The response contains only
    TBA numbers, tag numbers, and bag IDs.
    """
    # Load difficulty flags for this company
    flags_rows = (
        db.query(LocationDifficultyFlag)
        .filter(LocationDifficultyFlag.company_id == caller.company_id)
        .all()
    )
    difficulty_flags = {row.block_key: row.difficulty_tier for row in flags_rows}

    return run_sort(request=body, difficulty_flags=difficulty_flags)


# ---------------------------------------------------------------------------
# Commit — persist a sort result, binding walker IDs
# ---------------------------------------------------------------------------

@router.post("/commit", response_model=list[WalkerRouteResponse], status_code=status.HTTP_201_CREATED)
def commit_sort(
    sort_body: SortRequest,
    assign_body: AssignWalkersRequest,
    db: Session = Depends(get_db),
    caller: Employee = Depends(allow_dispatch),
):
    """Run the sort and persist routes + trips to the DB.

    walker_ids must be ordered to match the walker_index values in the sort
    result (index 0 → first walker ID, etc.).  Addresses are discarded after
    the sort computation; nothing address-related is written.
    """
    # Verify the truck assignment belongs to this company
    assignment = (
        db.query(TruckAssignment)
        .filter(
            TruckAssignment.id == sort_body.truck_assignment_id,
            TruckAssignment.company_id == caller.company_id,
        )
        .first()
    )
    if not assignment:
        raise HTTPException(status_code=404, detail="Truck assignment not found")

    flags_rows = (
        db.query(LocationDifficultyFlag)
        .filter(LocationDifficultyFlag.company_id == caller.company_id)
        .all()
    )
    difficulty_flags = {row.block_key: row.difficulty_tier for row in flags_rows}

    result = run_sort(request=sort_body, difficulty_flags=difficulty_flags)

    if len(assign_body.walker_ids) < len(result.walker_routes):
        raise HTTPException(
            status_code=400,
            detail=f"Provide {len(result.walker_routes)} walker IDs to match the sort output",
        )

    created_routes: list[WalkerRoute] = []

    for route_out in result.walker_routes:
        walker_id = assign_body.walker_ids[route_out.walker_index]

        route = WalkerRoute(
            company_id=caller.company_id,
            truck_assignment_id=sort_body.truck_assignment_id,
            route_date=sort_body.route_date,
            walker_id=walker_id,
            total_packages=route_out.total_packages,
            total_bags=route_out.total_bags,
            total_ovs=route_out.total_ovs,
            planned_trips=route_out.planned_trips,
        )
        db.add(route)
        db.flush()  # get route.id before creating trips

        for trip_out in route_out.trips:
            db.add(WalkerTrip(
                company_id=caller.company_id,
                walker_route_id=route.id,
                trip_number=trip_out.trip_number,
                bag_ids=trip_out.bag_ids,
                tba_numbers=trip_out.tba_numbers,
                tag_numbers=[t for t in trip_out.tag_numbers if t],
                status="pending",
            ))

        for flag in route_out.misrouted_packages:
            db.add(MisroutedPackageFlag(
                company_id=caller.company_id,
                walker_route_id=route.id,
                tba_number=flag.tba_number,
                tag_number=flag.tag_number,
                current_bag_id=flag.current_bag_id,
                suggested_walker_route_id=None,  # resolved after all routes flushed
                resolved=False,
            ))

        created_routes.append(route)

    # Unassigned misroutes (no cluster match) — attach to first route as a catch-all
    if result.unassigned_misroutes and created_routes:
        for flag in result.unassigned_misroutes:
            db.add(MisroutedPackageFlag(
                company_id=caller.company_id,
                walker_route_id=created_routes[0].id,
                tba_number=flag.tba_number,
                tag_number=flag.tag_number,
                current_bag_id=flag.current_bag_id,
                suggested_walker_route_id=None,
                resolved=False,
            ))

    db.commit()
    for r in created_routes:
        db.refresh(r)

    return created_routes


# ---------------------------------------------------------------------------
# Read routes
# ---------------------------------------------------------------------------

@router.get("/assignment/{assignment_id}", response_model=list[WalkerRouteResponse])
def get_routes_for_assignment(
    assignment_id: UUID,
    db: Session = Depends(get_db),
    caller: Employee = Depends(allow_field),
):
    routes = (
        db.query(WalkerRoute)
        .filter(
            WalkerRoute.truck_assignment_id == assignment_id,
            WalkerRoute.company_id == caller.company_id,
        )
        .order_by(WalkerRoute.created_at)
        .all()
    )
    for route in routes:
        route.trips = (
            db.query(WalkerTrip)
            .filter(WalkerTrip.walker_route_id == route.id)
            .order_by(WalkerTrip.trip_number)
            .all()
        )
    return routes


@router.get("/{route_id}", response_model=WalkerRouteResponse)
def get_walker_route(
    route_id: UUID,
    db: Session = Depends(get_db),
    caller: Employee = Depends(allow_field),
):
    route = (
        db.query(WalkerRoute)
        .filter(WalkerRoute.id == route_id, WalkerRoute.company_id == caller.company_id)
        .first()
    )
    if not route:
        raise HTTPException(status_code=404, detail="Walker route not found")
    route.trips = (
        db.query(WalkerTrip)
        .filter(WalkerTrip.walker_route_id == route.id)
        .order_by(WalkerTrip.trip_number)
        .all()
    )
    return route


# ---------------------------------------------------------------------------
# Trip status updates (walker taps Start Trip / Return)
# ---------------------------------------------------------------------------

@router.patch("/trips/{trip_id}/status", response_model=WalkerTripResponse)
def update_trip_status(
    trip_id: UUID,
    body: WalkerTripStatusPatch,
    db: Session = Depends(get_db),
    caller: Employee = Depends(allow_field),
):
    trip = (
        db.query(WalkerTrip)
        .filter(WalkerTrip.id == trip_id, WalkerTrip.company_id == caller.company_id)
        .first()
    )
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    now = datetime.now(timezone.utc)
    trip.status = body.status
    if body.status == "in_progress" and trip.departed_at is None:
        trip.departed_at = now
    elif body.status == "completed" and trip.returned_at is None:
        trip.returned_at = now

    db.commit()
    db.refresh(trip)
    return trip


# ---------------------------------------------------------------------------
# Difficulty flags
# ---------------------------------------------------------------------------

@router.get("/difficulty-flags", response_model=list[LocationDifficultyFlagResponse])
def list_difficulty_flags(
    db: Session = Depends(get_db),
    caller: Employee = Depends(allow_captain),
):
    return (
        db.query(LocationDifficultyFlag)
        .filter(LocationDifficultyFlag.company_id == caller.company_id)
        .order_by(LocationDifficultyFlag.block_key)
        .all()
    )


@router.post("/difficulty-flags", response_model=LocationDifficultyFlagResponse, status_code=status.HTTP_201_CREATED)
def create_difficulty_flag(
    body: LocationDifficultyFlagCreate,
    db: Session = Depends(get_db),
    caller: Employee = Depends(allow_captain),
):
    # Upsert — update tier if block_key already exists for this company
    existing = (
        db.query(LocationDifficultyFlag)
        .filter(
            LocationDifficultyFlag.company_id == caller.company_id,
            LocationDifficultyFlag.block_key == body.block_key,
        )
        .first()
    )
    if existing:
        existing.difficulty_tier = body.difficulty_tier
        existing.notes = body.notes
        existing.flagged_by = caller.id
        existing.flagged_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(existing)
        return existing

    flag = LocationDifficultyFlag(
        company_id=caller.company_id,
        block_key=body.block_key,
        difficulty_tier=body.difficulty_tier,
        flagged_by=caller.id,
        notes=body.notes,
    )
    db.add(flag)
    db.commit()
    db.refresh(flag)
    return flag


# ---------------------------------------------------------------------------
# Misrouted package resolution
# ---------------------------------------------------------------------------

@router.patch("/misroutes/{flag_id}/resolve", response_model=MisroutedPackageFlagResponse)
def resolve_misroute(
    flag_id: UUID,
    db: Session = Depends(get_db),
    caller: Employee = Depends(allow_captain),
):
    flag = (
        db.query(MisroutedPackageFlag)
        .filter(MisroutedPackageFlag.id == flag_id, MisroutedPackageFlag.company_id == caller.company_id)
        .first()
    )
    if not flag:
        raise HTTPException(status_code=404, detail="Misrouted package flag not found")

    flag.resolved = True
    flag.resolved_by = caller.id
    flag.resolved_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(flag)
    return flag

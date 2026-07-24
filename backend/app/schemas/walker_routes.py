from datetime import date, datetime
from uuid import UUID
from typing import Optional, Literal
from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Capacity constants (half-slot units ×2)
# ---------------------------------------------------------------------------

EFFORT_CAPACITY: dict[str, int] = {
    "easy":     12,   # 6 slots × 2
    "standard": 12,   # 6 slots × 2
    "heavy":    8,    # 4 slots × 2
}

EFFORT_CAPACITY_PAIRED: dict[str, int] = {
    "easy":     18,   # 9 slots × 2
    "standard": 18,   # 9 slots × 2
    "heavy":    12,   # 6 slots × 2
}

# workload_class → effort_class (from BuildingProfile / BuildingProfileLibrary)
WORKLOAD_TO_EFFORT: dict[str, str] = {
    "bulk_drop":  "easy",
    "standard":   "standard",
    "high_wait":  "heavy",
    "high_touch": "heavy",
}

# OV half-slot costs
OV_HALF_SLOTS: dict[str, int] = {
    "S": 1,
    "M": 2,
    "L": 3,
    "XL": 4,
}

# A tote costs 2 HALF-slots — i.e. exactly ONE full cart slot. All capacity
# arithmetic is in half-slots (×2) to keep OV fractions integral; don't read
# this as "a tote takes two slots". OVs add half-slots per OV_HALF_SLOTS.
TOTE_HALF_SLOTS = 2


# ---------------------------------------------------------------------------
# Sort request — addresses are ephemeral, never stored
# ---------------------------------------------------------------------------

class PackageInput(BaseModel):
    tba_number: str
    bag_id: str
    bag_color: Optional[str] = None            # ADR-230: physical bag color hex, parsed from the manifest label
    block_key: Optional[str] = None            # pre-computed from enriched Redis manifest
    normalised_address: Optional[str] = None   # from GeoClient — used for BuildingProfile lookup
    package_type: Optional[str] = None         # "OV_S"|"OV_M"|"OV_L"|"OV_XL"|"standard"|None
    lat: Optional[float] = None
    lng: Optional[float] = None
    first_cross_street: Optional[str] = None   # from GeoClient — used for BFS adjacency
    second_cross_street: Optional[str] = None  # from GeoClient — used for BFS adjacency
    # LION street-segment graph (ADR-196): two segments are adjacent iff they
    # share a node. The authoritative NYC adjacency; block_key can't express it
    # (a block_key spans many segments). Cached by enrichment; None when
    # GeoClient had no segment match (~1% — falls back to coordinate adjacency).
    segment_id: Optional[str] = None
    from_lion_node_id: Optional[str] = None
    to_lion_node_id: Optional[str] = None


class SortRequest(BaseModel):
    truck_assignment_id: UUID
    route_date: date
    packages: list[PackageInput]
    # walker_count removed — routes are computed first, people assigned second
    # ovs removed — OV pairings are derived server-side from bag_id + package_type


# ---------------------------------------------------------------------------
# Sort result — no addresses in any output
# ---------------------------------------------------------------------------

class MisroutedPackageOut(BaseModel):
    tba_number: Optional[str] = None
    current_bag_id: Optional[str] = None
    destination_block_key: Optional[str] = None        # block_key it belongs to
    normalised_address: Optional[str] = None           # so the captain can find it, and resolve can move it (ADR-194)
    suggested_route_number: Optional[int] = None       # None = needs captain review


class BagGroupOut(BaseModel):
    """TBAs grouped by their bag (ADR-230). bag_id is the numeric id the driver
    reads on the physical bag; bag_color is the resolved hex tint (None → neutral
    pill). The client renders a number-only pill tinted bag_color, then the FULL
    TBAs as plain text."""
    bag_id: str
    bag_color: Optional[str] = None
    tba_numbers: list[str]


class StopOut(BaseModel):
    """One delivery stop — a unique normalised address with its packages (ADR-194).

    Built from the DELIVERED set (carried minus flagged-out riders): a flagged
    misroute is not a stop, it gets pulled at the AP. Sorted for presentation:
    blocks ascending, house numbers ascending within a block.
    """
    block_key: str
    address: str
    tba_numbers: list[str]
    # ADR-230: TBAs grouped by bag (with color). tba_numbers stays as the flat
    # union for back-compat; clients render from bags.
    bags: list[BagGroupOut] = []


class StopDetailOut(BaseModel):
    """A stop enriched for the per-employee detail page (ADR-216 Phase 1 + 3).

    Adds per-stop classification + building type + package count on top of StopOut.
    workload_class / building_type are resolved on read from BuildingProfile /
    Library (fresh — a captain's re-classification shows immediately); None when the
    stop's address has no profile yet.

    Phase 3 adds the operating hours, operational_note, troublesome_score, and the
    server-computed cutoff FACTS. The urgency gradient COLOUR is derived client-side
    from `cutoff_state` + `minutes_to_cutoff` against live `now` (a now-relative colour
    would be stale seconds after the server computed it).
    """
    block_key: str
    address: str
    tba_numbers: list[str]
    bags: list[BagGroupOut] = []            # ADR-230: TBAs grouped by bag (with color)
    package_count: int
    workload_class: Optional[str] = None    # bulk_drop | standard | high_touch | high_wait
    building_type: Optional[str] = None     # doorman | elevator | walkup | biz_freight | …
    lifecycle: str = "remaining"            # current | remaining | completed (ADR-216 phase 2 refines)

    # Phase 3 — operating hours (wall-clock "HH:MM"), note, troublesome signal.
    opens_at: Optional[str] = None
    closes_at: Optional[str] = None
    break_start: Optional[str] = None
    break_end: Optional[str] = None
    days_open: Optional[list[str]] = None
    operational_note: Optional[str] = None
    troublesome_score: Optional[float] = None

    # Phase 3 — cutoff facts (colour computed client-side from these).
    cutoff_state: str = "none"              # none | future | on_break | closed
    cutoff_at: Optional[str] = None         # "HH:MM" of the relevant closing / break-start
    reopens_at: Optional[str] = None        # "HH:MM" break_end, when cutoff_state == on_break
    minutes_to_cutoff: Optional[int] = None # signed: >0 future, <=0 overdue (future/closed only)


class RouteOut(BaseModel):
    """One cart trip — the output unit of the sort algorithm."""
    route_number: int
    block_keys: list[str]
    tote_ids: list[str]
    tba_numbers: list[str]
    slot_cost: int                  # half-slots
    capacity_limit: int             # half-slots
    capacity_limit_paired: Optional[int] = None  # ADR-212: ~1.5× ceiling on paired-capacity routes
    effort_class: str               # easy|standard|heavy|very_heavy
    effort_score: float = 0.0       # weighted normalized score snapshot
    workload_source: str            # address_profile|block_profile|flag|default
    package_count: int
    coverage_pct: float = 0.0       # fraction of packages with locked BuildingProfile
    normalised_addresses: list[str] = []
    stops: list[StopOut] = []       # delivered-set drill-down: block → address → tbas (ADR-194)
    misrouted_packages: list[MisroutedPackageOut] = []


class SortResult(BaseModel):
    truck_assignment_id: UUID
    route_date: date
    routes: list[RouteOut]
    unassigned_misroutes: list[MisroutedPackageOut]   # no destination route found (genuine captain review)
    # ADR-214: no-covering-route packages that fall OUTSIDE the company boundary —
    # not misroutes, they are out-of-zone removals (pulled at the AP, returned to
    # station). commit_sort writes these as PackageRemoval(reason=out_of_zone).
    out_of_zone_removals: list[MisroutedPackageOut] = []
    # F5 surplus signal (ADR-197 Phase 1): routes the consolidation built vs the
    # active crew. routes_built < crew_size → dispatch can release the difference.
    # None when consolidation was off (no crew_size passed).
    routes_built: Optional[int] = None
    crew_size: Optional[int] = None


# ---------------------------------------------------------------------------
# Wave distribution — assigning people to routes
# ---------------------------------------------------------------------------

class WaveAssignmentEntry(BaseModel):
    route_number: int
    employee_id: UUID
    # D9.2 (ADR-187): frontend marks whether this row was accepted from the
    # auto-proposal as-is (True), human-overridden (False), or manual/unknown
    # (None). The accept audit aggregates these — per-signal override rate is
    # the primary weight-tuning feedback for the smart matcher.
    auto_proposed: Optional[bool] = None


class WaveDistributionRequest(BaseModel):
    """Assign routes to confirmed staff at the anchor point.

    When auto_assign=True the server returns a WaveDistributionProposal without
    committing anything. The trainer reviews, adjusts, then resubmits with
    auto_assign=False and the finalized assignments list.
    When auto_assign=False (default) assignments must be fully populated.
    """
    truck_assignment_id: UUID
    route_date: date
    assignments: list[WaveAssignmentEntry] = []
    # Optional at the schema level: auto_assign=True is a PROPOSAL-ONLY call
    # (ADR-139 §5 — nothing is committed; the auto branch never reads
    # trainer_id) and the frontend sends null/omits it there. Requiring a UUID
    # here 422'd every auto-propose. The endpoint enforces trainer_id where it
    # is actually consumed: the manual branch's trainee-pairing sync.
    trainer_id: Optional[UUID] = None
    trainee_id: Optional[UUID] = None
    trainee_phase: Optional[int] = Field(None, ge=1, le=5)
    auto_assign: bool = False


class RouteReassignRequest(BaseModel):
    """Move a single route from its current assignee to a new one."""
    new_employee_id: UUID
    new_employee_name: str


# ---------------------------------------------------------------------------
# Arrival confirmation — triggers 1.5× rebalance
# ---------------------------------------------------------------------------

class ArrivalConfirmRequest(BaseModel):
    truck_assignment_id: UUID
    route_date: date
    # Optional since the ADR-145 flow rework: the pair is DERIVED from the
    # dispatch pairing (AssignmentMember.paired_trainer_id) — arbitrary
    # trainer/trainee combinations were never meaningful. Explicit ids remain
    # honored for the multi-pair disambiguation case.
    trainer_id: Optional[UUID] = None
    trainee_id: Optional[UUID] = None


class ArrivalConfirmResponse(BaseModel):
    sort_not_yet_committed: bool
    paired_route: Optional["RouteResponse"]
    absorbed_route_numbers: list[int]
    trimmed_route_numbers: list[int]
    paired_capacity_limit: int


# ---------------------------------------------------------------------------
# DB response schemas
# ---------------------------------------------------------------------------

class ParticipantOut(BaseModel):
    """A route participant with the employee name resolved (ADR-212)."""
    id: UUID          # employee_id
    name: str


class RouteResponse(BaseModel):
    id: UUID
    truck_assignment_id: UUID
    route_date: date
    route_number: int
    wave_number: int = 1
    block_keys: list[str]
    tote_ids: list[str]
    tba_numbers: list[str]
    normalised_addresses: list[str] = []
    # None = route predates the stops column (ADR-194) — clients fall back to the flat lists
    stops: Optional[list[StopOut]] = None
    slot_cost: int
    capacity_limit: int
    capacity_limit_paired: Optional[int] = None
    package_count: int
    effort_class: str
    effort_score: Optional[float] = None
    workload_source: str
    coverage_pct: Optional[float] = None
    # ADR-212: membership. executor = assignee-of-record (nullable until wave
    # distribution); supervisors = trainers overseeing the route ([] when solo).
    executor: Optional[ParticipantOut] = None
    supervisors: list[ParticipantOut] = []
    trainee_phase: Optional[int] = None
    phase4_solo_opted_in: bool
    status: str
    departed_at: Optional[datetime] = None
    returned_at: Optional[datetime] = None
    # ADR-229: set when the walker (or a captain) raised request-help; gates the
    # crew-row "cover remaining stops" emergency split on the client.
    help_requested_at: Optional[datetime] = None
    created_at: datetime
    misrouted_packages: list["MisroutedPackageFlagResponse"] = []
    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_route(cls, route, name_by_id: dict) -> "RouteResponse":
        """Build from a Route ORM object + an {employee_id: name} map.

        Names live on Employee, not on RouteParticipant (ADR-212 §1 — no
        denormalised name), so the router supplies a resolved name map.
        """
        def _part(employee_id):
            return ParticipantOut(id=employee_id, name=name_by_id.get(employee_id, ""))

        executor_id = route.executor_id
        obj = cls.model_validate(route, from_attributes=True)
        obj.executor = _part(executor_id) if executor_id else None
        obj.supervisors = [_part(sid) for sid in route.supervisor_ids]
        return obj


class RouteStatusPatch(BaseModel):
    status: Literal["assigned", "in_progress", "completed"]


class RouteDetailResponse(BaseModel):
    """Per-employee route detail for the crew drill-down (ADR-216).

    The route's identity + executor/supervisors + effort, plus stops enriched with
    classification / building type / package count and grouped by block_key (the
    "segment" label). Stops are ordered current → remaining → completed via the
    `lifecycle` field on each StopDetailOut.
    """
    id: UUID
    route_number: int
    route_date: date
    status: str
    effort_class: str
    executor: Optional[ParticipantOut] = None
    supervisors: list[ParticipantOut] = []
    package_count: int
    stops: list[StopDetailOut] = []
    # Phase 3 — urgency-gradient windows (minutes), so the client colours match
    # the operator's tuning: red within `urgent_window`, yellow the `caution_window`
    # immediately before it, green/blue beyond.
    urgent_window_minutes: int = 60
    caution_window_minutes: int = 60
    model_config = ConfigDict(from_attributes=True)


class PairSplitResponse(BaseModel):
    """Result of splitting a pair (ADR-213): the trainee's now-solo route and the
    trainer's newly-assigned route, plus how many overflow totes moved across."""
    trainee_route: "RouteResponse"
    trainer_route: "RouteResponse"
    overflow_totes_moved: int


class CoverRemainingResponse(BaseModel):
    """ADR-229 — result of an emergency split of an in-progress route. The original
    route capped at delivered + closed; the undelivered stops moved to a new
    unassigned covering route for the captain to assign via the wave/reassign UI."""
    original_route: "RouteResponse"
    covering_route: "RouteResponse"
    stops_moved: int


# ---------------------------------------------------------------------------
# Wave pool — second-wave return mechanic
# ---------------------------------------------------------------------------

class ReturnedWalkerRoute(BaseModel):
    route_number: int
    wave_number: int
    package_count: int
    effort_class: str


class ReturnedWalker(BaseModel):
    employee_id: UUID
    employee_name: str
    injury_status: Optional[str] = None
    completed_routes: list[ReturnedWalkerRoute]


class UnassignedRouteEntry(BaseModel):
    route_id: UUID
    route_number: int
    effort_class: str
    package_count: int
    slot_cost: int
    wave_number: int


class WaveStatusCounts(BaseModel):
    assigned: int = 0
    in_progress: int = 0
    completed: int = 0
    unassigned: int = 0


class WaveSummary(BaseModel):
    """Per-wave status breakdown, keyed by wave number (1-based string key).

    Returned as {"1": {...}, "2": {...}, ...} — clients iterate over keys
    rather than hardcoded field names so any number of waves is supported.
    """
    waves: dict[str, WaveStatusCounts]
    total_routes: int


class WavePoolResponse(BaseModel):
    returned_walkers: list[ReturnedWalker]
    unassigned_routes: list[UnassignedRouteEntry]
    wave_summary: WaveSummary


# ---------------------------------------------------------------------------
# Wave distribution — auto_assign proposal mode
# ---------------------------------------------------------------------------

class ProposedAssignmentEntry(BaseModel):
    route_number: int
    route_id: UUID
    employee_id: UUID
    employee_name: str
    effort_class: str
    auto_proposed: bool = False


class WaveDistributionProposal(BaseModel):
    """Returned when auto_assign=True — trainer reviews before confirming."""
    proposed_assignments: list[ProposedAssignmentEntry]
    conflicts: list[str]   # human-readable strings when injury constraints can't be fully satisfied


# ---------------------------------------------------------------------------
# Commit sort — persist Route rows from SortResult
# ---------------------------------------------------------------------------

class CommitSortRequest(BaseModel):
    """Commit a route sort for a truck assignment.

    Server loads packages from the enriched Redis manifest via TruckZone.package_tbas.
    OV pairings are derived server-side from bag_id grouping + package_type — the
    trainer does not need to supply them.
    """
    truck_assignment_id: UUID
    route_date: date


class CommitSortResponse(BaseModel):
    routes: list[RouteResponse]
    packages_sorted: int
    packages_dropped: int
    dropped_tbas: list[str]
    unassigned_misroutes: list[MisroutedPackageOut]


# ---------------------------------------------------------------------------
# Difficulty flags and misroutes
# ---------------------------------------------------------------------------

class LocationDifficultyFlagCreate(BaseModel):
    block_key: str
    difficulty_tier: Literal["standard", "moderate", "heavy"]
    notes: Optional[str] = Field(None, max_length=500)


class LocationDifficultyFlagResponse(BaseModel):
    id: UUID
    block_key: str
    difficulty_tier: str
    flagged_by: Optional[UUID] = None
    flagged_at: datetime
    notes: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


class MisroutedPackageFlagResponse(BaseModel):
    id: UUID
    route_id: UUID
    tba_number: str
    current_bag_id: str
    destination_block_key: Optional[str] = None
    normalised_address: Optional[str] = None
    suggested_route_id: Optional[UUID] = None
    resolved: bool
    resolved_by: Optional[UUID] = None
    resolved_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


class MisrouteResolveRequest(BaseModel):
    destination_route_id: UUID


# Phase 4 opt-in
class Phase4OptInRequest(BaseModel):
    route_number: int
    truck_assignment_id: UUID
    route_date: date



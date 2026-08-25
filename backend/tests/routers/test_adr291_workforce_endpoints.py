"""ADR-291 D7-D9 — the workforce routing endpoints.

The refusals are what matter:

  - re-sorting must NOT delete a route a walker is already holding (409)
  - an overflow must be OPTED INTO, never a silent side effect (409 by default)
  - reassigning a route that is already out must be refused
  - a lookup that matches nothing must say "escalate", not guess

Plus the structural guarantee: this router is gated to WORKFORCE mode, the
mirror of walker_routes' `full` gate, so exactly one routing path is reachable
per company.
"""
import inspect
import uuid
from datetime import date

import pytest
from fastapi import HTTPException

from app.routers import workforce_routes as W
from app.routers.workforce_routes import (
    AssignWalkerIn, CommitWorkforceSortIn, RouteLookupIn, ToteAddressIn,
)


# ── request schemas (dim 9) ───────────────────────────────────────────────────

def test_payloads_reject_unknown_keys():
    for model, kwargs in (
        (ToteAddressIn, dict(truck_id=uuid.uuid4(), entry_date=date.today(),
                             bag_id="5270", raw_address="411 W 36 St")),
        (CommitWorkforceSortIn, dict(truck_assignment_id=uuid.uuid4(),
                                     route_date=date.today())),
        (AssignWalkerIn, dict(employee_id=uuid.uuid4())),
        (RouteLookupIn, dict(truck_assignment_id=uuid.uuid4(),
                             raw_address="411 W 36 St")),
    ):
        model(**kwargs)                       # valid payload builds
        with pytest.raises(Exception):
            model(**kwargs, bogus=1)          # unknown key rejected


def test_address_is_length_bounded():
    """Attacker-controlled free text landing in a String(300) column."""
    with pytest.raises(Exception):
        ToteAddressIn(truck_id=uuid.uuid4(), entry_date=date.today(),
                      bag_id="5270", raw_address="x" * 301)
    with pytest.raises(Exception):
        ToteAddressIn(truck_id=uuid.uuid4(), entry_date=date.today(),
                      bag_id="5270", raw_address="ab")     # min_length=3


def test_overflow_is_off_by_default():
    """D7: an overflow must be a deliberate act. Defaulting it on would make
    every capacity limit advisory without anyone choosing that."""
    payload = CommitWorkforceSortIn(truck_assignment_id=uuid.uuid4(),
                                    route_date=date.today())
    assert payload.allow_overflow is False


# ── mode gating: exactly one routing path per company ─────────────────────────

def test_router_is_gated_to_workforce_mode():
    """The mirror of walker_routes' full-mode gate. A tenant with a manifest must
    not also have this weaker path; a tenant without one has only this."""
    main_src = (
        __import__("pathlib").Path(W.__file__).parent.parent / "main.py"
    ).read_text()
    assert "workforce_routes.router" in main_src
    line = next(l for l in main_src.splitlines() if "workforce_routes.router" in l)
    assert "_workforce_mode" in line, f"not gated to workforce mode: {line.strip()}"


def test_walker_routes_stays_gated_to_full_mode():
    """Guards the other half of the pair — if this drifts, both paths become
    reachable at once and a full-mode tenant gets two sorts."""
    main_src = (
        __import__("pathlib").Path(W.__file__).parent.parent / "main.py"
    ).read_text()
    line = next(l for l in main_src.splitlines() if "walker_routes.router" in l)
    assert "_full_mode" in line


# ── role gates (dim 2) ────────────────────────────────────────────────────────

def test_write_endpoints_require_route_lead():
    """Building and assigning routes is route-lead work (ADR-256 D5). A walker
    must not be able to assign themselves a route."""
    for fn in (W.add_tote_address, W.delete_tote_address, W.commit_workforce_sort,
               W.assign_walker, W.route_lookup):
        gates = [
            getattr(p.default.dependency, "allowed_roles", None)
            for p in inspect.signature(fn).parameters.values()
            if getattr(p.default, "dependency", None) is not None
        ]
        roles = next((g for g in gates if g), None)
        assert roles is not None, f"{fn.__name__} has no role gate"
        assert "walker" not in roles, f"{fn.__name__} lets a walker write"
        assert "captain" in roles, f"{fn.__name__} excludes the captain"


def test_read_endpoint_includes_field_staff():
    """A walker reads what is on their truck; they just cannot change it."""
    gates = [
        getattr(p.default.dependency, "allowed_roles", None)
        for p in inspect.signature(W.list_tote_addresses).parameters.values()
        if getattr(p.default, "dependency", None) is not None
    ]
    roles = next(g for g in gates if g)
    assert "walker" in roles and "captain" in roles


# ── no fabricated data ────────────────────────────────────────────────────────

def test_cross_streets_are_not_faked():
    """ResolvedAddress carries no cross-street fields (verified: lat/lng/
    normalised_address/block_key/segment_id/geocoded). An earlier draft used
    getattr(resolved, "first_cross_street", None), which writes None forever
    while looking like a populated column."""
    from app.services.package_intake import ResolvedAddress
    assert not hasattr(ResolvedAddress, "first_cross_street")

    src = inspect.getsource(W.add_tote_address)
    assert "getattr(resolved" not in src, "reintroduced a silent-None fallback"
    assert "first_cross_street=" not in src


def test_workforce_routes_store_no_addresses_or_segments():
    """ADR-219: addresses live on ToteAddress and are purged there. ADR-291 D10:
    workforce mode builds no segment infrastructure, so segment_ids must be
    empty rather than fabricated."""
    src = inspect.getsource(W.commit_workforce_sort)
    assert "normalised_addresses=[]" in src
    assert "segment_ids=[]" in src
    assert "stops=None" in src


# ── the sort reuses the real algorithm (D5) ───────────────────────────────────

def test_commit_sort_calls_the_genuine_run_sort():
    """If this router ever grows its own traversal, ADR-291 D5 is violated and
    1,700 lines of the deepest IP in the product exist twice."""
    src = inspect.getsource(W.commit_workforce_sort)
    assert "run_sort(" in src
    # It must not reimplement the block walk.
    for forbidden in ("_build_routes", "_seed_priority", "_nearest_neighbor_block"):
        assert forbidden not in src, f"reimplements {forbidden}"


def test_overflow_is_computed_not_trusted():
    """slot_cost and capacity_limit come from the sort's own output. Taking an
    overflow figure from the client would let a caller under-report it."""
    src = inspect.getsource(W.commit_workforce_sort)
    assert "max(0, (r.slot_cost or 0) - (r.capacity_limit or 0))" in src


# ── route lookup ranking (D9) ─────────────────────────────────────────────────

def test_lookup_ranks_on_block_not_segment():
    """D9/D10: workforce mode has no populated segment map, so ranking on
    segments would sort every candidate identically on empty data.

    Checks the CODE, not the docstring — the docstring says the word "segment"
    precisely to explain why it is not used, and an earlier version of this test
    failed on its own explanation.
    """
    src = inspect.getsource(W.route_lookup)
    body = src[src.index('"""', src.index('"""') + 3) + 3:]      # strip docstring
    code = "\n".join(l for l in body.splitlines() if not l.strip().startswith("#"))

    assert "segment" not in code.lower(), "route lookup touches segment data"
    assert "exact_block" in code and "adjacent_block" in code and "same_street" in code


def test_lookup_escalates_rather_than_guessing():
    """Nothing matched means say so. A best-effort guess sends a package to the
    wrong walker with the same confidence as a real match."""
    src = inspect.getsource(W.route_lookup)
    assert "escalate=True" in src


def test_lookup_tiers_are_ordered_best_first():
    src = inspect.getsource(W.route_lookup)
    assert '{"exact_block": 0, "adjacent_block": 1, "same_street": 2}' in src


# ── the refusals ──────────────────────────────────────────────────────────────

def test_resort_never_deletes_a_route_whose_totes_left_the_truck():
    """A walker holding a route must not have it deleted underneath them.

    REWRITTEN for ADR-302. The original asserted the literal string
    `r.status in ("assigned", "in_progress")` — the very guard ADR-302 found
    INVERTED. It blocked the whole re-sort on `in_progress`, which defeats the
    purpose of a mid-day re-sort (some walkers are always already out), while
    treating `assigned` — a name on a plan, totes still in the truck — as
    equally untouchable.

    The invariant that actually matters is unchanged and is now asserted as
    BEHAVIOUR rather than as a source literal: a status whose totes have left
    the truck can never enter the delete set.
    """
    from app.services.constants import DELETABLE_ON_RESORT

    # in_progress: departed_at is stamped, the walker is gone with the totes.
    # completed: delivered, and six tables CASCADE off routes (ADR-304).
    assert "in_progress" not in DELETABLE_ON_RESORT
    assert "completed" not in DELETABLE_ON_RESORT

    # `assigned` is deliberately NOT deletable-by-default either: it needs the
    # captain's explicit clear (D2a), so the default is "nothing happens".
    assert "assigned" not in DELETABLE_ON_RESORT

    src = inspect.getsource(W.commit_workforce_sort)
    assert "DELETABLE_ON_RESORT" in src
    assert "HTTP_409_CONFLICT" in src


def test_reassigning_a_route_that_is_out_is_refused():
    src = inspect.getsource(W.assign_walker)
    assert 'route.status == "in_progress"' in src
    assert "HTTP_409_CONFLICT" in src


def test_assignment_replaces_the_executor_rather_than_adding_one():
    """ADR-212: exactly one executor per route, enforced by a partial unique
    index. Adding a second would raise an IntegrityError and 500."""
    src = inspect.getsource(W.assign_walker)
    assert "RouteParticipant.role == \"executor\"" in src
    assert ".delete(" in src


def test_empty_entry_is_a_422_not_an_empty_sort():
    """Sorting nothing would produce zero routes and look like success."""
    src = inspect.getsource(W.commit_workforce_sort)
    assert "No tote addresses entered" in src


# ── audit + PII ───────────────────────────────────────────────────────────────

def test_writes_are_audited():
    for fn in (W.add_tote_address, W.delete_tote_address,
               W.commit_workforce_sort, W.assign_walker):
        assert "write_audit" in inspect.getsource(fn), f"{fn.__name__} is unaudited"


def test_audit_detail_carries_no_address():
    """Dimension 7: block_key is the durable non-identifying fact; the address
    itself must not be copied into an immutable audit row that outlives the
    ADR-219 purge.

    The slice is bounded to the write_audit CALL. An earlier version ran to the
    end of the function and swept in the response builder — which legitimately
    returns the address to the captain who just typed it — and reported a
    violation that was not there.
    """
    src = inspect.getsource(W.add_tote_address)
    start = src.index("write_audit")
    audit_call = src[start:src.index("db.commit()", start)]

    assert "raw_address" not in audit_call
    assert "normalised_address" not in audit_call
    assert "block_key" in audit_call


def test_route_lookup_writes_nothing():
    """It is a POST only because the address is a request body — a GET would put
    a customer address in the query string, the URL bar and every access log
    (dim 7). The audit-coverage allowlist records the same reasoning; this
    asserts the property it claims."""
    src = inspect.getsource(W.route_lookup)
    for writer in ("db.add", "db.commit", "db.delete", "db.flush", ".update("):
        assert writer not in src, f"route_lookup calls {writer}"


# ── per-route package count (D11) ─────────────────────────────────────────────

def test_flex_count_payload_is_bounded():
    from app.routers.workforce_routes import FlexPackageCountIn
    FlexPackageCountIn(package_count=0)          # a route that carried nothing
    FlexPackageCountIn(package_count=250)
    with pytest.raises(Exception):
        FlexPackageCountIn(package_count=-1)
    with pytest.raises(Exception):
        FlexPackageCountIn(package_count=2001)
    with pytest.raises(Exception):
        FlexPackageCountIn(package_count=100, bogus=1)


def test_flex_count_is_nullable_not_zero_defaulted():
    """NULL means 'not recorded yet'; 0 means the route genuinely carried
    nothing. A NOT NULL default of 0 makes those indistinguishable — the
    zero-versus-absence failure ADR-294 exists to prevent."""
    from app.models.walker_route import Route
    assert Route.__table__.c.flex_package_count.nullable
    assert Route.__table__.c.flex_package_count.default is None
    assert Route.__table__.c.flex_package_count.server_default is None


def test_flex_count_is_separate_from_derived_package_count():
    """package_count is sum(len(t.packages)) from the sort, and a workforce
    'package' is a captain-entered ADDRESS. Overwriting it would corrupt the
    field dashboards and assignment history already read."""
    src = inspect.getsource(W.record_flex_package_count)
    assert "route.flex_package_count = payload.package_count" in src
    assert "route.package_count =" not in src, "clobbers the sort's own count"


def test_flex_count_is_re_recordable_until_the_route_closes():
    """Deliberately NOT a one-way stamp. A miscounted scan is corrected in the
    moment, and a 409 on every second attempt would leave a known-wrong number
    in the reporting. The audit carries before/after so the correction is
    traceable.

    AMENDED by ADR-300 D5. The original asserted `HTTP_409_CONFLICT not in src`
    — a blanket "never refuses". It now refuses in exactly one case: after the
    route is CLOSED, when the count has become the day's persisted record
    (ADR-299 D4) and a late re-record would silently change a number the day was
    already reported on. Re-recording before the close is unchanged.
    """
    src = inspect.getsource(W.record_flex_package_count)
    assert "previous = route.flex_package_count" in src
    assert "before={" in src and "after={" in src

    # The ONLY refusal is the post-close freeze, and it is conditioned on
    # returned_at — not on the count already having a value.
    assert "route.returned_at is not None" in src
    assert src.count("HTTP_409_CONFLICT") == 1, (
        "re-recording before the close must stay unrestricted"
    )


def test_flex_count_endpoint_is_route_lead_gated():
    gates = [
        getattr(p.default.dependency, "allowed_roles", None)
        for p in inspect.signature(W.record_flex_package_count).parameters.values()
        if getattr(p.default, "dependency", None) is not None
    ]
    roles = next(g for g in gates if g)
    assert "captain" in roles and "walker" not in roles

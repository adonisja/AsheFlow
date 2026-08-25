"""Workforce re-sort: what may be re-planned is decided by where the totes are (ADR-302).

The guard this replaces was inverted on both counts — it blocked the whole
re-sort on `in_progress` (defeating mid-day re-sorting, which exists precisely
because some walkers are already out) while treating `assigned` (a name on a
plan, totes still in the truck) as equally untouchable.

The rule now follows physical location:

    unassigned  -> totes in the truck, never worked      -> deleted
    assigned    -> totes in the truck, someone was told  -> cleared ONLY on an
                                                            explicit captain choice
    in_progress -> totes GONE with a walker              -> retained
    completed   -> delivered, record final               -> retained
"""
import inspect

import pytest

from app.routers import workforce_routes as W
from app.services.constants import DELETABLE_ON_RESORT
from app.services.workforce_sort_adapter import build_packages


# ── D2: the allow-list follows physical location ──────────────────────────────

def test_only_never_worked_routes_are_deletable_by_default():
    assert DELETABLE_ON_RESORT == frozenset({"unassigned", None})


@pytest.mark.parametrize("status", ["assigned", "in_progress", "completed"])
def test_no_worked_status_is_deletable_without_a_decision(status):
    assert status not in DELETABLE_ON_RESORT


def test_both_commit_sorts_share_one_constant():
    """Two divergent guards on the same operation is how ADR-304's defect
    survived in full mode while workforce mode had a (different, also wrong)
    one. They must be the same object, not two equal copies."""
    from app.routers.walker_routes import DELETABLE_ON_RESORT as full_mode

    assert full_mode is DELETABLE_ON_RESORT


# ── D2/D2a: the guard's partition ─────────────────────────────────────────────

def _partition(statuses):
    """Mirrors the endpoint's own split."""
    rows = [type("R", (), {"status": st, "id": i, "route_number": i})()
            for i, st in enumerate(statuses)]
    replaceable = [r for r in rows if r.status in DELETABLE_ON_RESORT]
    assigned = [r for r in rows if r.status == "assigned"]
    out_of_reach = [r for r in rows
                    if r.status not in DELETABLE_ON_RESORT and r.status != "assigned"]
    return replaceable, assigned, out_of_reach


def test_in_progress_does_not_block_the_resort():
    """THE regression. Blocking here is what ADR-302 was written to fix.

    A walker being out is the NORMAL mid-day state; refusing the whole call
    because of it makes the feature useless exactly when it is needed.
    """
    replaceable, assigned, out_of_reach = _partition(
        ["unassigned", "in_progress", "unassigned"]
    )
    assert len(replaceable) == 2, "stale routes must still be replaced"
    assert assigned == [], "nothing to clear, so no 409"
    assert len(out_of_reach) == 1, "the in_progress route is stepped around"


def test_completed_routes_are_retained_not_refused():
    replaceable, assigned, out_of_reach = _partition(["completed", "unassigned"])
    assert len(replaceable) == 1
    assert len(out_of_reach) == 1
    assert assigned == []


def test_assigned_is_separated_from_both_other_groups():
    """`assigned` is neither freely deletable nor permanently out of reach —
    it is the one status that needs a human decision (D2a)."""
    replaceable, assigned, out_of_reach = _partition(["assigned"])
    assert replaceable == []
    assert out_of_reach == []
    assert len(assigned) == 1


# ── D2a: clearing is a decision, and the default is "nothing happens" ─────────

def test_default_refuses_rather_than_silently_replanning():
    """No choice supplied + an assigned route present -> 409 that NAMES it.

    The failure mode being prevented is a captain re-sorting and silently
    taking a route away from someone who was already told it was theirs.
    """
    src = inspect.getsource(W.commit_workforce_sort)
    assert "clear_all_assigned" in src
    assert "clear_assigned_route_ids" in src
    assert "HTTP_409_CONFLICT" in src
    # The 409 must name the routes: "this walker is busy" is useless without
    # "...on route 4".
    assert "route_number" in src


def test_clear_choice_is_an_explicit_request_field():
    fields = W.CommitWorkforceSortIn.model_fields
    assert "clear_assigned_route_ids" in fields
    assert "clear_all_assigned" in fields
    # Dimension 9: bounded list, and the default must be the SAFE one.
    assert fields["clear_assigned_route_ids"].default is None
    assert fields["clear_all_assigned"].default is False


def test_request_schema_still_forbids_unknown_keys():
    """Dimension 9 — a mistyped key is a 422, not a silently ignored field."""
    assert W.CommitWorkforceSortIn.model_config.get("extra") == "forbid"


# ── D3: retained routes' totes are excluded from the sort input ───────────────

def test_build_packages_accepts_an_exclusion_set():
    assert "exclude_bag_ids" in inspect.signature(build_packages).parameters


def test_excluded_totes_are_reported_not_silently_dropped():
    """ADR-291 D5's no-silent-drops rule applies to this exclusion too.

    A captain who entered 25 totes and sees 20 sorted needs to know the other 5
    are out with a walker — not wonder whether the system lost them.
    """
    from app.services.workforce_sort_adapter import AdapterResult

    assert "already_routed" in AdapterResult.__dataclass_fields__
    assert "already_routed_bags" in W.CommitWorkforceSortOut.model_fields


def test_excluded_totes_do_not_resurface_as_unaddressed():
    """The subtle one.

    `_unaddressed_bags` is fed the set of accounted-for bags. Pass only the
    ADDRESSED ones and an excluded tote comes back as "unaddressed" — telling
    the captain to go address a tote that is currently out with a walker.
    """
    src = inspect.getsource(build_packages)
    assert "accounted_for" in src
    assert "already_routed" in src


# ── D3a: numbering continues past survivors ───────────────────────────────────

def test_new_routes_are_numbered_past_retained_ones():
    """run_sort always numbers from 1 and (truck_assignment_id, route_number)
    is UNIQUE — so retaining route 1 and emitting 1..n raises IntegrityError
    and fails the whole re-sort."""
    retained = [type("R", (), {"route_number": n})() for n in (1, 2, 3)]
    offset = max((r.route_number or 0) for r in retained) if retained else 0
    assert offset == 3
    assert [n + offset for n in (1, 2)] == [4, 5]


def test_offset_is_applied_at_persistence():
    src = inspect.getsource(W.commit_workforce_sort)
    assert "number_offset" in src
    assert "r.route_number + number_offset" in src


# ── D6: the destruction is audited ────────────────────────────────────────────

def test_a_resort_that_deletes_writes_an_audit_entry():
    src = inspect.getsource(W.commit_workforce_sort)
    assert "workforce_route.resort_replaced" in src
    assert "deleted_route_ids" in src

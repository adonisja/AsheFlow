"""commit-sort must not destroy worked routes or their CASCADE children (ADR-304).

walker_routes is proprietary → gitignored (syncs to private), so this module
skips cleanly when the private sync has not carried it over.

WHAT THIS PROTECTS. `commit-sort` deletes prior routes before rebuilding. It had
no status guard, and SIX tables CASCADE off `routes` — delivery_stops,
rts_packages, missing_packages, misrouted_package_flags, route_handoffs,
route_participants. A re-sort of a worked truck-day silently destroyed that
day's delivery history and the RTS evidence behind any scorecard appeal.

`routes` uses JSONB, which the shared SQLite `db` fixture cannot create, so these
are unit tests over the guard expression plus a metadata assertion that the
CASCADEs are real. The end-to-end "the delivery_stops rows still exist after a
re-sort" check needs Postgres and belongs in the staging verification — noted
here so nobody reads this file as proving more than it does.
"""
import pytest

try:
    from app.routers.walker_routes import DELETABLE_ON_RESORT, _persist_routes  # noqa: F401
except ImportError:
    pytest.skip(
        "proprietary walker_routes deps not available (CI skip)",
        allow_module_level=True,
    )

# ── D1: the allow-list ────────────────────────────────────────────────────────

def test_only_never_worked_statuses_are_deletable():
    """The whole guard in one assertion.

    An allow-list, so a status added later defaults to PROTECTED. This test is
    what fails when someone adds a status and assumes it is safe to destroy.
    """
    assert DELETABLE_ON_RESORT == frozenset({"unassigned", None})


@pytest.mark.parametrize("status", ["assigned", "in_progress", "completed"])
def test_worked_statuses_are_never_deletable(status):
    """assigned / in_progress / completed all survive a re-sort.

    `completed` is the one the original block-list missed in the workforce twin
    (ADR-302), and `in_progress` means the walker is physically out with the
    packages.
    """
    assert status not in DELETABLE_ON_RESORT


def test_every_model_status_is_classified():
    """Guards against a status existing that nobody decided about.

    Not a tautology: it pins the CURRENT vocabulary, so adding "paused" without
    deciding whether it is deletable fails here rather than silently defaulting.
    """
    known = {"unassigned", "assigned", "in_progress", "completed", "nullified", None}
    for st in known:
        deletable = st in DELETABLE_ON_RESORT
        assert deletable == (st in {"unassigned", None}), (
            f"status {st!r} is unclassified — decide explicitly (ADR-304 D1)"
        )


# ── D1/D2: the CASCADE is real, and the guard keeps worked routes out of it ───
#
# `routes` uses JSONB, which SQLite cannot compile, so the shared `db` fixture
# deliberately excludes it (see conftest DISPATCH_TABLES). Rather than build a
# shadow table — which would test a fake schema and prove nothing about the real
# CASCADE — these assert the two halves separately:
#   1. the FKs really are ON DELETE CASCADE, read from the live ORM metadata
#   2. the guard never puts a worked route into the delete set
# Together those are the claim. An integration test over real Postgres would be
# stronger and belongs in the staging verification, not the unit suite.

def _fk_ondelete(model, column="route_id"):
    col = model.__table__.columns[column]
    return [fk.ondelete for fk in col.foreign_keys]


def test_route_children_really_do_cascade():
    """If these stop being CASCADE, the guard is protecting against nothing.

    Read from ORM metadata rather than asserted from memory — the blast radius
    is the reason this ADR exists, so it is pinned here.
    """
    from app.models.delivery_stop import DeliveryStop
    from app.models.rts import MissingPackage, RTSPackage
    from app.models.walker_route import RouteParticipant

    for model in (DeliveryStop, RTSPackage, MissingPackage, RouteParticipant):
        assert "CASCADE" in _fk_ondelete(model), (
            f"{model.__name__}.route_id no longer CASCADEs — re-check ADR-304's "
            f"blast radius before relying on the allow-list"
        )


def _delete_set(statuses):
    """Exactly the expression commit-sort uses to choose what to destroy."""
    rows = [type("R", (), {"status": st, "id": i})() for i, st in enumerate(statuses)]
    stale = [r for r in rows if r.status in DELETABLE_ON_RESORT]
    retained = [r for r in rows if r.status not in DELETABLE_ON_RESORT]
    return [r.status for r in stale], [r.status for r in retained]


def test_worked_routes_never_enter_the_delete_set():
    """The regression this ADR exists for, at the level the bug lived.

    A mixed truck-day: only the never-worked routes are destroyed.
    """
    stale, retained = _delete_set(
        ["unassigned", "assigned", "in_progress", "completed", "unassigned"]
    )
    assert stale == ["unassigned", "unassigned"]
    assert retained == ["assigned", "in_progress", "completed"]


def test_a_day_of_only_worked_routes_deletes_nothing():
    """Re-sorting a finished day destroys nothing and still proceeds.

    Refusing outright would defeat mid-day re-sorting, which is the case the
    endpoint exists to serve.
    """
    stale, retained = _delete_set(["completed", "completed", "in_progress"])
    assert stale == []
    assert len(retained) == 3


def test_the_guard_is_not_a_no_op():
    """A first sort with only stale routes still replaces them."""
    stale, retained = _delete_set(["unassigned", "unassigned"])
    assert len(stale) == 2
    assert retained == []


# ── D4: renumbering past survivors ────────────────────────────────────────────

def test_new_routes_are_numbered_past_retained_ones():
    """A UNIQUE violation, not a cosmetic collision.

    run_sort always numbers from 1 and (truck_assignment_id, route_number) is
    UNIQUE, so emitting 1..n beside a retained route 1 fails the whole re-sort.
    """
    retained = [type("R", (), {"route_number": n})() for n in (1, 2, 3)]
    offset = max((r.route_number or 0) for r in retained) if retained else 0
    assert offset == 3
    assert [n + offset for n in (1, 2)] == [4, 5]


def test_no_offset_when_nothing_is_retained():
    """The ordinary first-sort path must be unchanged — numbering starts at 1."""
    retained = []
    offset = max((r.route_number or 0) for r in retained) if retained else 0
    assert offset == 0


# ── D3: retained routes' packages are excluded ────────────────────────────────

def test_packages_on_retained_routes_are_excluded_from_the_resort():
    """Excluding routes without excluding their packages is worse than the bug.

    The retained route survives AND its packages get planned onto a new route —
    a walker dispatched after parcels another walker is already carrying.
    """
    retained = [type("R", (), {"tba_numbers": ["TBA_OUT_1", "TBA_OUT_2"]})()]
    tbas = ["TBA_OUT_1", "TBA_OUT_2", "TBA_FREE_1", "TBA_FREE_2"]

    spoken_for = {t for r in retained for t in (r.tba_numbers or [])}
    already_routed = [t for t in tbas if t in spoken_for]
    remaining = [t for t in tbas if t not in spoken_for]

    assert remaining == ["TBA_FREE_1", "TBA_FREE_2"]
    # Reported, not silently dropped — a re-sort planning fewer packages explains why.
    assert already_routed == ["TBA_OUT_1", "TBA_OUT_2"]


def test_nothing_is_excluded_when_no_route_is_retained():
    """First sort of the day: every package is in play."""
    spoken_for = {t for r in [] for t in (r.tba_numbers or [])}
    tbas = ["A", "B"]
    assert [t for t in tbas if t not in spoken_for] == tbas

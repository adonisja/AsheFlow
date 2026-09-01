"""The captain's Field Ops is the crew roster (ADR-319).

A captain opened Field Ops and saw a title, a date, and an empty page. The
screen computes `isDriver = hasRole('driver')` and puts its whole body behind
it, so a captain passed the tab gate, reached the screen, and matched no render
branch. Reachable and empty is worse than absent: absence at least tells you
where you stand.

Nothing needed building on the server. The screen already fetched
/roll-call/my-truck/{today}, already held `crew` and `rollCall` in state, and
the gates already admitted captains.
"""
import inspect
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
MOBILE = BACKEND.parent / "mobile" / "src"
FIELD_OPS = MOBILE / "screens" / "FieldOps" / "FieldOpsScreen.tsx"
PANEL = MOBILE / "components" / "route" / "CrewRosterPanel.tsx"


def _gates(fn):
    for p in inspect.signature(fn).parameters.values():
        roles = getattr(getattr(p.default, "dependency", None), "allowed_roles", None)
        if roles:
            return set(roles)
    return set()


# ── D5: gear was a role-list omission, not a rendering bug ───────────────────

def test_captain_can_read_and_request_gear():
    """`captain` was the ONLY field role missing from allow_all, so the Gear tab
    rendered an empty page: get_catalogue and get_my_orders both 403'd and
    nothing errored visibly."""
    from app.routers import gear_requests as G
    for name in ("get_catalogue", "get_my_orders", "submit_gear_order"):
        assert "captain" in _gates(getattr(G, name)), name


def test_captain_cannot_approve_or_fulfil_gear():
    """Requesting gloves is not approving requisitions."""
    from app.routers import gear_requests as G
    for name in ("approve_item", "deny_item", "fulfill_item",
                 "get_all_orders", "get_pending_orders"):
        assert "captain" not in _gates(getattr(G, name)), name


# ── The backend the panel calls already admitted captains ────────────────────

def test_the_roster_endpoints_already_admit_captains():
    """This is why ADR-319 needed no server change."""
    from app.routers import roll_call as R
    for name in ("get_my_truck_roll_call", "submit_roll_call", "confirm_roll_call"):
        assert "captain" in _gates(getattr(R, name)), name


def test_the_dispatch_side_roll_call_views_stay_closed():
    """summary and override are the oversight views; this ADR does not open
    them."""
    from app.routers import roll_call as R
    for name in ("get_roll_call_summary", "override_roll_call"):
        assert "captain" not in _gates(getattr(R, name)), name


def test_a_captain_can_only_roll_call_their_own_truck():
    """The object-level guard matters more than the role gate here: a captain
    marking ANOTHER truck's crew NCNS is a real hazard."""
    from app.routers import roll_call as R
    src = inspect.getsource(R.submit_roll_call)
    assert "_get_caller_truck_assignment" in src
    assert "only submit roll call for crew members on your truck" in src


# ── The status is derived, not chosen ────────────────────────────────────────

def test_the_client_never_sends_a_status():
    """present/late/early are derived server-side from arrival time against the
    AP-established reference (ADR-198). RollCallCreate carries no status field,
    so the captain records WHETHER someone showed and the clock decides whether
    it was late."""
    from app.schemas.roll_call import RollCallCreate
    fields = set(RollCallCreate.model_fields)
    assert fields == {"employee_id", "date", "notes", "ncns"}
    assert "status" not in fields

    panel = PANEL.read_text()
    assert "ncns," in panel
    assert "status:" not in panel.split("apiClient.post")[1][:200], (
        "the panel must not send a status the server would ignore"
    )


def test_the_panel_posts_the_path_that_exists():
    """/roll-call, not /roll-call/ — a first draft had the trailing slash, which
    the router does not declare."""
    panel = PANEL.read_text()
    assert "apiClient.post('/roll-call'," in panel


# ── D2: a branch, not a gate ─────────────────────────────────────────────────

def test_the_driver_body_is_unchanged_and_the_captain_gets_their_own():
    src = FIELD_OPS.read_text()
    assert "const isCaptain = hasRole('captain');" in src
    # the driver's wizard still renders behind isDriver
    assert "isDriver && allSteps.length > 0" in src
    # and the captain's panel is a sibling, not a replacement
    assert "isCaptain && !isDriver" in src


# ── D0: workforce mode only ──────────────────────────────────────────────────

def test_the_roster_panel_is_workforce_only():
    """The route column comes from WorkforceRouteOut.assigned_to; full mode
    assigns stops from a manifest, which is a different shape and a separate
    design."""
    src = FIELD_OPS.read_text()
    m = re.search(r"\{isCaptain && [^}]*?\(", src)
    assert m and "!stationSort" in m.group(0), (
        "the captain panel must be gated off station_sort (ADR-319 D0)"
    )


def test_the_route_join_only_runs_in_workforce_mode():
    """/walker-routes (full mode) carries no assigned_to, so joining there would
    silently produce an empty map."""
    src = FIELD_OPS.read_text()
    i = src.index("routeByEmployee[r.assigned_to]")
    assert "if (!stationSort)" in src[max(0, i - 400):i]


# ── D4: unaccounted is visible ───────────────────────────────────────────────

def test_a_member_with_no_roll_call_row_renders_pending():
    """Dropping them would let a captain confirm a roster that quietly lost
    someone who never showed."""
    panel = PANEL.read_text()
    assert "rollCall[m.id] ?? 'pending'" in panel
    # and every crew member is rendered, not a filtered subset
    assert "crew.map(m =>" in panel
    assert ".filter(" not in panel.split("crew.map")[0][-300:]


# ── D3: read-only on this screen ─────────────────────────────────────────────

def test_the_panel_does_not_assign_or_close_routes():
    """A roster that could also reassign becomes a second write path to the same
    rows, and the casual one skips the checks."""
    panel = PANEL.read_text()
    for forbidden in ("/assign", "/close", "/depart", "package-count"):
        assert forbidden not in panel, f"the roster must not call {forbidden}"

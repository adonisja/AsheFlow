"""Amazon's numbers are a morning reference; ours are the record (ADR-299).

Two counts exist in workforce mode and they answer different questions:

    morning    sum(BTRRoute.package_count)    Amazon's claim, off the BTR sheet,
                                              the only count that exists before
                                              the truck moves
    close-out  sum(Route.flex_package_count)  ours — the real parcel count a
                                              captain reads off Amazon Flex at
                                              scan time (ADR-291 D11)

`Route.package_count` is used for NEITHER in workforce mode: it counts
captain-entered ADDRESSES, so a route holding one tote with three addresses
reports 3 while the tote physically carries fifty.
"""
import inspect

import pytest

from app.routers import workforce_routes as W
from app.routers.workforce_routes import TruckDayTotalsOut


def _totals_src():
    return inspect.getsource(W.truck_day_totals)


# ── D4: the close-out is ours, from flex_package_count ───────────────────────

def test_the_record_comes_from_flex_package_count():
    src = _totals_src()
    assert "Route.flex_package_count" in src
    assert "Route.package_count" not in src, (
        "package_count counts ADDRESSES in workforce mode (ADR-298)"
    )


def test_package_count_is_absent_from_the_payload_entirely():
    """A field that is not in the response cannot be rendered by accident."""
    assert "package_count" not in TruckDayTotalsOut.model_fields
    assert "packages_carried" in TruckDayTotalsOut.model_fields


def test_a_partial_scan_yields_null_not_a_partial_sum():
    """THE test a naive implementation fails.

    Three of five routes scanned: summing three silently reports a smaller
    truck than actually went out. NULL plus a count of what is unrecorded is the
    honest answer, and doubles as the nudge to finish scanning.
    """
    src = _totals_src()
    assert "if closed and not unscanned:" in src
    assert "routes_missing_flex_count" in src


def test_carried_is_optional_and_defaults_to_none():
    f = TruckDayTotalsOut.model_fields["packages_carried"]
    assert "Optional" in str(f.annotation)
    assert f.default is None, "0 would mean 'carried nothing', a different fact"


@pytest.mark.parametrize(
    "closed_counts,expect_carried,expect_missing",
    [
        ([40, 60],        100,  0),   # every closed route scanned
        ([40, None],      None, 1),   # one unscanned -> withheld, not 40
        ([None, None],    None, 2),   # none scanned
        ([],              None, 0),   # nothing closed yet -> not 0
        ([0, 0],          0,    0),   # genuinely carried nothing IS 0
    ],
)
def test_the_null_rule_across_scan_states(closed_counts, expect_carried, expect_missing):
    """Mirrors the endpoint's own arithmetic.

    The last row matters: 0 is a real measurement (a route that carried
    nothing) and must NOT be collapsed into the "unavailable" case.
    """
    closed = [type("R", (), {"flex_package_count": c})() for c in closed_counts]
    unscanned = [r for r in closed if r.flex_package_count is None]

    carried = None
    if closed and not unscanned:
        carried = sum(r.flex_package_count for r in closed)

    assert carried == expect_carried
    assert len(unscanned) == expect_missing


# ── D1/D2: the morning figure is Amazon's, and says so ───────────────────────

def test_dispatch_board_sources_the_morning_count_from_the_btr_sheet():
    """Before the truck moves, ours does not exist: no tote addresses entered,
    no sort run, nothing scanned. Amazon's BTR sheet is the only count there is.
    """
    try:
        from app.routers import dispatch as Dsp
    except ImportError:
        pytest.skip("proprietary dispatch router not available (CI skip)",
                    allow_module_level=False)
        return

    src = inspect.getsource(Dsp.get_daily_dispatch)
    assert "BTRRoute.package_count" in src
    assert "ap_source" in src


def test_the_morning_figure_carries_its_attribution():
    """D2 — attributed, never bare.

    Amazon partitions routes for a driver in a truck; we re-partition for a
    walker on foot. The two legitimately disagree, and two unlabelled numbers
    are worse than one wrong number: the reader cannot tell whose is whose and
    assumes a bug.
    """
    try:
        from app.routers import dispatch as Dsp
    except ImportError:
        pytest.skip("proprietary dispatch router not available (CI skip)",
                    allow_module_level=False)
        return

    src = inspect.getsource(Dsp.get_daily_dispatch)
    assert '"ap_source": ap_source' in src
    assert 'ap_source = "amazon_btr"' in src


def test_full_mode_still_uses_the_manifest_count():
    """Full mode is unchanged — package_count IS a parcel count there."""
    try:
        from app.routers import dispatch as Dsp
    except ImportError:
        pytest.skip("proprietary dispatch router not available (CI skip)",
                    allow_module_level=False)
        return

    src = inspect.getsource(Dsp.get_daily_dispatch)
    assert 'ap_source = "manifest"' in src
    assert "Route.package_count" in src


# ── D5: the two numbers are never reconciled ─────────────────────────────────

def test_the_close_out_does_not_read_the_btr_sheet():
    """A gap between Amazon's morning claim and our close-out is a real signal —
    packages that never made it onto a route, a wrong sheet, an unaddressed
    tote. Averaging or silently preferring one destroys it."""
    src = _totals_src()
    assert "BTRRoute" not in src
    assert "BTRSheet" not in src

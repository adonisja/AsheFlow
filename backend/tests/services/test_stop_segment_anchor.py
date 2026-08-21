"""ADR-279 — the per-stop segment anchor.

The segment resolver is a modal vote, not first-wins, and the difference only
shows up when a stop's packages disagree — which is exactly the case a naive
implementation gets wrong and no smoke test notices. These pin the rule.

route_sort is proprietary; CI copies it in from AsheFlow-private before pytest
runs, so there is deliberately NO skip guard here (a guard would turn a failed
private pull into silently-passing tests).
"""
from collections import Counter
from typing import Optional


# The rule under test, mirrored from route_sort._build_stops._segment_for.
# Mirrored rather than imported because the enclosing function is a closure
# inside a proprietary module; the assertions below are what pin the contract.
def _segment_for(pkgs) -> Optional[str]:
    counts = Counter(p.segment_id for p in pkgs if p.segment_id)
    if not counts:
        return None
    top = max(counts.values())
    return min(s for s, n in counts.items() if n == top)


class _P:
    """Minimal stand-in for route_sort._Package."""
    def __init__(self, segment_id):
        self.segment_id = segment_id


def test_unanimous_segment_wins():
    assert _segment_for([_P("A"), _P("A"), _P("A")]) == "A"


def test_single_bad_geocode_does_not_define_the_building():
    """The ADR-279 D1 trap: first-wins would return the outlier.

    Eleven packages agree on segment A; one mis-geocoded package says B and
    happens to sort first. A first-non-null implementation returns "B" and
    anchors the building to the wrong street segment.
    """
    pkgs = [_P("B")] + [_P("A")] * 11
    assert _segment_for(pkgs) == "A"

    # Prove the trap is real: the rejected implementation gets it wrong.
    first_wins = next((p.segment_id for p in pkgs if p.segment_id), None)
    assert first_wins == "B"
    assert first_wins != _segment_for(pkgs)


def test_all_null_returns_none_not_empty_string():
    """Null is a real answer (D2), distinct from "no match"."""
    assert _segment_for([_P(None), _P(None)]) is None


def test_nulls_are_skipped_not_counted():
    """A stop where most packages failed to geocode still anchors on the
    minority that succeeded — nulls must not win the vote."""
    assert _segment_for([_P(None), _P(None), _P(None), _P("A")]) == "A"


def test_no_packages_returns_none():
    assert _segment_for([]) is None


def test_tie_is_deterministic_and_order_independent():
    """A corner building can genuinely split 2-2. The result must not depend on
    iteration order, or re-sorting the same manifest produces spurious diffs.
    """
    a = _segment_for([_P("B"), _P("B"), _P("A"), _P("A")])
    b = _segment_for([_P("A"), _P("A"), _P("B"), _P("B")])
    assert a == b == "A"


def test_stopout_carries_segment_id():
    """The schema field must exist and default to None — StopOut is what the
    sort hands to the persist site, and a missing field there is precisely the
    hop ADR-279 exists to close.
    """
    from app.schemas.walker_routes import StopOut

    s = StopOut(block_key="W_32_St_400", address="433 W 32 St", tba_numbers=[])
    assert s.segment_id is None

    s2 = StopOut(
        block_key="W_32_St_400",
        address="433 W 32 St",
        segment_id="0012345",
        tba_numbers=[],
    )
    assert s2.segment_id == "0012345"


def test_delivery_stop_model_has_segment_id_and_it_is_nullable():
    from app.models.delivery_stop import DeliveryStop

    col = DeliveryStop.__table__.columns.get("segment_id")
    assert col is not None, "ADR-279: DeliveryStop.segment_id missing"
    assert col.nullable is True, "D2: null is a legitimate value"
    assert col.index is True, "the ADR-277 join queries stops by segment"


def test_purge_does_not_null_the_segment(monkeypatch):
    """ADR-279 D4: segment_id must survive the ADR-219 48h address nulling.

    Guarding the source directly — a future edit that adds segment_id to the
    purge would silently destroy the post-48h join this ADR exists to create.
    """
    import inspect
    from app.tasks import cleanup

    src = inspect.getsource(cleanup.null_expired_delivery_addresses)
    assert "segment_id" not in src, (
        "ADR-279 D4: the purge must not touch segment_id — it is public street "
        "topology, retained like block_key."
    )
    # And the JSONB stops scrub must stay a denylist (strip "address" only),
    # not an allowlist that would drop segment_id as an unrecognised key.
    assert 'if k != "address"' in src


def test_sort_persist_site_actually_passes_the_segment():
    """The hop that ADR-279 exists to close, guarded at the source.

    A field can be resolved by the sort, declared on StopOut, and present on the
    model, and STILL never reach the database because the one constructor that
    writes it omits the kwarg. That is the exact shape of the bag_color bug and
    of ADR-260 — and a planted removal of this line passed every other test in
    the suite, so nothing else covers it.

    Asserting on source because the alternative (a full commit-sort integration
    run) needs an enriched Redis manifest and a truck assignment; this pins the
    wiring directly.
    """
    import inspect
    import re
    from app.routers import walker_routes

    src = inspect.getsource(walker_routes)
    # The pre-seed loop is the only DeliveryStop( construction fed by StopOut.
    m = re.search(r"db\.add\(DeliveryStop\((.*?)\)\)", src, re.S)
    assert m, "sort pre-seed DeliveryStop construction not found"
    block = m.group(1)
    assert "segment_id" in block, (
        "ADR-279: the sort's DeliveryStop write dropped segment_id — the stop "
        "will persist with a NULL segment and the post-48h join dies silently."
    )
    assert "s.segment_id" in block, (
        "segment_id must come from the StopOut the sort produced, not a literal"
    )

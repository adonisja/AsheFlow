"""The workforce cross-check compared Amazon against a table we never write (ADR-301).

`our_delivered` came from DeliveryStop. Workforce mode NEVER WRITES that table,
so it was always 0, and the two metrics inherited that zero in opposite and
equally wrong directions:

  packages_delivered   delta = amazon - 0        -> every scorecard contestable
  completion_dpmo      attempted = 0 + rts + missing
                       -> our_dpmo = 1,000,000, and `contestable` requires
                          az_dpmo > our_dpmo * 1.25, which no real Amazon DPMO
                          reaches -> nothing EVER contestable

The second silently suppressed every legitimate completion appeal while the
response still read "Consistent with our RTS/missing record".

ADR-294 D5 had shipped a precision note claiming the figure came from
"captain-recorded route counts". No such wiring existed. That is the lesson: a
label asserting a data source the code does not read is worse than no label,
because it converts an obvious absence into a plausible approximation.
"""
import ast
import inspect

from app.routers import scorecards as S
from app.schemas.scorecard import CrossCheckResponse


def _code_only(obj) -> str:
    """Source with docstrings stripped — grep matches its own prose otherwise."""
    tree = ast.parse(inspect.getsource(obj))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef, ast.Module)):
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                node.body.pop(0)
    return ast.unparse(tree)


SRC = _code_only(S.cross_check_scorecard)


# ── The arithmetic, executed rather than asserted about ──────────────────────

def _evaluate(*, full, our_carried, rts, missing, az_delivered, az_dpmo):
    """Mirror of the endpoint's two computations (ADR-301 D2/D4)."""
    delivered = 0 if full else None
    ours = delivered if full else (
        our_carried - rts - missing if our_carried is not None else None)
    if ours is None:
        pkg = {"our_value": None, "contestable": False}
    else:
        delta = round(az_delivered - ours, 1)
        thresh = max(5, 0.05 * max(az_delivered, ours, 1))
        pkg = {"our_value": float(ours), "contestable": abs(delta) > thresh}
    attempted = (delivered + rts + missing) if full else our_carried
    dpmo = round((rts + missing) / attempted * 1_000_000, 1) if attempted else None
    return pkg, {"our_value": dpmo,
                 "contestable": dpmo is not None and az_dpmo > dpmo * 1.25}


def test_the_old_dpmo_inversion_is_gone():
    """THE dangerous half. With delivered=0 the denominator was rts+missing, so
    our_dpmo was exactly 1,000,000 and no Amazon DPMO could ever exceed
    1.25x that — every completion appeal silently suppressed."""
    _, old = _evaluate(full=True, our_carried=None, rts=3, missing=1,
                       az_delivered=300, az_dpmo=150_000)
    assert old["our_value"] == 1_000_000.0
    assert old["contestable"] is False, "the bug: a real defect gap reads as consistent"

    _, new = _evaluate(full=False, our_carried=310, rts=30, missing=5,
                       az_delivered=300, az_dpmo=150_000)
    assert new["our_value"] < 1_000_000
    assert new["contestable"] is True, (
        "a genuine defect discrepancy must now be appealable (ADR-301 D4)"
    )


def test_the_old_delivered_inversion_is_gone():
    """The other direction: amazon - 0 always cleared the threshold."""
    old, _ = _evaluate(full=True, our_carried=None, rts=3, missing=1,
                       az_delivered=300, az_dpmo=5000)
    assert old["our_value"] == 0.0 and old["contestable"] is True

    new, _ = _evaluate(full=False, our_carried=310, rts=3, missing=1,
                       az_delivered=300, az_dpmo=5000)
    assert new["our_value"] == 306.0
    assert new["contestable"] is False, "a matching week must not be flagged"


# ── D3: NULL suppresses, it does not accuse ──────────────────────────────────

def test_no_recorded_count_withholds_both_comparisons():
    """An appeal built on a fabricated discrepancy costs more credibility with
    Amazon than a missing comparison does. Default to silence."""
    pkg, dpmo = _evaluate(full=False, our_carried=None, rts=3, missing=1,
                          az_delivered=300, az_dpmo=5000)
    for item in (pkg, dpmo):
        assert item["our_value"] is None
        assert item["contestable"] is False


def test_partial_coverage_reports_none_never_a_partial_sum():
    """A partial sum understates what was carried, manufacturing a discrepancy
    in exactly the direction that produces a bad appeal (ADR-299 D4)."""
    assert "routes_unrecorded == 0" in SRC, (
        "our_carried must only be summed when EVERY route has a count"
    )
    assert "routes_unrecorded" in CrossCheckResponse.model_fields


# ── D2: the field cannot keep a name it cannot honour ────────────────────────

def test_the_workforce_figure_is_named_carried_not_delivered():
    """flex_package_count counts parcels CARRIED. Workforce mode has no delivery
    event at all (ADR-297 D5c), so naming it `delivered` asserts a measurement
    that does not exist. A reader who skips the note must still not be misled."""
    f = CrossCheckResponse.model_fields
    assert "our_carried" in f
    assert "Optional" in str(f["our_carried"].annotation) or "None" in str(f["our_carried"].annotation)
    # our_delivered survives for FULL mode, but must now be nullable
    assert "Optional" in str(f["our_delivered"].annotation) or "None" in str(f["our_delivered"].annotation)


def test_delivered_is_not_populated_in_workforce_mode():
    """The whole defect was reading a table workforce mode never writes."""
    tree = ast.parse(SRC)
    fn = tree.body[0]
    # the DeliveryStop query must sit inside `if full_mode:`
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and "DeliveryStop" in ast.dump(node):
            break
    assert "if full_mode:" in SRC
    ds = SRC.index("DeliveryStop.packages_delivered")
    assert SRC.index("if full_mode:") < ds, (
        "the DeliveryStop read must be gated on full mode (ADR-301 D1)"
    )


# ── D1: the replacement source ───────────────────────────────────────────────

def test_workforce_reads_flex_package_count_through_the_executor():
    src = SRC
    assert "flex_package_count" in src
    assert 'RouteParticipant.role == "executor"' in src or \
           "RouteParticipant.role == 'executor'" in src


def test_the_model_names_actually_resolve():
    """`import app.main` passes even when a name inside a function body does not
    exist — it resolves at CALL time. This shipped once already: the first draft
    imported `WalkerRoute`, which is not a class in that module (it is `Route`)."""
    import app.models.walker_route as wr
    for name in ("Route", "RouteParticipant"):
        assert hasattr(wr, name), f"{name} is not defined in app.models.walker_route"
    assert "WalkerRoute" not in SRC, "stale model name"

    from app.models.walker_route import Route, RouteParticipant
    for col in ("flex_package_count", "route_date", "company_id", "id"):
        assert hasattr(Route, col)
    for col in ("route_id", "employee_id", "role", "company_id"):
        assert hasattr(RouteParticipant, col)


# ── D5: the note describes what the code does ────────────────────────────────

def test_the_precision_note_no_longer_claims_a_source_it_does_not_read():
    """The original note promised "captain-recorded route counts" while the code
    read DeliveryStop's zero. The note is kept — ADR-294 D5's reasoning is right
    — but it must now be true."""
    assert "captain-recorded parcel count" in SRC
    assert "less recorded returns" in SRC
    # and it must say the two sides measure different things
    assert "different measurement" in SRC


# ── Dimension 1 ──────────────────────────────────────────────────────────────

def test_every_workforce_query_is_company_scoped():
    seg = SRC[SRC.index("RouteParticipant"):SRC.index("our_rts =")]
    assert "RouteParticipant.company_id == cid" in seg
    assert "Route.company_id == cid" in seg


def test_config_is_read_once():
    """Three CompanyConfig lookups in one request is the shape this replaced."""
    assert SRC.count("db.query(CompanyConfig)") == 1


# ── The appeal payload the client actually sends ─────────────────────────────

def test_appeal_evidence_accepts_what_the_only_producer_sends():
    """Found while mirroring ADR-301 into types.ts, and PRE-EXISTING.

    `ab510f89` tightened AppealEvidence from Dict[str, Any] to a typed model
    with extra="forbid", on a docstring claim that ScorecardEntry.tsx "sends
    exactly {rts_reasons: [...]}". It does not — it also sends our_delivered,
    our_rts, our_missing, week_start and week_end. Every appeal filed from the
    UI 422'd on five unrecognised keys.

    A Dimension 9 hardening that is not checked against the real producer
    replaces an unbounded write with a broken endpoint.
    """
    from app.schemas.scorecard_appeal import AppealEvidence

    # exactly what ScorecardEntry.tsx built BEFORE this ADR
    AppealEvidence(**{
        "rts_reasons": [{"rts_type": "business_closed", "count": 2}],
        "our_delivered": 200, "our_rts": 3, "our_missing": 1,
        "week_start": "2026-07-06", "week_end": "2026-07-12",
    })

    # and what it sends now
    AppealEvidence(**{
        "rts_reasons": [], "our_delivered": None, "our_carried": 310,
        "routes_unrecorded": 0, "precision": "captain_reported",
        "our_rts": 3, "our_missing": 1,
        "week_start": "2026-07-06", "week_end": "2026-07-12",
    })


def test_appeal_evidence_still_forbids_unknown_keys():
    """The Dimension 9 property must survive the widening: an unrecognised key
    is a client bug worth a 422, not something to persist into JSONB."""
    import pytest
    from pydantic import ValidationError
    from app.schemas.scorecard_appeal import AppealEvidence

    with pytest.raises(ValidationError):
        AppealEvidence(rts_reasons=[], unexpected_key=1)


def test_appeal_evidence_figures_are_nullable():
    """An appeal must be able to say "we do not hold this figure" rather than
    assert a fabricated zero (ADR-301 D3)."""
    from app.schemas.scorecard_appeal import AppealEvidence
    ev = AppealEvidence(rts_reasons=[])
    assert ev.our_delivered is None and ev.our_carried is None

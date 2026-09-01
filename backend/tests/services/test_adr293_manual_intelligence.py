"""Sparse collection means decay must stop, not slow (ADR-293).

The operator calls walkers "the walking banks" — their accumulated knowledge of
which buildings are slow, which have a doorman, which close early is the asset
that makes routing intelligent.

In full mode that knowledge accrues automatically: a walker completes a stop and
ADR-277 surfaces the building for assessment in context. Workforce mode has no
stops, so collection is entirely manual — and the nightly decay job kept running
at a rate calibrated against daily delivery evidence that no longer arrives.
Every score would fade to zero unopposed. The building does not become less
troublesome; only our record of it does.
"""
import ast
import inspect

from app.models.building_profile import BuildingProfile
from app.services import building_troublesome as BT
from app.services.company_config import full_mode_company_ids, is_full_mode


def _code_only(obj) -> str:
    tree = ast.parse(inspect.getsource(obj))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef, ast.Module)):
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                node.body.pop(0)
    return ast.unparse(tree)


# ── D1: decay STOPS in workforce mode ────────────────────────────────────────

def test_decay_is_scoped_to_full_mode_companies():
    """Not slowed, not re-tuned — stopped. A rate calibrated against evidence
    that stopped arriving has no correct value."""
    src = _code_only(BT.decay_all)
    assert "full_mode_company_ids" in src
    assert "company_id.in_(full_mode)" in src


def test_decay_does_nothing_when_no_company_is_full_mode():
    """The early return matters: without it the query would decay every row in
    the table when the filter set is empty."""
    src = _code_only(BT.decay_all)
    i = src.index("full_mode_company_ids")
    assert "if not full_mode:" in src[i:]
    assert "return 0" in src[i:]


def test_freezing_is_the_chosen_state_not_an_oversight():
    """Scores hold at their last delivery-informed value, and decay resumes if
    the tenant returns to full mode. Recorded in the source so a later reader
    does not 'fix' it by re-enabling global decay."""
    doc = inspect.getdoc(BT.decay_all) or ""
    assert "ADR-293" in doc
    assert "workforce" in doc.lower()


# ── D3: provenance ───────────────────────────────────────────────────────────

def test_collection_source_records_how_a_profile_was_collected():
    cols = {c.name for c in BuildingProfile.__table__.columns}
    assert "collection_source" in cols
    col = BuildingProfile.__table__.columns["collection_source"]
    assert col.nullable is False
    assert "route" in str(col.server_default.arg), (
        "existing rows were all route-collected; defaulting to 'manual' would "
        "misdescribe the entire history"
    )


def test_provenance_is_derived_server_side_never_client_supplied():
    """A caller could otherwise mislabel a manual entry as route-collected and
    launder a remembered guess into the sample that decay and analysis trust."""
    from app.routers.building_profiles import submit_building_profile
    src = _code_only(submit_building_profile)
    assert "collection_source" in src
    assert "body.collection_source" not in src
    assert "is_full_mode(db, caller.company_id)" in src


def test_the_request_schema_rejects_a_smuggled_provenance():
    """It was silently IGNORED before — the value never reached the model, but
    the caller got no signal it had been dropped.

    Verified against the real producers before tightening (the ADR-301 lesson):
    BuildingProfiles.tsx and MyRoute.tsx both send a typed BuildingProfileCreate
    carrying only normalised_address, block_key, building_type and raw_note.
    """
    import pytest
    from pydantic import ValidationError
    from app.schemas.location_profile import BuildingProfileCreate

    assert BuildingProfileCreate.model_config.get("extra") == "forbid"
    # both real producer payloads must still work
    BuildingProfileCreate(normalised_address="1 TEST ST",
                          building_type="walkup", raw_note="x")
    BuildingProfileCreate(normalised_address="1 TEST ST", block_key="Test_St_0",
                          building_type="walkup")
    with pytest.raises(ValidationError):
        BuildingProfileCreate(normalised_address="1 TEST ST",
                              building_type="walkup", collection_source="route")


def test_is_full_mode_answers_for_one_company():
    """The request-path counterpart to full_mode_company_ids, which exists for
    cross-tenant background tasks."""
    src = _code_only(is_full_mode)
    assert "CompanyConfig.company_id == company_id" in src
    assert "MODE_FULL" in src


# ── D2: manual entry needs no route ──────────────────────────────────────────

def test_profile_creation_does_not_require_a_route_or_stop():
    """Workforce mode has neither. If creation depended on one, manual
    collection would be impossible in the mode that needs it."""
    from app.routers.building_profiles import submit_building_profile
    src = _code_only(submit_building_profile)
    for coupled in ("DeliveryStop", "route_id", "WalkerRoute"):
        assert coupled not in src


# ── D4: the promotion bar is NOT lowered ─────────────────────────────────────

def test_the_library_promotion_gate_is_unchanged():
    """Do not lower the bar because collection is sparse — the library is
    cross-company, and a lower bar propagates one company's guess to everyone."""
    from app.routers import building_profile_library as BPL
    src = inspect.getsource(BPL)
    assert 'building_type_status == "locked"' in src
    assert "collection_source" not in src, (
        "promotion must not treat a manual entry differently — same bar (D4)"
    )

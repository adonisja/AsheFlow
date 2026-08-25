"""ADR-292 — manual RTS / missing / damaged entry.

The central claim is D1/D2: a manually entered TBA is a REAL Amazon tracking
number, so nothing here synthesises one. That is the OPPOSITE call from
ADR-291's route adapter, which does mint ids — and the difference is the point.
A captain-entered address has no Amazon identity to preserve; a package in a
walker's hand has its tracking number printed on it, and destroying that would
make a scorecard appeal unanswerable.
"""
import ast
import inspect
import uuid
from datetime import date

import pytest

from app.models.rts import (
    PACKAGE_SOURCES, DamagedPackage, MissingPackage, RTSPackage, RTS_TYPES,
    is_reattemptable,
)
from app.routers import manual_returns as M
from app.routers.manual_returns import DamagedRecordIn, MissingRecordIn, RTSRecordIn


def _code_only(obj) -> str:
    """Source with docstrings and comments stripped.

    Every prose-matching assertion in this file needs it: the module and function
    docstrings mention `WF-` and `route_id` precisely to explain why those are
    NOT used, so a raw substring check fails on its own explanation. Two earlier
    versions of these tests did exactly that and reported violations in correct
    code — a static check that reads too wide is a false-alarm generator, and
    false alarms are how real findings get ignored.
    """
    src = inspect.getsource(obj)
    tree = ast.parse(src) if not src.startswith(" ") else ast.parse(
        "\n".join(l[4:] if l.startswith("    ") else l for l in src.splitlines())
    )
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
                             ast.Module)) and ast.get_docstring(node):
            node.body = node.body[1:]          # drop the docstring statement
    return ast.unparse(tree)                    # comments are gone by construction


# ── D1 / D2: the identifier ───────────────────────────────────────────────────

def test_nothing_synthesises_a_tba():
    """D2. A generated id like WF-2026-08-24-001 is unusable outside AsheFlow:
    Amazon can only act on a real TBA. Contrast ADR-291's adapter, which mints
    ids precisely because a captain-entered ADDRESS has no Amazon identity."""
    code = _code_only(M)
    for minted in ("WF-", "synthetic_tba", "uuid4().hex"):
        assert minted not in code, f"manual returns should not mint {minted}"


def test_tba_is_required_on_every_record_type():
    """D1: the TBA exists — it is on the package. Accepting a record without one
    would lose the only identifier Amazon can act on."""
    for model in (RTSRecordIn, MissingRecordIn, DamagedRecordIn):
        assert "tba_number" in model.model_fields
        assert model.model_fields["tba_number"].is_required()


def test_tba_is_not_format_locked():
    """A captain correcting a scanner misread must not be blocked by a regex
    while holding the physical label. Bounded to the column width, not shaped."""
    ok = RTSRecordIn(route_id=uuid.uuid4(), tba_number="TBA303012345678",
                     rts_type="no_access", rts_explanation="gate locked")
    assert ok.tba_number == "TBA303012345678"
    odd = RTSRecordIn(route_id=uuid.uuid4(), tba_number="1Z999AA10123456784",
                      rts_type="no_access", rts_explanation="gate locked")
    assert odd.tba_number.startswith("1Z")


# ── D3: provenance ────────────────────────────────────────────────────────────

def test_all_three_models_carry_source():
    for model in (RTSPackage, MissingPackage, DamagedPackage):
        assert "source" in model.__table__.c, f"{model.__name__} has no source"


def test_source_defaults_to_manifest_not_null():
    """Every pre-existing row came from a manifest, so that is the truth for
    them rather than a placeholder. A nullable column could not distinguish
    'unknown provenance' from 'never set' — the ADR-283 ambiguity."""
    for model in (RTSPackage, MissingPackage, DamagedPackage):
        col = model.__table__.c["source"]
        assert not col.nullable
        assert col.server_default is not None


def test_manual_records_are_written_as_manual():
    for fn in (M.record_rts, M.record_missing, M.record_damaged):
        assert 'source="manual"' in inspect.getsource(fn), f"{fn.__name__}"


def test_source_values_are_the_two_real_ones():
    assert PACKAGE_SOURCES == ("manifest", "manual")


# ── D6: the type enum is unchanged ────────────────────────────────────────────

def test_rts_types_match_the_model_exactly():
    """D6: every value is an observation about a delivery attempt, not a fact
    derived from the manifest — so workforce mode uses the same six."""
    literal = RTSRecordIn.model_fields["rts_type"].annotation
    accepted = set(getattr(literal, "__args__", ()))
    assert accepted == set(RTS_TYPES)


def test_is_reattemptable_is_server_derived():
    """A client that could set it would decide whether a package goes back out
    today. That is a rule, not an input."""
    assert "is_reattemptable" not in RTSRecordIn.model_fields
    src = inspect.getsource(M.record_rts)
    assert "is_reattemptable=is_reattemptable(payload.rts_type)" in src


def test_reattemptable_derivation_is_the_shared_one():
    assert is_reattemptable("no_access") is True
    assert is_reattemptable("customer_cancelled_order") is False


# ── D4: the scanner ───────────────────────────────────────────────────────────

def test_scan_label_writes_nothing():
    """An OCR read is a suggestion. Giving the endpoint no write path is what
    forces the confirmation, the same mechanism as ADR-290's preview."""
    src = inspect.getsource(M.scan_label)
    for writer in ("db.add", "db.commit", "db.flush", "db.delete"):
        assert writer not in src, f"scan_label calls {writer}"


def test_scan_label_reuses_the_existing_ingestor():
    """D4: label_ingestor (ADR-246) already extracts a TBA with confidence and
    documents why the read must be confirmed. A second OCR path would drift."""
    assert "from app.services.label_ingestor import LabelIngestor" in \
        inspect.getsource(M.scan_label)


def test_scan_label_returns_no_address():
    """label_ingestor also parses an address line. A manual return does not need
    one, and returning a customer address nobody asked for puts it in a response
    and its logs for nothing (dim 7)."""
    src = inspect.getsource(M.scan_label)
    assert "address_line" not in src
    assert "read.tba" in src


def test_scan_label_does_not_demand_manual_entry_for_a_missing_address():
    """label_ingestor's own needs_manual_entry is True when EITHER field is
    missing. Here only the TBA matters, so reusing that flag verbatim would send
    a captain to type a tracking number that scanned perfectly."""
    src = inspect.getsource(M.scan_label)
    assert "needs_manual_entry=read.tba is None" in src


# ── duplicates ────────────────────────────────────────────────────────────────

def test_duplicate_scans_are_rejected():
    """A captain working through a returned tote can scan the same label twice.
    Silently doubling the day's RTS count lands in the scorecard cross-check as
    a real discrepancy."""
    for fn in (M.record_rts, M.record_missing, M.record_damaged):
        src = inspect.getsource(fn)
        assert "_reject_duplicate" in src or "_reject_damaged_duplicate" in src


def test_damaged_duplicate_check_does_not_use_route_id():
    """DamagedPackage is keyed by route_date + truck_assignment_id — station
    damage happens before a package is ever on a route. An earlier draft passed
    route_id to the shared helper, which would have raised at runtime."""
    assert "route_id" not in _code_only(M._reject_damaged_duplicate)
    assert "route_id" not in DamagedPackage.__table__.c


# ── gates and audit ───────────────────────────────────────────────────────────

def test_a_walker_cannot_record_their_own_non_delivery():
    """Dim 2. Every record here is an exception to a delivery that did not
    happen; self-reporting them unsupervised is how a bad day becomes an
    invisible one."""
    for fn in (M.record_rts, M.record_missing, M.record_damaged, M.scan_label):
        gates = [
            getattr(p.default.dependency, "allowed_roles", None)
            for p in inspect.signature(fn).parameters.values()
            if getattr(p.default, "dependency", None) is not None
        ]
        roles = next((g for g in gates if g), None)
        assert roles is not None, f"{fn.__name__} has no role gate"
        assert "walker" not in roles, f"{fn.__name__} lets a walker self-report"
        assert "captain" in roles


def test_every_write_is_audited():
    for fn in (M.record_rts, M.record_missing, M.record_damaged):
        assert "write_audit" in inspect.getsource(fn), f"{fn.__name__} unaudited"


def test_free_text_is_scrubbed():
    """Dim 7: rts_explanation and damage_notes are captain-written free text and
    can name a resident or a customer."""
    for fn in (M.record_rts, M.record_missing, M.record_damaged):
        assert "scrub_note" in inspect.getsource(fn), f"{fn.__name__}"


def test_free_text_is_bounded():
    with pytest.raises(Exception):
        RTSRecordIn(route_id=uuid.uuid4(), tba_number="TBA1234567890",
                    rts_type="no_access", rts_explanation="x" * 1001)


def test_payloads_reject_unknown_keys():
    with pytest.raises(Exception):
        RTSRecordIn(route_id=uuid.uuid4(), tba_number="TBA1234567890",
                    rts_type="no_access", rts_explanation="ok", bogus=1)


def test_parse_errors_do_not_leak_exception_text():
    """Dim 6: a Textract or boto failure must not reach the client."""
    src = inspect.getsource(M.scan_label)
    assert "str(e)" not in src and "str(exc)" not in src
    assert "exc_info=True" in src, "the detail should be logged, not returned"


# ── mode gating ───────────────────────────────────────────────────────────────

def test_router_is_gated_to_workforce_mode():
    """rts.py stays gated to full mode; this is its small mirror, not an
    un-gating of 394 package references' worth of manifest coupling."""
    main_src = (
        __import__("pathlib").Path(M.__file__).parent.parent / "main.py"
    ).read_text()
    line = next(l for l in main_src.splitlines() if "manual_returns.router" in l)
    assert "_workforce_mode" in line, f"not workforce-gated: {line.strip()}"

    rts_line = next(l for l in main_src.splitlines()
                    if "rts.router" in l and "manual" not in l)
    assert "_full_mode" in rts_line, "rts.py must stay full-mode gated"

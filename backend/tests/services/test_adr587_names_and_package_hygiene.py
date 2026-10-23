"""ADR-587 — no customer name or package id leaves its purpose.

D1  a label read returns the TBA and canonical address candidates, never every line;
D2  no log call carries a TBA, an address or a recipient;
D3  sort_packages_dropped (push + Discord) carries a count;
D4  truck_zones.tote_roster expires and erases with its row;
D5  a tote door's coordinates and cross streets go with its address.
"""
import ast
import asyncio
import pathlib
import re
import uuid
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.models.tote_address import ToteAddress
from app.models.truck_zone import TruckZone
from app.services import pi_erasure
from app.tasks import cleanup
from tests.conftest import SEED_COMPANY_ID
# Real-row fixtures and helpers from the ADR-493 suite (SQLite ARRAY shim, tables).
from tests.services.test_adr493_erasure import _erase, _fresh, _tables, array_as_json  # noqa: F401

BACKEND = pathlib.Path(__file__).resolve().parents[2]
TBA = "TBA123456789000"
LABEL = ["SHIP TO:", "JANE SAMPLE", "350 5th Ave Apt 12B", "NEW YORK NY 10118",
         TBA, "Return: ACME CO", "999 RETURN RD"]


# ── D2: logs ────────────────────────────────────────────────────────────────

_PI_NAME = re.compile(
    r"(^|_)(tba|tbas|address|addresses|addr|recipient|lat|lng)($|_)", re.I)
_LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical"}

# (file, enclosing function, name) logged deliberately, each with its reason.
LOG_EXEMPT = {
    # A street NAME with no house number is not an address: it is the public
    # street, shared by every door on it.
    ("app/services/segment_map.py", "on_street"): "a street name, no house number",
    ("app/tasks/enrich_manifest.py", "cross_street_one"): "a street name, no house number",
    ("app/tasks/enrich_manifest.py", "cross_street_two"): "a street name, no house number",
}


def _pi_in(node) -> set[str]:
    """Names and dict keys inside a log argument that look like PI, skipping
    anything under len(...) — a count is not the value."""
    out: set[str] = set()

    def walk(n):
        if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "len":
            return
        if isinstance(n, ast.Name) and _PI_NAME.search(n.id):
            out.add(n.id)
        elif isinstance(n, ast.Attribute) and _PI_NAME.search(n.attr):
            out.add(n.attr)
        elif isinstance(n, ast.Dict):
            for k, v in zip(n.keys, n.values):
                if isinstance(k, ast.Constant) and isinstance(k.value, str) and _PI_NAME.search(k.value) \
                        and not (isinstance(v, ast.Call) and getattr(v.func, "id", None) == "len"):
                    out.add(k.value)
        for c in ast.iter_child_nodes(n):
            walk(c)
    walk(node)
    return out


def _log_leaks():
    leaks = []
    for p in sorted((BACKEND / "app").rglob("*.py")):
        rel = str(p.relative_to(BACKEND))
        for n in ast.walk(ast.parse(p.read_text())):
            if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr in _LOG_METHODS and isinstance(n.func.value, ast.Name)
                    and n.func.value.id in {"logger", "log", "_log", "logging"}):
                continue
            for arg in list(n.args[1:]) + [k.value for k in n.keywords]:
                for name in _pi_in(arg):
                    if (rel, name) not in LOG_EXEMPT:
                        leaks.append(f"{rel}:{n.lineno} {name}")
    return leaks


def test_no_log_call_carries_a_tba_or_an_address():
    leaks = _log_leaks()
    assert not leaks, (
        "These log calls carry a TBA, an address or a recipient (ADR-587 D2). Log a count "
        "or an id instead, or exempt a non-PI value in LOG_EXEMPT with its reason:\n  "
        + "\n  ".join(leaks))


def test_the_log_scan_sees_a_leak():
    """Vacuity guard: the walker must flag the shapes the five fixed calls had."""
    src = 'logger.warning("x", extra={"tba": tba, "n": len(tbas)})\nlogger.info("y %s", address)'
    found = set()
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Call) and getattr(n.func, "attr", None) in _LOG_METHODS:
            for arg in list(n.args[1:]) + [k.value for k in n.keywords]:
                found |= _pi_in(arg)
    assert found == {"tba", "address"}, found


# ── D1: label reads ─────────────────────────────────────────────────────────

def _ocr(lines):
    from app.services.label_ingestor import parse_label_lines
    return parse_label_lines([(t, 95.0) for t in lines])


class _Upload:
    filename, content_type = "label.jpg", "image/jpeg"

    async def read(self):
        return b"jpeg-bytes"


@pytest.fixture
def stub_ocr(monkeypatch):
    from app.services import label_ingestor

    class Stub:
        def __init__(self, payload):
            pass

        def read(self):
            return _ocr(LABEL)
    monkeypatch.setattr(label_ingestor, "LabelIngestor", Stub)


def _no_name(payload: dict):
    flat = repr(payload).upper()
    assert "JANE" not in flat and "SAMPLE" not in flat and "ACME" not in flat, payload
    assert "12B" not in flat, "a unit never leaves the parser (ADR-582 D4)"


def test_read_label_returns_the_tba_and_the_door_only(stub_ocr):
    from app.routers import package_intake as pi
    out = asyncio.run(pi.read_label(file=_Upload(), caller=None, _={}))
    body = out.model_dump()
    assert "lines" not in body
    assert body["tba"] == TBA and body["address_line"] == "350 5 AVE"
    _no_name(body)


def test_scan_label_returns_the_tba_only(stub_ocr):
    from app.routers import manual_returns as M
    out = asyncio.run(M.scan_label(file=_Upload(), caller=SimpleNamespace(company_id=uuid.uuid4()),
                                   _={}, db=None))
    body = out.model_dump()
    assert set(body) == {"tba", "confidence", "warnings", "needs_manual_entry"}
    assert body["tba"] == TBA and body["needs_manual_entry"] is False
    _no_name(body)


def test_no_label_schema_has_an_all_lines_field():
    from app.routers.manual_returns import LabelReadOut
    from app.schemas.package_intake import LabelReadResponse
    for model in (LabelReadOut, LabelReadResponse):
        assert "lines" not in model.model_fields, model.__name__


# ── D3: the dropped-packages notification ───────────────────────────────────

def test_the_dropped_packages_message_carries_no_tba():
    """walker_routes.commit_sort's fan_out(type="sort_packages_dropped"): the
    message may use len(dropped_tbas), never the list or any slice of it."""
    tree = ast.parse((BACKEND / "app/routers/walker_routes.py").read_text())
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and getattr(n.func, "id", None) == "fan_out"
             and any(k.arg == "type" and getattr(k.value, "value", None) == "sort_packages_dropped"
                     for k in n.keywords)]
    assert len(calls) == 1, "the scan must find the call it guards"
    message = next(k.value for k in calls[0].keywords if k.arg == "message")
    assert not _pi_in(message), _pi_in(message)
    for n in ast.walk(message):
        assert not (isinstance(n, ast.Name) and n.id in {"sample", "tba_lines"})


# ── D4: the tote roster ─────────────────────────────────────────────────────

def _zone(db, days_ago=0):
    z = TruckZone(id=uuid.uuid4(), company_id=SEED_COMPANY_ID, truck_id=uuid.uuid4(),
                  truck_polygon={}, zone_label="Z", created_by_name="x",
                  zone_date=date.today() - timedelta(days=days_ago),
                  package_tbas=[TBA, "TBAKEEP00000001"],
                  tote_roster=[
                      {"bag_id": "B1", "tba_numbers": [TBA, "TBAKEEP00000001"], "package_count": 2},
                      {"bag_id": f"(loose) {TBA}", "tba_numbers": [TBA], "package_count": 1},
                  ])
    db.add(z)
    db.commit()
    return z


def test_old_rosters_expire_and_counts_hold(db):
    old, new = _zone(db, days_ago=100), _zone(db, days_ago=5)
    with patch.object(cleanup, "SessionLocal", return_value=db), patch.object(db, "close"), \
         patch.multiple(cleanup.settings, tba_retention_days=90, delivery_address_retention_hours=48):
        out = cleanup.expire_package_ids_and_audit_pi()
    o = _fresh(db, old).tote_roster
    assert [len(e["tba_numbers"]) for e in o] == [2, 1]
    assert all(pi_erasure.is_placeholder(x) for e in o for x in e["tba_numbers"])
    assert o[1]["bag_id"] == "(loose)"
    assert _fresh(db, new).tote_roster[1]["bag_id"] == f"(loose) {TBA}"
    assert out["tbas"]["truck_zones.tote_roster"] == 4


def test_an_erasure_reaches_the_roster_and_only_that_package(db):
    z = _zone(db)
    res = _erase(db, "tba", TBA)
    db.commit()
    roster = _fresh(db, z).tote_roster
    assert roster[0]["tba_numbers"][1] == "TBAKEEP00000001"
    assert pi_erasure.is_placeholder(roster[0]["tba_numbers"][0])
    assert roster[1]["bag_id"] == "(loose)"
    assert res.counts["truck_zones.tote_roster"] == 3


def test_a_dry_run_leaves_the_roster(db):
    z = _zone(db)
    res = _erase(db, "tba", TBA, dry_run=True)
    db.commit()
    assert _fresh(db, z).tote_roster[1]["bag_id"] == f"(loose) {TBA}"
    assert res.counts["truck_zones.tote_roster"] == 3


# ── D5: a tote door's coordinates ───────────────────────────────────────────

def _tote(db, days_ago=0):
    t = ToteAddress(id=uuid.uuid4(), company_id=SEED_COMPANY_ID, truck_id=uuid.uuid4(),
                    entry_date=date.today() - timedelta(days=days_ago), bag_id="B1",
                    raw_address="350 5th Ave", normalised_address="350 5 AVE",
                    block_key="5_Ave_300", lat=40.7484, lng=-73.9857,
                    first_cross_street="W 33 ST", second_cross_street="W 34 ST",
                    segment_id="0012345")
    db.add(t)
    db.commit()
    return t


def _assert_door_gone(t):
    assert (t.raw_address, t.normalised_address, t.lat, t.lng,
            t.first_cross_street, t.second_cross_street) == (None,) * 6
    assert t.block_key == "5_Ave_300" and t.segment_id == "0012345", "the sort keeps these"


def test_the_48h_job_takes_the_coordinates_with_the_address(db):
    old, new = _tote(db, days_ago=3), _tote(db, days_ago=0)
    with patch.object(cleanup, "SessionLocal", return_value=db), patch.object(db, "close"), \
         patch.object(cleanup.settings, "delivery_address_retention_hours", 48):
        cleanup.null_expired_delivery_addresses()
    _assert_door_gone(_fresh(db, old))
    assert _fresh(db, new).lat == 40.7484


def test_an_address_erasure_takes_the_coordinates_too(db):
    t = _tote(db)
    _erase(db, "address", "350 5 AVE")
    db.commit()
    _assert_door_gone(_fresh(db, t))

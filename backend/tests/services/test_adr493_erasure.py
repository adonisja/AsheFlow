"""ADR-493 — Personal Information is erasable by what Amazon names.

Real rows throughout. An erasure is a set of rows that must change and a set
that must NOT (another tenant's, tenant-less ones, the truck's own anchor), and
only real rows can show both.

Postgres ARRAY columns (`routes.tba_numbers`, `delivery_stops.tba_numbers`) do
not exist in SQLite. The `array_as_json` fixture stores them as JSON for the
duration of a test — bind, result and DDL — so the list logic is exercised on
real rows rather than skipped.
"""
import json
import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.audit_log import AuditLog
from app.models.building_profile import BuildingProfile
from app.models.building_profile_verification import BuildingProfileVerification
from app.models.collection import CollectedAddressProfile
from app.models.delivery_stop import DeliveryStop
from app.models.pi_erasure_ledger import PiErasureLedger
from app.models.rts import RTSPackage
from app.models.scorecard_import import ScorecardImportPending
from app.models.tote_ops import PackageRemoval
from app.models.truck_zone import TruckZone
from app.models.walker_route import Route
from app.routers import privacy
from app.services import pi_erasure
from app.tasks import cleanup
from tests.conftest import SEED_COMPANY_ID, make_employee, sqlite_mirror_with_defaults

OTHER = uuid.uuid4()
ADDR = "433 W 32 ST"
TBA = "TBA123456789000"
KEY = "test-ledger-key"


@pytest.fixture(autouse=True)
def array_as_json(monkeypatch):
    from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY
    orig_bind, orig_result = PG_ARRAY.bind_processor, PG_ARRAY.result_processor

    def bind(self, dialect):
        if dialect.name == "sqlite":
            return lambda v: None if v is None else json.dumps(list(v))
        return orig_bind(self, dialect)

    def result(self, dialect, coltype):
        if dialect.name == "sqlite":
            return lambda v: None if v is None else json.loads(v)
        return orig_result(self, dialect, coltype)

    monkeypatch.setattr(PG_ARRAY, "bind_processor", bind)
    monkeypatch.setattr(PG_ARRAY, "result_processor", result)


@pytest.fixture(autouse=True)
def _tables(db, array_as_json):
    models = {pi_erasure.resolve(t) for t in pi_erasure.REGISTRY}
    from app.models.walker_route import RouteParticipant   # Route eager-loads it
    models |= {BuildingProfileVerification, PiErasureLedger, RouteParticipant}
    for m in models:
        sqlite_mirror_with_defaults(m.__table__).create(db.get_bind(), checkfirst=True)


# ── row builders ────────────────────────────────────────────────────────────

def _route(db, company=SEED_COMPANY_ID, days_ago=0, tbas=(TBA, "TBAOTHER0000001"), addrs=(ADDR,)):
    r = Route(id=uuid.uuid4(), company_id=company, truck_assignment_id=uuid.uuid4(),
              route_date=date.today() - timedelta(days=days_ago), route_number=1, capacity_limit=10,
              tba_numbers=list(tbas), normalised_addresses=list(addrs),
              stops=[{"address": addrs[0] if addrs else None, "block_key": "b1",
                      "tba_numbers": list(tbas)}])
    db.add(r)
    db.commit()
    return r


def _profile(db, company=SEED_COMPANY_ID, address=ADDR, note=None):
    p = BuildingProfile(id=uuid.uuid4(), company_id=company, normalised_address=address,
                        block_key="b1", building_type="walkup", workload_class="low",
                        submitted_by_name="W", raw_note=note)
    db.add(p)
    db.add(BuildingProfileVerification(id=uuid.uuid4(), company_id=company, profile_id=p.id,
                                       weight=1, building_type="walkup"))
    db.commit()
    return p


def _collected(db, company, address="433 West 32nd Street"):
    c = CollectedAddressProfile(id=uuid.uuid4(), company_id=company, token_id=uuid.uuid4(),
                                address=address, building_type="walkup", workload_class="low",
                                collected_on=date.today())
    db.add(c)
    db.commit()
    return c


def _audit(db, company, after, target="rts_packages", days_ago=0):
    a = AuditLog(id=uuid.uuid4(), company_id=company, action_type="x", target_table=target,
                 target_id=uuid.uuid4(), after_snapshot=after,
                 created_at=datetime.now(timezone.utc) - timedelta(days=days_ago))
    db.add(a)
    db.commit()
    return a


def _erase(db, kind, value, company=SEED_COMPANY_ID, dry_run=False):
    return pi_erasure.erase(db, pi_erasure.Request(kind=kind, value=value, company_id=company),
                            dry_run=dry_run)


def _fresh(db, obj):
    db.expire_all()
    from sqlalchemy import inspect
    return db.get(type(obj), inspect(obj).identity[0])


# ── address ─────────────────────────────────────────────────────────────────

class TestAnAddressIsErasedEverywhereInTheTenant:
    def test_every_spelling_of_the_door_goes(self, db):
        prof = _profile(db)
        route = _route(db)
        stop = DeliveryStop(id=uuid.uuid4(), company_id=SEED_COMPANY_ID, route_id=route.id,
                            truck_assignment_id=uuid.uuid4(), block_key="b1", stop_sequence=1,
                            normalised_address=ADDR, tba_numbers=[TBA])
        db.add(stop)
        db.commit()
        coll = _collected(db, SEED_COMPANY_ID)
        audit = _audit(db, SEED_COMPANY_ID, {"normalised_address": ADDR, "route_id": "r"})
        note = ScorecardImportPending(id=uuid.uuid4(), company_id=SEED_COMPANY_ID, week="2026-W01",
                                      transporter_id="T", payload={},
                                      note=f"dropped at 433 w. 32nd st by mistake")
        db.add(note)
        db.commit()

        res = _erase(db, "address", "433 West 32nd Street")
        db.commit()

        assert _fresh(db, prof) is None and db.query(BuildingProfileVerification).count() == 0
        assert _fresh(db, coll) is None
        assert _fresh(db, stop).normalised_address is None
        r = _fresh(db, route)
        assert len(r.normalised_addresses) == 1 and pi_erasure.is_placeholder(r.normalised_addresses[0])
        assert "address" not in r.stops[0] and r.stops[0]["block_key"] == "b1"
        assert _fresh(db, audit).after_snapshot == {"normalised_address": "[erased]", "route_id": "r"}
        assert "[erased]" in _fresh(db, note).note and "32nd" not in _fresh(db, note).note
        assert {ADDR, "433 West 32nd Street"} <= res.matched_spellings

    def test_another_tenant_and_tenantless_rows_are_untouched(self, db):
        theirs = _profile(db, company=OTHER)
        open_campaign = _collected(db, None)
        their_audit = _audit(db, OTHER, {"normalised_address": ADDR})
        _erase(db, "address", ADDR)
        db.commit()
        assert _fresh(db, theirs) is not None
        assert _fresh(db, open_campaign) is not None
        assert _fresh(db, their_audit).after_snapshot == {"normalised_address": ADDR}

    def test_the_trucks_own_anchor_is_exempt_in_audit(self, db):
        anchor = _audit(db, SEED_COMPANY_ID, {"address": ADDR}, target="trucks")
        _erase(db, "address", ADDR)
        db.commit()
        assert _fresh(db, anchor).after_snapshot == {"address": ADDR}

    def test_platform_scope_reaches_only_tenantless_rows(self, db):
        open_campaign = _collected(db, None)
        mine = _collected(db, SEED_COMPANY_ID)
        _erase(db, "address", ADDR, company=None)
        db.commit()
        assert _fresh(db, open_campaign) is None
        assert _fresh(db, mine) is not None

    def test_a_dry_run_changes_nothing_and_reports_everything(self, db):
        """Asserted on the SESSION, before any rollback. The first version
        rolled back and then looked — which hid a dry run that deleted (probe P3
        passed against it). erase() itself must not touch anything."""
        prof = _profile(db)
        route = _route(db)
        _audit(db, SEED_COMPANY_ID, {"normalised_address": ADDR})
        res = _erase(db, "address", ADDR, dry_run=True)
        assert not db.deleted and not db.dirty and not db.new
        assert res.counts["building_profiles.normalised_address"] == 1
        assert res.counts["routes.normalised_addresses"] == 1
        db.commit()
        assert _fresh(db, prof) is not None
        assert _fresh(db, route).normalised_addresses == [ADDR]


# ── package ─────────────────────────────────────────────────────────────────

class TestAPackageIsErasedAndCountsSurvive:
    def test_lists_keep_their_length(self, db):
        route = _route(db)
        z = TruckZone(id=uuid.uuid4(), company_id=SEED_COMPANY_ID, truck_id=uuid.uuid4(),
                      truck_polygon={}, zone_label="Z", zone_date=date.today(), created_by_name="x",
                      package_tbas=[TBA, "KEEP"])
        rts = RTSPackage(id=uuid.uuid4(), company_id=SEED_COMPANY_ID, route_id=route.id,
                         truck_assignment_id=uuid.uuid4(), tba_number=TBA.lower(),
                         rts_type="business_closed", rts_explanation="closed")
        rem = PackageRemoval(id=uuid.uuid4(), company_id=SEED_COMPANY_ID, removal_date=date.today(),
                             bag_id="B1", tba=TBA, tba_numbers=[TBA])
        db.add_all([z, rts, rem])
        db.commit()
        audit = _audit(db, SEED_COMPANY_ID, {"tba_number": TBA, "stage": "x"})

        _erase(db, "tba", TBA)
        db.commit()

        r = _fresh(db, route)
        assert len(r.tba_numbers) == 2 and pi_erasure.is_placeholder(r.tba_numbers[0])
        assert r.tba_numbers[1] == "TBAOTHER0000001", "only the requested package goes"
        assert len(r.stops[0]["tba_numbers"]) == 2 and TBA not in r.stops[0]["tba_numbers"]
        assert _fresh(db, z).package_tbas[1] == "KEEP" and len(_fresh(db, z).package_tbas) == 2
        assert pi_erasure.is_placeholder(_fresh(db, rts).tba_number), "case-insensitive match"
        assert _fresh(db, rem).tba is None and pi_erasure.is_placeholder(_fresh(db, rem).tba_numbers[0])
        assert _fresh(db, audit).after_snapshot["tba_number"] == "[erased]"

    def test_placeholders_are_unique(self, db):
        route = _route(db, tbas=(TBA, TBA))
        _erase(db, "tba", TBA)
        db.commit()
        a, b = _fresh(db, route).tba_numbers
        assert a != b


# ── endpoint, audit, ledger ─────────────────────────────────────────────────

class TestTheEndpoint:
    def _mgr(self, db):
        return make_employee(db, role="management", name="Mgr")

    def test_dry_run_is_the_default(self):
        assert privacy.ErasureRequest(kind="tba", value=TBA).dry_run is True

    @pytest.mark.parametrize("body", [
        {"kind": "name", "value": "Jane Doe"},
        {"kind": "tba", "value": "x" * 201},
        {"kind": "tba", "value": TBA, "scope": "all"},
    ])
    def test_the_request_is_bounded(self, body):
        with pytest.raises(ValidationError):
            privacy.ErasureRequest(**body)

    def test_an_endpoint_dry_run_writes_no_ledger_and_no_audit(self, db):
        prof = _profile(db)
        with patch.object(privacy.settings, "pi_erasure_hmac_key", KEY):
            out = privacy.erase_for_tenant(body=privacy.ErasureRequest(kind="address", value=ADDR),
                                           _={}, caller=self._mgr(db), db=db)
        assert out.dry_run is True and out.total >= 1
        assert db.query(PiErasureLedger).count() == 0
        assert db.query(AuditLog).filter_by(action_type="privacy.erasure").count() == 0
        assert _fresh(db, prof) is not None

    def test_a_real_run_without_the_key_refuses_and_changes_nothing(self, db):
        prof = _profile(db)
        with patch.object(privacy.settings, "pi_erasure_hmac_key", ""), pytest.raises(HTTPException) as e:
            privacy.erase_for_tenant(body=privacy.ErasureRequest(kind="address", value=ADDR, dry_run=False),
                                     _={}, caller=self._mgr(db), db=db)
        assert e.value.status_code == 503
        assert _fresh(db, prof) is not None

    def test_a_real_run_ledgers_and_audits_without_the_value(self, db):
        _profile(db)
        with patch.object(privacy.settings, "pi_erasure_hmac_key", KEY):
            out = privacy.erase_for_tenant(
                body=privacy.ErasureRequest(kind="address", value=ADDR, dry_run=False),
                _={}, caller=self._mgr(db), db=db)
        assert out.total >= 1 and ADDR in out.matched
        ledger = db.query(PiErasureLedger).one()
        audit = db.query(AuditLog).filter_by(action_type="privacy.erasure").one()
        assert ledger.value_hash == pi_erasure.value_hash("address", ADDR, KEY)
        blob = json.dumps(audit.after_snapshot) + ledger.value_hash
        assert "433" not in blob and "32" not in blob.replace(ledger.value_hash, ""), \
            "neither record may carry the erased value"


class TestTheLedgerSurvivesARestore:
    def test_replay_erases_a_restored_row(self, db):
        _profile(db)
        _erase(db, "address", ADDR)
        db.add(PiErasureLedger(id=uuid.uuid4(), company_id=SEED_COMPANY_ID, kind="address",
                               value_hash=pi_erasure.value_hash("address", ADDR, KEY),
                               erased_at=datetime.now(timezone.utc)))
        db.commit()
        restored = _profile(db, address="433 west 32nd street")    # the backup brought it back

        out = pi_erasure.replay_ledger(db, KEY, datetime.now(timezone.utc) - timedelta(days=31))
        db.commit()
        assert out["erased"] >= 1 and _fresh(db, restored) is None

    def test_the_wrong_key_matches_nothing(self, db):
        db.add(PiErasureLedger(id=uuid.uuid4(), company_id=SEED_COMPANY_ID, kind="address",
                               value_hash=pi_erasure.value_hash("address", ADDR, "other-key"),
                               erased_at=datetime.now(timezone.utc)))
        db.commit()
        restored = _profile(db)
        out = pi_erasure.replay_ledger(db, KEY, datetime.now(timezone.utc) - timedelta(days=31))
        assert out["erased"] == 0 and _fresh(db, restored) is not None


# ── nightly retention ───────────────────────────────────────────────────────

class TestNightlyRetention:
    def _run(self, db, backfill=False):
        with patch.object(cleanup, "SessionLocal", return_value=db), patch.object(db, "close"), \
             patch.multiple(cleanup.settings, tba_retention_days=90, delivery_address_retention_hours=48):
            return cleanup.expire_package_ids_and_audit_pi(backfill=backfill)

    def test_old_tbas_become_placeholders_and_lengths_hold(self, db):
        old, new = _route(db, days_ago=100), _route(db, days_ago=10)
        out = self._run(db)
        o, n = _fresh(db, old), _fresh(db, new)
        assert len(o.tba_numbers) == 2 and all(pi_erasure.is_placeholder(x) for x in o.tba_numbers)
        assert all(pi_erasure.is_placeholder(x) for x in o.stops[0]["tba_numbers"])
        assert n.tba_numbers == [TBA, "TBAOTHER0000001"]
        assert out["tbas"]["routes.tba_numbers"] == 2

    def test_a_second_run_finds_nothing(self, db):
        _route(db, days_ago=100)
        self._run(db)
        assert self._run(db)["tbas"] == {}

    def test_the_window_leaves_history_for_the_backfill(self, db):
        ancient = _route(db, days_ago=400)
        self._run(db)
        assert _fresh(db, ancient).tba_numbers[0] == TBA
        self._run(db, backfill=True)
        assert pi_erasure.is_placeholder(_fresh(db, ancient).tba_numbers[0])

    def test_audit_snapshots_lose_addresses_after_48h_but_not_the_truck_anchor(self, db):
        rts_audit = _audit(db, SEED_COMPANY_ID, {"normalised_address": ADDR, "tba_number": TBA}, days_ago=3)
        recent = _audit(db, SEED_COMPANY_ID, {"normalised_address": ADDR}, days_ago=0)
        anchor = _audit(db, SEED_COMPANY_ID, {"address": ADDR}, target="trucks", days_ago=3)
        self._run(db)
        snap = _fresh(db, rts_audit).after_snapshot
        assert snap["normalised_address"] == "[erased]"
        assert snap["tba_number"] == TBA, "TBAs are on the 90-day clock, not 48h"
        assert _fresh(db, recent).after_snapshot["normalised_address"] == ADDR
        assert _fresh(db, anchor).after_snapshot["address"] == ADDR


class TestWalkerNotesAreScrubbedAtWrite:
    def test_every_raw_note_write_goes_through_the_scrub(self):
        """AST, not text: every `raw_note=` keyword or assignment in the router
        must be a call to scrub_note. A new write site that forgets fails here."""
        import ast
        import inspect
        from app.routers import building_profiles
        tree = ast.parse(inspect.getsource(building_profiles))
        writes = []
        for n in ast.walk(tree):
            if isinstance(n, ast.keyword) and n.arg == "raw_note":
                writes.append(n.value)
        assert writes, "found no raw_note writes — the scan is broken"
        for v in writes:
            inner = v.value if isinstance(v, ast.Subscript) else v
            assert isinstance(inner, ast.Call) and getattr(inner.func, "id", None) == "scrub_note", \
                ast.unparse(v)


class TestThePlatformEndpoint:
    def test_erases_tenantless_rows_and_records_the_owner(self, db):
        open_row = _collected(db, None)
        tenant_row = _collected(db, SEED_COMPANY_ID)
        owner = {"id": "cognito-sub-123", "email": "owner@example.com"}
        with patch.object(privacy.settings, "pi_erasure_hmac_key", KEY):
            out = privacy.erase_for_platform(
                body=privacy.ErasureRequest(kind="address", value=ADDR, dry_run=False),
                super_admin=owner, db=db)
        assert out.total >= 1
        assert _fresh(db, open_row) is None and _fresh(db, tenant_row) is not None
        ledger = db.query(PiErasureLedger).one()
        assert ledger.company_id is None and ledger.erased_by == "cognito-sub-123"

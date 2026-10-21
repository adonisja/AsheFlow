"""ADR-504 — the survey register: who may write, how a door gets recorded, who reads.

Real rows on SQLite. The city's address list (NYC AddressPoint) is stubbed: the
property under test is that the SERVER fetches it and the client never supplies
it, not the HTTP call itself.
"""
import ast
import pathlib
import uuid
from datetime import date, datetime, timezone

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.audit_log import AuditLog
from app.models.survey_register import (
    SurveyArea, SurveyAreaBlock, SurveyBlockClaim, SurveyContributor, SurveyDeliveryPoint,
    SurveyDoorUnlock, SurveyObservation, SurveyReceivesFor, SurveyWalk,
    SurveyObservationWithdrawal, SurveyWithdrawal,
)
from app.routers import survey_register as R
from app.services import survey_blocks
from tests.conftest import SEED_COMPANY_ID, make_employee, sqlite_mirror_with_defaults

LAT, LNG = 40.7505, -73.9934          # Manhattan, inside the request bounds
BLOCK = "W_32_St_400"


@pytest.fixture(autouse=True)
def _tables(db):
    for m in (SurveyContributor, SurveyArea, SurveyAreaBlock, SurveyWalk, SurveyObservation,
              SurveyDeliveryPoint, SurveyReceivesFor, SurveyBlockClaim, SurveyDoorUnlock,
              SurveyWithdrawal, SurveyObservationWithdrawal, AuditLog):   # ADR-555
        sqlite_mirror_with_defaults(m.__table__).create(db.get_bind(), checkfirst=True)


@pytest.fixture(autouse=True)
def city(monkeypatch):
    """Two blocks near the point, as the city's list would return them."""
    calls = []

    def fake(lat, lng, radius_m=150):
        calls.append((lat, lng, radius_m))
        return [
            survey_blocks.Block(BLOCK, "W 32 ST", [
                {"address": "401 W 32 ST", "bin": "1000001", "lat": 40.75, "lng": -73.99},
                {"address": "433 W 32 ST", "bin": "1000002", "lat": 40.75, "lng": -73.99},
            ]),
            survey_blocks.Block("W_33_St_400", "W 33 ST", [
                {"address": "410 W 33 ST", "bin": "1000003", "lat": 40.75, "lng": -73.99},
            ]),
        ]
    monkeypatch.setattr(survey_blocks, "blocks_near", fake)

    def fake_enrich(doors):
        """Block 1/01073 faces W 32 and W 31; its other door is on W 31 St."""
        return [{**d, "city_block": "101073", "sides": ["W 32 ST", "W 31 ST", "9 AVE"],
                 "neighbours": [{"address": o["address"], "bin": o["bin"]} for o in doors
                                if o["address"] != d["address"]]
                               + [{"address": "433 W 31 ST", "bin": "1000009"}]}
                for d in doors]
    monkeypatch.setattr(survey_blocks, "enrich_doors", fake_enrich)
    return calls


OWNER = {"id": "owner-sub-0001", "cognito_groups": ["super_admin"]}


def _surveyor(sub="surveyor-sub-01"):
    return {"id": sub, "cognito_groups": ["surveyor"]}


def _admit(db, sub="surveyor-sub-01", revoked=False):
    c = SurveyContributor(id=uuid.uuid4(), cognito_sub=sub, display_name="A Contributor",
                          agreement_version="v1", agreement_signed_on=date(2026, 10, 13))
    if revoked:
        from datetime import datetime, timezone
        c.revoked_at = datetime.now(timezone.utc)
    db.add(c)
    db.commit()
    return c


def _walk(db, writer, **over):
    body = dict(lat=LAT, lng=LNG, block_key=BLOCK,
                attest_off_shift=True, attest_unbranded=True, attest_as_self=True)
    body.update(over)
    return R.start_walk(R.StartWalkIn(**body), writer=writer, db=db)


def _obs(db, writer, walk_id, **over):
    body = dict(address_index=1, source="mailroom", building_type="freight")
    body.update(over)
    # ADR-555: past slowapi's decorator (needs a live Request; the handler never reads it).
    return R.record_observation.__wrapped__(request=None, walk_id=walk_id, body=R.ObservationIn(**body),
                                            writer=writer, db=db)


OWNER_W = R.Writer(sub="owner-sub-0001", owner=True)


# ── D1: who may write ───────────────────────────────────────────────────────

class TestWhoMayWrite:
    def test_the_owner_writes(self, db):
        assert R.get_writer(OWNER, db) == OWNER_W

    def test_a_surveyor_without_a_contributor_row_is_refused(self, db):
        with pytest.raises(HTTPException) as e:
            R.get_writer(_surveyor(), db)
        assert e.value.status_code == 403

    def test_a_revoked_contributor_is_refused(self, db):
        _admit(db, revoked=True)
        with pytest.raises(HTTPException) as e:
            R.get_writer(_surveyor(), db)
        assert e.value.status_code == 403

    def test_an_admitted_contributor_writes(self, db):
        _admit(db)
        assert R.get_writer(_surveyor(), db) == R.Writer(sub="surveyor-sub-01", owner=False)

    @pytest.mark.parametrize("groups", [[], ["platform_support"], ["management"]])
    def test_nobody_else_writes(self, db, groups):
        with pytest.raises(HTTPException) as e:
            R.get_writer({"id": "someone-1234", "cognito_groups": groups}, db)
        assert e.value.status_code == 403

    def test_an_employee_linked_account_is_refused_on_every_write(self, db, monkeypatch):
        """Checked on each request, not only at admission: an account that LATER
        gains an employee record stops writing at once."""
        _admit(db)
        R.get_writer(_surveyor(), db)                       # fine today
        emp = make_employee(db, role="walker")
        emp.cognito_sub = "surveyor-sub-01"
        db.commit()
        monkeypatch.setattr(R.settings, "survey_excluded_company_id", str(SEED_COMPANY_ID))
        with pytest.raises(HTTPException) as e:
            R.get_writer(_surveyor(), db)
        assert e.value.status_code == 403

    def test_with_no_company_configured_any_employee_link_is_refused(self, db, monkeypatch):
        monkeypatch.setattr(R.settings, "survey_excluded_company_id", "")
        _admit(db)
        emp = make_employee(db, role="walker")
        emp.cognito_sub = "surveyor-sub-01"
        db.commit()
        with pytest.raises(HTTPException):
            R.get_writer(_surveyor(), db)

    def test_admission_refuses_an_employee_linked_account(self, db, monkeypatch):
        monkeypatch.setattr(R.settings, "survey_excluded_company_id", "")
        emp = make_employee(db, role="walker")
        emp.cognito_sub = "employee-sub-99"
        db.commit()
        with pytest.raises(HTTPException) as e:
            R.admit_contributor(R.ContributorIn(cognito_sub="employee-sub-99", display_name="X",
                                                agreement_version="v1",
                                                agreement_signed_on=date(2026, 10, 13)),
                                super_admin=OWNER, db=db)
        assert e.value.status_code == 403
        assert db.query(SurveyContributor).count() == 0

    def test_admission_is_audited_and_once(self, db):
        body = R.ContributorIn(cognito_sub="new-sub-12345", display_name="Pat",
                               agreement_version="v1", agreement_signed_on=date(2026, 10, 13))
        R.admit_contributor(body, super_admin=OWNER, db=db)
        assert db.query(AuditLog).filter_by(action_type="survey.contributor.admit").count() == 1
        with pytest.raises(HTTPException) as e:
            R.admit_contributor(body, super_admin=OWNER, db=db)
        assert e.value.status_code == 409


# ── D2/D3: how a door gets recorded ─────────────────────────────────────────

class TestTheProtocol:
    @pytest.mark.parametrize("field", ["attest_off_shift", "attest_unbranded", "attest_as_self"])
    def test_every_confirmation_is_required(self, field):
        with pytest.raises(ValidationError):
            R.StartWalkIn(lat=LAT, lng=LNG, block_key=BLOCK, **{
                "attest_off_shift": True, "attest_unbranded": True, "attest_as_self": True,
                field: False})

    def test_the_server_fetches_the_list_and_snapshots_it(self, db, city):
        w = _walk(db, OWNER_W)
        assert city == [(LAT, LNG, 150)]
        assert [a.address for a in w.addresses] == ["401 W 32 ST", "433 W 32 ST"]
        stored = db.get(SurveyWalk, w.id)
        assert stored.source_dataset == R.settings.socrata_addresspoint_dataset
        assert [a["address"] for a in stored.addresses] == ["401 W 32 ST", "433 W 32 ST"]

    def test_a_block_not_on_the_city_list_is_refused(self, db):
        with pytest.raises(HTTPException) as e:
            _walk(db, OWNER_W, block_key="Some_Other_Block_100")
        assert e.value.status_code == 422

    def test_the_request_body_cannot_carry_addresses(self):
        with pytest.raises(ValidationError):
            R.StartWalkIn(lat=LAT, lng=LNG, block_key=BLOCK, attest_off_shift=True,
                          attest_unbranded=True, attest_as_self=True,
                          addresses=[{"address": "1 FAKE ST"}])

    def test_outside_new_york_is_refused(self):
        with pytest.raises(ValidationError):
            R.StartWalkIn(lat=51.5, lng=-0.12, block_key=BLOCK, attest_off_shift=True,
                          attest_unbranded=True, attest_as_self=True)

    def test_the_door_comes_from_the_snapshot(self, db):
        w = _walk(db, OWNER_W)
        o = _obs(db, OWNER_W, w.id, address_index=1)
        assert (o.address, o.bin, o.source) == ("433 W 32 ST", "1000002", "mailroom")
        row = db.get(SurveyObservation, o.id)
        assert row.attestation == R.ATTESTATION and row.observed_on == date.today()

    def test_a_door_off_the_list_is_refused(self, db):
        w = _walk(db, OWNER_W)
        with pytest.raises(HTTPException) as e:
            _obs(db, OWNER_W, w.id, address_index=2)
        assert e.value.status_code == 422

    def test_a_door_is_recorded_once_per_walk(self, db):
        w = _walk(db, OWNER_W)
        _obs(db, OWNER_W, w.id)
        with pytest.raises(HTTPException) as e:
            _obs(db, OWNER_W, w.id)
        assert e.value.status_code == 409

    def test_a_closed_walk_takes_nothing(self, db):
        w = _walk(db, OWNER_W)
        R.close_walk(w.id, writer=OWNER_W, db=db)
        with pytest.raises(HTTPException) as e:
            _obs(db, OWNER_W, w.id)
        assert e.value.status_code == 409
        with pytest.raises(HTTPException) as e:
            R.close_walk(w.id, writer=OWNER_W, db=db)
        assert e.value.status_code == 409

    def test_someone_elses_walk_is_not_found(self, db):
        _admit(db)
        w = _walk(db, OWNER_W)
        with pytest.raises(HTTPException) as e:
            _obs(db, R.Writer(sub="surveyor-sub-01", owner=False), w.id)
        assert e.value.status_code == 404

    def test_an_unknown_building_type_is_refused(self, db):
        w = _walk(db, OWNER_W)
        with pytest.raises(HTTPException) as e:
            _obs(db, OWNER_W, w.id, building_type="castle")
        assert e.value.status_code == 422


# ── D4: what a record may hold ──────────────────────────────────────────────

class TestWhatARecordMayHold:
    @pytest.mark.parametrize("note", [
        "gate code 4471", "buzzer 12", "use the keypad", "door is #4471", "1234# at the side",
        "PIN is on the box",
    ])
    def test_codes_are_refused_with_the_reason(self, db, note):
        w = _walk(db, OWNER_W)
        with pytest.raises(HTTPException) as e:
            _obs(db, OWNER_W, w.id, note=note)
        assert e.value.status_code == 422 and "code" in e.value.detail

    def test_a_code_in_a_delivery_point_is_refused_too(self, db):
        w = _walk(db, OWNER_W)
        with pytest.raises(HTTPException):
            _obs(db, OWNER_W, w.id, delivery_points=[{"point": "service_entrance",
                                                      "side": "side door, code 99#"}])
        with pytest.raises(HTTPException):
            _obs(db, OWNER_W, w.id, delivery_points=[{"point": "mailroom",
                                                      "which_packages": "buzz 4B"}])

    def test_a_phone_number_is_scrubbed(self, db):
        w = _walk(db, OWNER_W)
        o = _obs(db, OWNER_W, w.id, note="service entrance on 33rd, call 212-555-0199")
        assert "555-0199" not in o.note and "service entrance" in o.note

    @pytest.mark.parametrize("over", [
        {"source": "the doorman"}, {"delivery_points": [{"point": "roof"}]}, {"floors": 0},
        {"floors": 500}, {"note": "x" * 501}, {"resident_name": "Bob"},
        {"security_desk": True}, {"delivery_points": [{"point": "mailroom"}] * 4},
        {"weekday": {"status": "open"}}, {"weekday": {"status": "closed", "open": "08:00"}},
        {"receives_for": [0, 0]}, {"break_start": "12:00"},
    ])
    def test_malformed_observations_are_refused(self, over):
        body = {"address_index": 0, "source": "observed", "building_type": "freight", **over}
        with pytest.raises(ValidationError):
            R.ObservationIn(**body)

    def test_a_malformed_company_setting_fails_closed(self, db, monkeypatch):
        """A typo in config must not let employees write: it falls back to the
        strict any-tenant rule."""
        monkeypatch.setattr(R.settings, "survey_excluded_company_id", "not-a-uuid")
        _admit(db)
        emp = make_employee(db, role="walker")
        emp.cognito_sub = "surveyor-sub-01"
        db.commit()
        with pytest.raises(HTTPException):
            R.get_writer(_surveyor(), db)


# ── D7: who reads ───────────────────────────────────────────────────────────

class TestWhoReads:
    def test_a_contributor_reads_only_their_own_and_the_owner_reads_all(self, db):
        _admit(db)
        me = R.Writer(sub="surveyor-sub-01", owner=False)
        owner_walk = _walk(db, OWNER_W)
        _obs(db, OWNER_W, owner_walk.id, address_index=0)
        # Since ADR-513 a contributor walks from a claim in an area, never by
        # scouting; this test is about READS, so the walk row is made directly.
        mine_walk = SurveyWalk(writer_sub=me.sub, block_key=BLOCK, street="W 32 ST",
                               addresses=db.get(SurveyWalk, owner_walk.id).addresses,
                               source_dataset="uf93-f8nk", fetched_at=datetime.now(timezone.utc),
                               attest_off_shift=True, attest_unbranded=True, attest_as_self=True)
        db.add(mine_walk)
        db.commit()
        _obs(db, me, mine_walk.id, address_index=1)
        mine = R.list_observations(bin=None, block_key=None, limit=200, writer=me, db=db)
        everything = R.list_observations(bin=None, block_key=None, limit=200, writer=OWNER_W, db=db)
        assert [o.address for o in mine] == ["433 W 32 ST"] and all(o.mine for o in mine)
        assert len(everything) == 2

    def test_audit_rows_carry_no_address(self, db):
        w = _walk(db, OWNER_W)
        _obs(db, OWNER_W, w.id)
        R.close_walk(w.id, writer=OWNER_W, db=db)
        for a in db.query(AuditLog).filter(AuditLog.action_type.like("survey.%")):
            assert "W 32" not in str(a.after_snapshot)


# ── D6: nothing writes the register except this router ─────────────────────

def test_only_the_register_router_constructs_register_rows():
    """No import path from tenant data (ADR-504 D6). A drift test in the
    ADR-464 style: scan the app, not a list."""
    app = pathlib.Path(R.__file__).resolve().parents[1]
    allowed = {app / "routers" / "survey_register.py", app / "models" / "survey_register.py"}
    offenders = []
    for path in app.rglob("*.py"):
        if path in allowed:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) in {
                    "SurveyObservation", "SurveyWalk", "SurveyContributor"}:
                offenders.append(f"{path.relative_to(app)}:{node.lineno}")
    assert not offenders, f"register rows constructed outside the register router: {offenders}"


def test_the_walk_confirmations_are_a_database_rule_too():
    names = {c.name for c in SurveyWalk.__table__.constraints}
    assert "ck_survey_walk_attested" in names


class TestLocate:
    def test_locate_uses_geoclient_not_the_library(self, monkeypatch):
        """D6: `resolve_address` reads and writes the PlaceType Library; the
        register must call the city's geocoder directly."""
        import inspect
        src = inspect.getsource(R.survey_locate)
        assert "_geoclient_normalise" in src and "resolve_address(" not in src

    def test_an_unknown_address_is_404(self, monkeypatch):
        import app.tasks.enrich_manifest as EM
        monkeypatch.setattr(EM, "_geoclient_normalise", lambda a, borough="manhattan": None)
        with pytest.raises(HTTPException) as e:
            R.survey_locate.__wrapped__(request=None, address="999 Nowhere St", borough="manhattan",
                                        writer=OWNER_W)
        assert e.value.status_code == 404


# ── ADR-504 D8: the form, version 2 ─────────────────────────────────────────

class TestFormV2:
    def test_the_walk_snapshots_block_sides_and_neighbours(self, db):
        w = _walk(db, OWNER_W)
        a = w.addresses[1]
        assert a.city_block == "101073" and a.sides[0] == "W 32 ST"
        assert [n.address for n in a.neighbours] == ["401 W 32 ST", "433 W 31 ST"]

    def test_up_to_three_delivery_points_are_kept_in_order(self, db):
        w = _walk(db, OWNER_W)
        o = _obs(db, OWNER_W, w.id, delivery_points=[
            {"point": "service_entrance", "side": "W 31 ST", "floor": 1},
            {"point": "front_desk", "which_packages": "for the ground-floor business", "floor": 2},
        ])
        assert [(p.position, p.point, p.side, p.floor) for p in o.delivery_points] == [
            (1, "service_entrance", "W 31 ST", 1), (2, "front_desk", None, 2)]
        assert o.delivery_points[1].which_packages == "for the ground-floor business"

    def test_receives_for_takes_only_same_block_doors(self, db):
        w = _walk(db, OWNER_W)
        o = _obs(db, OWNER_W, w.id, receives_for=[0, 1])
        assert [r.address for r in o.receives_for] == ["401 W 32 ST", "433 W 31 ST"]

    def test_receives_for_outside_the_block_is_refused(self, db):
        w = _walk(db, OWNER_W)
        with pytest.raises(HTTPException) as e:
            _obs(db, OWNER_W, w.id, receives_for=[2])
        assert e.value.status_code == 422 and "city block" in e.value.detail

    def test_the_request_cannot_name_an_address_to_receive_for(self):
        with pytest.raises(ValidationError):
            R.ObservationIn(address_index=0, building_type="freight", receives_for=["320 W 42 ST"])

    def test_hours_by_day_group(self, db):
        w = _walk(db, OWNER_W)
        o = _obs(db, OWNER_W, w.id,
                 weekday={"status": "open", "open": "08:00", "close": "17:00"},
                 saturday={"status": "open", "open": "09:00", "close": "15:00"},
                 sunday={"status": "closed"})
        assert (o.weekday.status, str(o.weekday.open), o.saturday.status, o.sunday.status) == (
            "open", "08:00:00", "open", "closed")

    def test_unanswered_means_didnt_find_out(self, db):
        w = _walk(db, OWNER_W)
        o = _obs(db, OWNER_W, w.id)
        assert (o.security_desk, o.sign_in_required, o.weekday.status, o.sunday.status) == (
            "unknown", "unknown", "unknown", "unknown")

    def test_not_a_delivery_point_needs_nothing_else(self, db):
        w = _walk(db, OWNER_W)
        o = _obs(db, OWNER_W, w.id, building_type=None, not_a_delivery_point=True)
        assert o.not_a_delivery_point and o.building_type == "unknown"
        assert R.get_walk(w.id, writer=OWNER_W, db=db).recorded == [1]

    def test_not_a_delivery_point_carries_no_delivery_details(self):
        with pytest.raises(ValidationError):
            R.ObservationIn(address_index=0, not_a_delivery_point=True,
                            delivery_points=[{"point": "mailroom"}])

    def test_a_delivery_point_needs_a_building_type(self):
        with pytest.raises(ValidationError):
            R.ObservationIn(address_index=0)


class TestSideOrdering:
    """D8 [B]: the owner's rule orders the streets the block actually faces."""
    def test_even_on_a_street_offers_one_street_down(self):
        assert survey_blocks.order_sides("330 W 34 ST", {"8 AVE", "9 AVE", "PENN PLZ", "W 33 ST", "W 34 ST"}) == [
            "W 34 ST", "W 33 ST", "8 AVE", "9 AVE", "PENN PLZ"]

    def test_odd_on_a_street_offers_one_street_up(self):
        assert survey_blocks.order_sides("331 W 34 ST", {"8 AVE", "9 AVE", "W 35 ST", "W 34 ST"})[:2] == [
            "W 34 ST", "W 35 ST"]

    def test_on_an_avenue_the_cross_streets_come_first(self):
        assert survey_blocks.order_sides("481 8 AVE", {"8 AVE", "9 AVE", "PENN PLZ", "W 34 ST", "W 35 ST"}) == [
            "8 AVE", "W 34 ST", "W 35 ST", "9 AVE", "PENN PLZ"]

    def test_a_street_the_block_does_not_face_is_never_offered(self):
        assert "W 33 ST" not in survey_blocks.order_sides("331 W 34 ST", {"W 34 ST", "W 35 ST"})


class TestEnrichmentFallback:
    def test_without_footprints_neighbours_are_same_street_side_and_hundred(self, monkeypatch):
        from app.services import survey_blocks as SB
        monkeypatch.undo()                                # the real enrich_doors
        monkeypatch.setattr(SB, "_fetch", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
        doors = [{"address": a, "bin": None, "lat": 40.75, "lng": -73.99}
                 for a in ("450 W 42 ST", "460 W 42 ST", "451 W 42 ST", "550 W 42 ST")]
        out = {d["address"]: d for d in SB.enrich_doors(doors)}
        assert [n["address"] for n in out["450 W 42 ST"]["neighbours"]] == ["460 W 42 ST"]
        assert out["450 W 42 ST"]["sides"] == ["W 42 ST"] and out["450 W 42 ST"]["city_block"] is None

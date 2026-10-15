"""ADR-512 — a stolen-package report is filed by the DA and signed by the driver or captain.

Behavioural, against the in-memory db with PRODUCTION's autoflush setting
(conftest, ADR-510). Endpoints are called directly with a real crew on a real
truck assignment.
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, time, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.anchor_point import AnchorPoint
from app.models.incident import Incident
from app.models.stolen_package_report import StolenPackageReport
from app.routers import stolen_package_reports as R
from tests.conftest import (
    SEED_COMPANY_ID, make_assignment, make_employee, make_member, make_truck,
    sqlite_mirror_with_defaults,
)

TODAY = date(2026, 10, 10)
TBA1, TBA2 = "TBA335358332455", "TBA000000000002"


@pytest.fixture(autouse=True)
def array_as_json(monkeypatch):
    """SQLite has no ARRAY; the ADR-493 erasure tests' shim, reused."""
    from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY
    ob, orr = PG_ARRAY.bind_processor, PG_ARRAY.result_processor

    def bind(self, dialect):
        return (lambda v: None if v is None else json.dumps(list(v))) if dialect.name == "sqlite" else ob(self, dialect)

    def result(self, dialect, coltype):
        return (lambda v: None if v is None else json.loads(v)) if dialect.name == "sqlite" else orr(self, dialect, coltype)
    monkeypatch.setattr(PG_ARRAY, "bind_processor", bind)
    monkeypatch.setattr(PG_ARRAY, "result_processor", result)


@pytest.fixture
def crew(db, array_as_json):
    for m in (Incident, StolenPackageReport, AnchorPoint):
        sqlite_mirror_with_defaults(m.__table__).create(db.get_bind(), checkfirst=True)
    truck = make_truck(db, "Truck 12")
    ta = make_assignment(db, truck, TODAY)
    da = make_employee(db, role="walker", name="Dana Walker")
    driver = make_employee(db, role="driver", name="Drew Driver")
    captain = make_employee(db, role="captain", name="Cap Tain")
    outsider = make_employee(db, role="walker", name="Other Walker")
    dispatch = make_employee(db, role="dispatch", name="Dee Dispatch")
    manager = make_employee(db, role="management", name="Max Manager")
    make_member(db, ta, da, "walker")
    make_member(db, ta, driver, "driver")
    make_member(db, ta, captain, "captain")
    db.commit()
    return dict(truck=truck, da=da, driver=driver, captain=captain,
                outsider=outsider, dispatch=dispatch, manager=manager)


def _body(**over):
    base = dict(incident_date=TODAY, incident_time=time(14, 50),
                incident_address="400 W 25 St", packages_stolen=1, tbas=[TBA1],
                summary="Parked and locked the cart outside 400 W 25 St; returned to find a package missing.")
    base.update(over)
    return R.StolenPackageIn(**base)


def _file(db, who, **over):
    with patch("app.services.notify._enqueue"):
        return R.file_report(_body(**over), db=db, caller=who, _={})


def _sign(db, who, incident_id, **over):
    body = R.SignIn(**{**_body(**over).model_dump(), "reviewer_comments": over.pop("reviewer_comments", None)}) \
        if "reviewer_comments" not in over else R.SignIn(**{**_body().model_dump(), **over})
    return R.sign(uuid.UUID(incident_id), body, db=db, caller=who, _={})


class TestTheForm:
    def test_the_owners_defaults(self):
        b = _body()
        assert (b.lmet_called, b.bike_locks_used, b.cart_cover_used, b.cart_stolen, b.totes_stolen) == \
               (False, True, True, False, 0)

    def test_tbas_are_validated_uppercased_and_deduplicated(self):
        assert _body(tbas=[TBA1.lower(), TBA1, f" {TBA2} "]).tbas == [TBA1, TBA2]
        with pytest.raises(ValidationError):
            _body(tbas=["TBA123"])

    def test_unknown_keys_are_refused(self):
        with pytest.raises(ValidationError):
            R.StolenPackageIn(**{**_body().model_dump(), "extra": 1})


class TestFiling:
    def test_it_creates_one_incident_and_the_da_version_and_asks_driver_and_captain(self, db, crew):
        out = _file(db, crew["da"])
        assert out["reviewers_notified"] == 2 and out["review_required"]
        inc = db.query(Incident).one()
        assert inc.category == "stolen_packages" and inc.reporter_id == crew["da"].id
        assert inc.incident_location is None, "the address lives on the report, where retention reaches it"
        da = db.query(StolenPackageReport).one()
        assert da.version == "da" and da.author_id == crew["da"].id and da.tbas == [TBA1]

    def test_a_da_who_is_the_only_driver_needs_no_review(self, db, crew):
        lone = make_employee(db, role="driver", name="Solo")
        t2 = make_truck(db, "Truck 9"); ta2 = make_assignment(db, t2, TODAY)
        make_member(db, ta2, lone, "driver"); db.commit()
        out = _file(db, lone)
        assert out["reviewers_notified"] == 0 and out["review_required"] is False


class TestVisibility:
    def test_who_can_see_it(self, db, crew):
        iid = uuid.UUID(_file(db, crew["da"])["incident_id"])
        for who in ("da", "driver", "captain", "dispatch"):
            R.get_report(iid, db=db, caller=crew[who], _={})
        with pytest.raises(HTTPException) as e:
            R.get_report(iid, db=db, caller=crew["outsider"], _={})
        assert e.value.status_code == 404

    def test_reviewer_comments_and_mismatches_are_oversight_only(self, db, crew):
        iid = _file(db, crew["da"])["incident_id"]
        _sign(db, crew["driver"], iid, packages_stolen=2, reviewer_comments="DA was on the phone")
        for who, sees in (("driver", False), ("captain", False), ("da", False), ("dispatch", True)):
            v = R.get_report(uuid.UUID(iid), db=db, caller=crew[who], _={})
            assert ("reviewer_comments" in v["versions"]["reviewer"]) is sees, who
            # The versions differ (1 vs 2 packages); only oversight is shown that.
            assert bool(v["mismatches"]) is sees, who


class TestSigning:
    def test_the_captain_can_sign_and_owns_the_copy(self, db, crew):
        iid = _file(db, crew["da"])["incident_id"]
        _sign(db, crew["captain"], iid)
        rv = db.query(StolenPackageReport).filter_by(version="reviewer").one()
        assert rv.author_id == crew["captain"].id and rv.signed_at is not None
        assert rv.da_employee_id == crew["da"].id

    def test_the_first_to_sign_wins(self, db, crew):
        iid = _file(db, crew["da"])["incident_id"]
        _sign(db, crew["driver"], iid)
        with pytest.raises(HTTPException) as e:
            _sign(db, crew["captain"], iid)
        assert e.value.status_code == 409

    def test_a_simultaneous_second_sign_is_a_409_not_a_500(self, db, crew):
        # Both pass the "already signed" read; the unique index decides.
        # The conftest mirror copies columns, not indexes: build the real one.
        from sqlalchemy import text
        db.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_stolen_report_version "
                        "ON stolen_package_reports (incident_id, version)"))
        iid = _file(db, crew["da"])["incident_id"]
        db.add(StolenPackageReport(company_id=SEED_COMPANY_ID, incident_id=uuid.UUID(iid),
                                   version="reviewer", author_id=crew["driver"].id,
                                   incident_date=TODAY, summary="raced", tbas=[]))
        db.flush()   # visible to the index, not to _load's earlier read
        with patch.object(R, "_load", side_effect=lambda d, i, c: (
                d.get(Incident, i),
                {"da": d.query(StolenPackageReport).filter_by(incident_id=i, version="da").one()})):
            with pytest.raises(HTTPException) as e:
                _sign(db, crew["captain"], iid)
        assert e.value.status_code == 409

    @pytest.mark.parametrize("who", ["da", "outsider", "dispatch"])
    def test_only_the_trucks_driver_or_captain_may_sign(self, db, crew, who):
        iid = _file(db, crew["da"])["incident_id"]
        with pytest.raises(HTTPException) as e:
            _sign(db, crew[who], iid)
        assert e.value.status_code == 403


    def test_a_captain_who_filed_cannot_sign_their_own_and_the_driver_can(self, db, crew):
        # The self-sign guard only matters when the filer is themselves a reviewer:
        # a walker DA is already refused by the reviewer check.
        out = _file(db, crew["captain"])
        assert out["reviewers_notified"] == 1, "the driver, not the filing captain"
        with pytest.raises(HTTPException) as e:
            _sign(db, crew["captain"], out["incident_id"])
        assert e.value.status_code == 403
        _sign(db, crew["driver"], out["incident_id"])


class TestToSign:
    def test_the_reviewers_list_holds_unsigned_reports_on_their_truck_only(self, db, crew):
        with patch.object(R, "company_today", return_value=TODAY):
            iid = _file(db, crew["da"])["incident_id"]
            for who in ("driver", "captain"):
                assert [x["incident_id"] for x in R.to_sign(db=db, caller=crew[who], _={})] == [iid], who
            assert R.to_sign(db=db, caller=crew["outsider"], _={}) == []
            assert R.to_sign(db=db, caller=crew["da"], _={}) == []
            _sign(db, crew["driver"], iid)
            assert R.to_sign(db=db, caller=crew["captain"], _={}) == [], "signed by the other reviewer"

    def test_a_filing_captain_does_not_see_their_own(self, db, crew):
        with patch.object(R, "company_today", return_value=TODAY):
            _file(db, crew["captain"])
            assert R.to_sign(db=db, caller=crew["captain"], _={}) == []
            assert len(R.to_sign(db=db, caller=crew["driver"], _={})) == 1


class TestLocking:
    def test_the_da_edits_until_signed_then_it_locks(self, db, crew):
        iid = uuid.UUID(_file(db, crew["da"])["incident_id"])
        R.edit_da(iid, _body(packages_stolen=2), db=db, caller=crew["da"], _={})
        _sign(db, crew["driver"], str(iid))
        with pytest.raises(HTTPException) as e:
            R.edit_da(iid, _body(packages_stolen=3), db=db, caller=crew["da"], _={})
        assert e.value.status_code == 409
        R.edit_da(iid, _body(packages_stolen=4), db=db, caller=crew["manager"], _={})


class TestMismatches:
    def test_differences_are_listed_field_by_field(self, db, crew):
        iid = _file(db, crew["da"])["incident_id"]
        _sign(db, crew["driver"], iid, incident_address="402 W 25 St", tbas=[TBA2, TBA1])
        m = R.get_report(uuid.UUID(iid), db=db, caller=crew["dispatch"], _={})["mismatches"]
        fields = {x["field"] for x in m}
        assert "incident_address" in fields and "tbas" in fields
        assert "summary" not in fields and "packages_stolen" not in fields


class TestTheIncidentFollowsTheReportOfRecord:
    def test_signing_moves_the_incident_to_the_signed_numbers_and_a_late_da_edit_does_not(self, db, crew):
        iid = _file(db, crew["da"])["incident_id"]
        inc = db.get(Incident, uuid.UUID(iid))
        assert inc.packages_tba == 1
        _sign(db, crew["driver"], iid, packages_stolen=3, summary="Signed account.")
        db.refresh(inc)
        assert (inc.packages_tba, inc.description) == (3, "Signed account.")
        R.edit_da(uuid.UUID(iid), _body(packages_stolen=9), db=db, caller=crew["manager"], _={})
        db.refresh(inc)
        assert inc.packages_tba == 3, "a correction to the superseded DA version is not the record"


class TestReportText:
    def test_the_owners_layout_in_order_without_private_comments(self, db, crew):
        iid = _file(db, crew["da"])["incident_id"]
        _sign(db, crew["driver"], iid, reviewer_comments="PRIVATE NOTE")
        txt = R.get_report_text(uuid.UUID(iid), db=db, caller=crew["dispatch"], _={})
        lines = [l.split(":")[0] for l in txt.splitlines()]
        assert lines == [
            "Date of incident", "DSP", "DA Name", "Incident Address", "Anchor Point Address",
            "Time of incident", "Was LMET called (Y/N)? N".split(":")[0],
            "LMET Case Number (if applicable)", "Were Bike Locks used to Anchor Totes (Y/N)? Y".split(":")[0],
            "Was a cart cover being used (Y/N)? Y".split(":")[0], "How many tote(s) were stolen? 0".split(":")[0],
            "Was the cart stolen (Y/N)? N".split(":")[0], "Number of stolen packages", "TBAs stolen", "Incident Summary",
        ]
        assert "PRIVATE NOTE" not in txt
        assert "Date of incident: 10/10/2026" in txt and "Time of incident: 2:50 PM" in txt
        assert f"TBAs stolen: {TBA1}" in txt and "DA Name: Dana Walker" in txt


class TestAnchorPointAtTheIncidentTime:
    def _ap(self, db, crew, seq, at, loc):
        db.add(AnchorPoint(id=uuid.uuid4(), company_id=SEED_COMPANY_ID, truck_id=crew["truck"].id,
                           driver_id=crew["driver"].id, date=TODAY, sequence=seq, is_initial=seq == 1,
                           status="confirmed", location=loc, submitted_at=at))
        db.commit()

    def test_the_one_active_then_not_the_first(self, db, crew):
        # Stored in UTC, as Postgres stores timestamptz: SQLite would keep an
        # offset value's wall-clock time and drop the offset.
        tz = timezone(timedelta(hours=-4))
        self._ap(db, crew, 1, datetime(2026, 10, 10, 13, 0, tzinfo=timezone.utc), "W 29 St & 9 Ave")   # 9:00 local
        self._ap(db, crew, 2, datetime(2026, 10, 10, 18, 0, tzinfo=timezone.utc), "W 33 St & 10 Ave")  # 14:00 local
        with patch.object(R, "company_tz", return_value=tz):
            assert R._anchor_at(db, SEED_COMPANY_ID, crew["truck"].id, TODAY, time(14, 50)) == "W 33 St & 10 Ave"
            assert R._anchor_at(db, SEED_COMPANY_ID, crew["truck"].id, TODAY, time(10, 0)) == "W 29 St & 9 Ave"
            assert R._anchor_at(db, SEED_COMPANY_ID, crew["truck"].id, TODAY, None) == "W 33 St & 10 Ave"


class TestRetention:
    def test_address_and_tbas_clear_at_60_days_and_the_rest_stays(self, db, crew):
        from app.tasks.cleanup import clear_stolen_package_pi
        old_day = date.today() - timedelta(days=61)
        new_day = date.today() - timedelta(days=59)
        for d in (old_day, new_day):
            make_assignment(db, crew["truck"], d)
        db.commit()
        _file(db, crew["da"], incident_date=old_day)
        _file(db, crew["da"], incident_date=new_day)
        with patch("app.tasks.cleanup.SessionLocal", return_value=db):
            out = clear_stolen_package_pi()
        assert out["cleared"] == 1
        db.expire_all()
        old = db.query(StolenPackageReport).filter_by(incident_date=old_day).one()
        new = db.query(StolenPackageReport).filter_by(incident_date=new_day).one()
        assert old.incident_address is None and old.tbas == [] and old.pi_cleared_at is not None
        assert old.packages_stolen == 1 and old.summary, "only the customer PI is cleared"
        assert new.incident_address == "400 W 25 St" and new.tbas == [TBA1]


def test_the_60_day_clearing_is_scheduled():
    # The address-retention coverage test exempts incident_address from the 48h
    # sweep BECAUSE this task clears it; an unscheduled task makes that a lie.
    from app.celery_app import celery_app
    tasks = {e["task"] for e in celery_app.conf.beat_schedule.values()}
    assert "app.tasks.cleanup.clear_stolen_package_pi" in tasks


def _gate(fn):
    import inspect
    return set(inspect.signature(fn).parameters["_"].default.dependency.allowed_roles)


def test_every_tenant_role_may_read_and_sign_from_the_canonical_list():
    from app.routers.registration import ROLE_TO_COGNITO_GROUP
    for fn in (R.get_report, R.sign, R.edit_da, R.get_report_text, R.to_sign):
        assert _gate(fn) == set(ROLE_TO_COGNITO_GROUP), fn.__name__


def test_only_field_roles_file_because_the_filer_is_named_as_the_da():
    filers = _gate(R.file_report)
    assert {"walker", "driver", "captain", "trainee", "trainer", "field_supervisor", "driver_trainee"} <= filers
    assert not filers & {"dispatch", "management", "admin"}
    assert _gate(R.prefill) == filers

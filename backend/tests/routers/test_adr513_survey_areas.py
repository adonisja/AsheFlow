"""ADR-513 — surveyors claim blocks inside declared areas; done doors are locked.

Real rows on SQLite. The city (boundaries and AddressPoint) is stubbed: the
properties under test are who may do what, and what the derived progress says.
"""
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.audit_log import AuditLog
from app.models.survey_register import (
    CLAIM_HOURS, MAX_ACTIVE_CLAIMS, REVISIT_DAYS,
    SurveyArea, SurveyAreaBlock, SurveyBlockClaim, SurveyContributor, SurveyDeliveryPoint,
    SurveyDoorUnlock, SurveyObservation, SurveyReceivesFor, SurveyWalk,
    SurveyObservationWithdrawal, SurveyWithdrawal,
)
from app.routers import survey_register as R
from app.services import survey_blocks, survey_progress
from app.services.survey_progress import block_progress
from tests.conftest import sqlite_mirror_with_defaults

T0 = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
OWNER = {"id": "owner-sub-0001", "cognito_groups": ["super_admin"]}
SUPPORT = {"id": "support-sub-0001", "email": "support@asheflow.com", "cognito_groups": ["platform_support"]}
ATTEST = dict(attest_off_shift=True, attest_unbranded=True, attest_as_self=True)


def _doors(street, nums):
    return [{"address": f"{n} {street}", "bin": "1083605", "lat": 40.75, "lng": -73.99} for n in nums]


# Two blocks in Manhattan, plus a Brooklyn block with the SAME key as one of them.
W32 = survey_blocks.Block("W_32_St_400", "W 32 ST", _doors("W 32 ST", [401, 403, 405]), borough="1")
W33 = survey_blocks.Block("W_33_St_400", "W 33 ST", _doors("W 33 ST", [410, 412]), borough="1")
BK_W32 = survey_blocks.Block("W_32_St_400", "W 32 ST", _doors("W 32 ST", [401, 403]), borough="3")


@pytest.fixture(autouse=True)
def _tables(db):
    for m in (SurveyContributor, SurveyArea, SurveyAreaBlock, SurveyWalk, SurveyObservation,
              SurveyDeliveryPoint, SurveyReceivesFor, SurveyBlockClaim, SurveyDoorUnlock,
              SurveyWithdrawal, SurveyObservationWithdrawal, AuditLog):   # ADR-555
        sqlite_mirror_with_defaults(m.__table__).create(db.get_bind(), checkfirst=True)


@pytest.fixture(autouse=True)
def city(monkeypatch):
    def boundary(kind, code):
        if code in ("MN0499", "199"):
            raise survey_blocks.UnknownBoundary(code)
        return survey_blocks.Boundary(kind, code, f"Area {code}", "9nt8-h7nd", {})
    blocks = {"MN0401": [W32, W33], "BK0101": [BK_W32], "104": [W32]}
    monkeypatch.setattr(survey_blocks, "fetch_boundary", boundary)
    monkeypatch.setattr(survey_blocks, "blocks_in_area", lambda b: [
        survey_blocks.Block(x.block_key, x.street, [dict(d) for d in x.doors], borough=x.borough)
        for x in blocks[b.code]])
    monkeypatch.setattr(survey_blocks, "blocks_near", lambda lat, lng, radius_m=150: [
        survey_blocks.Block(x.block_key, x.street, [dict(d) for d in x.doors], borough=x.borough)
        for x in (W32, W33)])
    monkeypatch.setattr(survey_blocks, "enrich_doors", lambda doors: [
        {**d, "city_block": "101073", "sides": ["W 32 ST"], "neighbours": []} for d in doors])


def _surveyor(db, sub="surveyor-sub-01"):
    db.add(SurveyContributor(id=uuid.uuid4(), cognito_sub=sub, display_name="A Contributor",
                             agreement_version="v1", agreement_signed_on=date(2026, 10, 13)))
    db.commit()
    return R.Writer(sub=sub, owner=False)


OWNER_W = R.Writer(sub=OWNER["id"], owner=True)


def _area(db, code="MN0401", kind="nta", staff=OWNER):
    return R.declare_area(R.AreaIn(kind=kind, code=code, reason="Coverage near the station"), staff=staff, db=db)


def _block(db, area, key="W_32_St_400"):
    return db.query(SurveyAreaBlock).filter_by(area_id=area.id, block_key=key).one()


def _claim_and_walk(db, writer, area, key="W_32_St_400"):
    claim = R.claim_block(area.id, _block(db, area, key).id, writer=writer, db=db)
    return claim, R.start_claimed_walk(claim.id, R.AttestIn(**ATTEST), writer=writer, db=db)


def _record(db, writer, walk, index, **over):
    body = {"address_index": index, "building_type": "freight", **over}
    # ADR-555: past slowapi's decorator, which needs a live Request; the
    # handler itself never reads it.
    return R.record_observation.__wrapped__(request=None, walk_id=walk.id, body=R.ObservationIn(**body),
                                            writer=writer, db=db)


# ── the replay: pure, so every rule is pinned without a database ───────────

class TestBlockProgress:
    D = ["1 A ST", "3 A ST"]

    def test_nothing_recorded_is_open(self):
        assert block_progress(self.D, [], [], T0).state == "open"

    def test_some_doors_is_in_progress(self):
        p = block_progress(self.D, [("1 A ST", T0)], [], T0)
        assert (p.state, p.done) == ("in_progress", {"1 A ST"})

    def test_the_last_door_completes_the_block_at_that_moment(self):
        p = block_progress(self.D, [("1 A ST", T0), ("3 A ST", T0 + timedelta(days=3))], [], T0 + timedelta(days=4))
        assert p.state == "done" and p.completed_at == T0 + timedelta(days=3)

    def test_the_whole_block_reopens_after_the_gap_not_door_by_door(self):
        # Door 1 was done long before door 3. Doors expiring one by one would
        # re-open door 1 alone while door 3 stayed done.
        obs = [("1 A ST", T0), ("3 A ST", T0 + timedelta(days=100))]
        mid = T0 + timedelta(days=REVISIT_DAYS + 50)          # door 1 is 230 days old
        assert block_progress(self.D, obs, [], mid).state == "done"
        after = T0 + timedelta(days=100 + REVISIT_DAYS)
        p = block_progress(self.D, obs, [], after)
        assert (p.state, p.done, p.completed_at) == ("open", set(), None)

    def test_an_incomplete_block_never_expires(self):
        p = block_progress(self.D, [("1 A ST", T0)], [], T0 + timedelta(days=900))
        assert p.state == "in_progress"

    def test_an_unlock_reopens_one_door_and_undoes_completion(self):
        obs = [("1 A ST", T0), ("3 A ST", T0)]
        p = block_progress(self.D, obs, [("3 A ST", T0 + timedelta(days=1))], T0 + timedelta(days=2))
        assert (p.state, p.done) == ("in_progress", {"1 A ST"})

    def test_a_door_the_city_dropped_does_not_block_completion(self):
        p = block_progress(["1 A ST"], [("1 A ST", T0), ("9 A ST", T0)], [], T0)
        assert p.state == "done" and p.done == {"1 A ST"}

    def test_a_door_the_city_added_is_open(self):
        p = block_progress(self.D + ["5 A ST"], [("1 A ST", T0), ("3 A ST", T0)], [], T0)
        assert p.state == "in_progress" and p.total == 3


# ── areas ──────────────────────────────────────────────────────────────────

class TestAreas:
    def test_owner_declares_and_the_blocks_are_snapshotted(self, db):
        out = _area(db)
        assert (out.blocks_total, out.doors_total, out.blocks_done) == (2, 5, 0)
        doors = _block(db, out).door_snapshot
        assert doors[0] == {"address": "401 W 32 ST", "bin": "1083605"}

    def test_a_block_that_cannot_be_walked_is_counted_not_dropped_silently(self, db, monkeypatch):
        nowhere = survey_blocks.Block("X_St_0", "X ST", [{"address": "1 X ST", "bin": None, "lat": None, "lng": None}],
                                      borough="1")
        monkeypatch.setattr(survey_blocks, "blocks_in_area", lambda b: [W32, nowhere])
        out = _area(db)
        assert out.blocks_total == 1
        a = db.query(AuditLog).filter_by(action_type="survey.area.declare").one()
        assert a.after_snapshot["blocks_skipped"] == 1

    def test_support_declares_and_is_audited_as_support(self, db):
        out = _area(db, staff=SUPPORT)
        assert out.declared_by_kind == "platform_support"
        a = db.query(AuditLog).filter_by(action_type="survey.area.declare").one()
        assert a.after_snapshot["actor_kind"] == "platform_support"

    def test_one_open_area_per_boundary(self, db):
        _area(db)
        with pytest.raises(HTTPException) as e:
            _area(db)
        assert e.value.status_code == 409

    def test_a_closed_area_can_be_declared_again(self, db):
        first = _area(db)
        R.close_area(first.id, staff=OWNER, db=db)
        assert _area(db).id != first.id

    def test_an_unknown_code_is_refused(self, db):
        with pytest.raises(HTTPException) as e:
            _area(db, code="MN0499")
        assert e.value.status_code == 422

    @pytest.mark.parametrize("kind,code", [("nta", "104"), ("cd", "MN0401"), ("nta", "MN04"), ("cd", "604")])
    def test_codes_must_have_the_citys_shape(self, kind, code):
        with pytest.raises(ValidationError):
            R.AreaIn(kind=kind, code=code, reason="why")

    def test_a_hand_drawn_polygon_is_not_accepted(self):
        with pytest.raises(ValidationError):
            R.AreaIn(kind="nta", code="MN0401", reason="why", polygon=[[0, 0]])

    def test_closing_releases_its_claims(self, db):
        area = _area(db)
        R.claim_block(area.id, _block(db, area).id, writer=OWNER_W, db=db)
        out = R.close_area(area.id, staff=SUPPORT, db=db)
        assert out.closed_at is not None
        assert db.query(SurveyBlockClaim).one().release_reason == "area_closed"
        with pytest.raises(HTTPException) as e:
            R.close_area(area.id, staff=SUPPORT, db=db)
        assert e.value.status_code == 409


# ── claims ─────────────────────────────────────────────────────────────────

class TestClaims:
    def test_a_claim_lasts_48_hours(self, db):
        area = _area(db)
        c = R.claim_block(area.id, _block(db, area).id, writer=OWNER_W, db=db)
        assert abs((c.expires_at - c.claimed_at) - timedelta(hours=CLAIM_HOURS)) < timedelta(seconds=5)

    def test_one_claim_per_block_and_the_holder_is_not_named(self, db):
        area = _area(db)
        R.claim_block(area.id, _block(db, area).id, writer=OWNER_W, db=db)
        other = _surveyor(db)
        with pytest.raises(HTTPException) as e:
            R.claim_block(area.id, _block(db, area).id, writer=other, db=db)
        assert e.value.status_code == 409
        view = R.area_blocks(area.id, lat=None, lng=None, viewer=R.AreaViewer(other.sub, other), db=db)
        held = next(b for b in view if b.block_key == "W_32_St_400")
        assert held.claim == "taken" and held.claim_id is None

    def test_one_claim_per_block_across_overlapping_areas(self, db):
        nta, cd = _area(db), _area(db, kind="cd", code="104")
        R.claim_block(nta.id, _block(db, nta).id, writer=OWNER_W, db=db)
        with pytest.raises(HTTPException) as e:
            R.claim_block(cd.id, _block(db, cd).id, writer=_surveyor(db), db=db)
        assert e.value.status_code == 409

    def test_the_same_key_in_another_borough_is_a_different_block(self, db):
        mn, bk = _area(db), _area(db, code="BK0101")
        R.claim_block(mn.id, _block(db, mn).id, writer=OWNER_W, db=db)
        R.claim_block(bk.id, _block(db, bk).id, writer=_surveyor(db), db=db)    # no 409

    def test_a_lapsed_claim_frees_the_block_without_any_write(self, db):
        area = _area(db)
        c = R.claim_block(area.id, _block(db, area).id, writer=OWNER_W, db=db)
        row = db.get(SurveyBlockClaim, c.id)
        row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
        R.claim_block(area.id, _block(db, area).id, writer=_surveyor(db), db=db)

    def test_no_more_than_three_at_once(self, db, monkeypatch):
        monkeypatch.setattr(R, "MAX_ACTIVE_CLAIMS", 1)
        area = _area(db)
        R.claim_block(area.id, _block(db, area).id, writer=OWNER_W, db=db)
        with pytest.raises(HTTPException) as e:
            R.claim_block(area.id, _block(db, area, "W_33_St_400").id, writer=OWNER_W, db=db)
        assert e.value.status_code == 409 and "1 blocks" in e.value.detail
        assert MAX_ACTIVE_CLAIMS == 3

    def test_release_is_once(self, db):
        area = _area(db)
        c = R.claim_block(area.id, _block(db, area).id, writer=OWNER_W, db=db)
        R.release_claim(c.id, writer=OWNER_W, db=db)
        with pytest.raises(HTTPException) as e:
            R.release_claim(c.id, writer=OWNER_W, db=db)
        assert e.value.status_code == 409

    def test_nobody_releases_or_walks_someone_elses_claim(self, db):
        area = _area(db)
        c = R.claim_block(area.id, _block(db, area).id, writer=OWNER_W, db=db)
        other = _surveyor(db)
        for call in (lambda: R.release_claim(c.id, writer=other, db=db),
                     lambda: R.start_claimed_walk(c.id, R.AttestIn(**ATTEST), writer=other, db=db)):
            with pytest.raises(HTTPException) as e:
                call()
            assert e.value.status_code == 404

    def test_a_closed_area_takes_no_claims(self, db):
        area = _area(db)
        R.close_area(area.id, staff=OWNER, db=db)
        with pytest.raises(HTTPException) as e:
            R.claim_block(area.id, _block(db, area).id, writer=OWNER_W, db=db)
        assert e.value.status_code == 409


# ── walking, locking, completing ───────────────────────────────────────────

class TestTheLadder:
    def test_a_claimed_walk_is_tied_to_its_claim_and_area(self, db):
        area = _area(db)
        claim, walk = _claim_and_walk(db, OWNER_W, area)
        assert walk.area_id == area.id
        assert db.get(SurveyBlockClaim, claim.id).walk_id == walk.id
        assert db.get(SurveyWalk, walk.id).borough == "1"

    def test_a_door_done_on_one_walk_is_ticked_and_locked_on_the_next(self, db):
        area = _area(db)
        _, first = _claim_and_walk(db, OWNER_W, area)
        _record(db, OWNER_W, first, 0)
        R.close_walk(first.id, writer=OWNER_W, db=db)              # a pause, not a finish

        other = _surveyor(db)
        _, second = _claim_and_walk(db, other, area)               # someone else continues it
        assert second.recorded == [0] and second.block_state == "in_progress"
        with pytest.raises(HTTPException) as e:
            _record(db, other, second, 0)
        assert e.value.status_code == 409
        _record(db, other, second, 1)                               # the rest stay open

    def test_finishing_early_releases_the_claim_and_leaves_the_block_in_progress(self, db):
        area = _area(db)
        claim, walk = _claim_and_walk(db, OWNER_W, area)
        _record(db, OWNER_W, walk, 0)
        R.close_walk(walk.id, writer=OWNER_W, db=db)
        assert db.get(SurveyBlockClaim, claim.id).release_reason == "walk_closed"
        b = next(x for x in R.area_blocks(area.id, lat=None, lng=None, viewer=R.AreaViewer(OWNER["id"], OWNER_W), db=db)
                 if x.block_key == "W_32_St_400")
        assert (b.state, b.doors_done, b.doors_total, b.claim) == ("in_progress", 1, 3, None)

    def test_the_last_door_completes_the_block_and_the_area_counts_it(self, db):
        area = _area(db)
        _, walk = _claim_and_walk(db, OWNER_W, area)
        _record(db, OWNER_W, walk, 0)
        _record(db, OWNER_W, walk, 1, not_a_delivery_point=True, building_type=None)   # [F] counts as done
        _record(db, OWNER_W, walk, 2)
        assert R.get_walk(walk.id, writer=OWNER_W, db=db).block_state == "done"
        a = R.list_areas(include_closed=False, viewer=R.AreaViewer(OWNER["id"], OWNER_W), db=db)[0]
        assert (a.blocks_done, a.blocks_total, a.doors_done, a.doors_total) == (1, 2, 3, 5)

    def test_a_done_block_cannot_be_claimed_and_says_when_it_reopens(self, db):
        area = _area(db)
        _, walk = _claim_and_walk(db, OWNER_W, area)
        for i in range(3):
            _record(db, OWNER_W, walk, i)
        R.close_walk(walk.id, writer=OWNER_W, db=db)
        with pytest.raises(HTTPException) as e:
            R.claim_block(area.id, _block(db, area).id, writer=_surveyor(db), db=db)
        assert e.value.status_code == 409 and "re-opens on" in e.value.detail

    def test_a_shared_bin_does_not_lock_another_address(self, db):
        """Every stub door carries BIN 1083605, like 314 9 Ave / 365 W 28 St /
        372 W 29 St in the city's data. Matching by BIN would lock them all."""
        area = _area(db)
        _, walk = _claim_and_walk(db, OWNER_W, area)
        _record(db, OWNER_W, walk, 0)
        assert R.get_walk(walk.id, writer=OWNER_W, db=db).recorded == [0]

    def test_the_owner_unlocks_one_door_for_a_correction(self, db):
        area = _area(db)
        _, walk = _claim_and_walk(db, OWNER_W, area)
        _record(db, OWNER_W, walk, 0)
        R.close_walk(walk.id, writer=OWNER_W, db=db)
        out = R.unlock_door(R.UnlockIn(walk_id=walk.id, address_index=0, reason="wrong building type"),
                            writer=OWNER_W, db=db)
        assert out.block_state == "open"
        _, again = _claim_and_walk(db, OWNER_W, area)
        _record(db, OWNER_W, again, 0)                               # re-recordable now
        assert db.query(SurveyObservation).count() == 2              # the old one stays (ADR-504 D5)

    def test_only_the_owner_unlocks_and_only_a_locked_door(self, db):
        area = _area(db)
        other = _surveyor(db)
        _, walk = _claim_and_walk(db, other, area)
        _record(db, other, walk, 0)
        with pytest.raises(HTTPException) as e:
            R.unlock_door(R.UnlockIn(walk_id=walk.id, address_index=0, reason="fix"), writer=other, db=db)
        assert e.value.status_code == 403
        with pytest.raises(HTTPException) as e:
            R.unlock_door(R.UnlockIn(walk_id=walk.id, address_index=1, reason="fix"), writer=OWNER_W, db=db)
        assert e.value.status_code == 409


# ── the gates on the old way in ────────────────────────────────────────────

class TestScouting:
    def _start(self, db, writer, key="W_32_St_400"):
        return R.start_walk(R.StartWalkIn(lat=40.7505, lng=-73.9934, block_key=key, **ATTEST),
                            writer=writer, db=db)

    def test_a_block_in_an_open_area_must_be_claimed(self, db):
        _area(db)
        with pytest.raises(HTTPException) as e:
            self._start(db, OWNER_W)
        assert e.value.status_code == 409

    def test_the_owner_scouts_outside_areas(self, db):
        walk = self._start(db, OWNER_W)
        assert walk.area_id is None and db.get(SurveyWalk, walk.id).borough == "1"

    def test_contributors_do_not_walk_outside_areas(self, db):
        with pytest.raises(HTTPException) as e:
            self._start(db, _surveyor(db))
        assert e.value.status_code == 403

    def test_support_reads_areas_but_never_walks(self, db):
        area = _area(db)
        v = R.get_area_viewer(SUPPORT, db)
        assert v.writer is None
        assert R.area_blocks(area.id, lat=None, lng=None, viewer=v, db=db)[0].claim is None
        with pytest.raises(HTTPException) as e:
            R.get_writer(SUPPORT, db)
        assert e.value.status_code == 403

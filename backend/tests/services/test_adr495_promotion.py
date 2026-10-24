"""ADR-495 — a collected door is promoted by the company that owns it.

Real rows throughout: promotion is a set of rows that must appear (the profile,
its anonymous observations, the stamps) and a set that must NOT change (the
company's existing profile, another tenant's rows, an unassigned open campaign).
"""
import json
import uuid
from datetime import date, datetime, time, timezone

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.audit_log import AuditLog
from app.models.building_profile import BuildingProfile
from app.models.building_profile_verification import BuildingProfileVerification
from app.models.collection import CollectedAddressProfile, CollectionToken
from app.models.company import Company
from app.routers import collection as C
from app.schemas.collection import PromoteIn
from app.services import collection_promotion as promo
from app.services.door_key import canonical_address
from tests.conftest import SEED_COMPANY_ID, make_employee, sqlite_mirror_with_defaults

OTHER = uuid.UUID("a0000000-0000-0000-0000-000000000002")


@pytest.fixture(autouse=True)
def array_as_json(monkeypatch):
    # building_profiles.days_open is a Postgres ARRAY (see test_adr493_erasure).
    from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY
    ob, orr = PG_ARRAY.bind_processor, PG_ARRAY.result_processor

    def bind(self, dialect):
        if dialect.name == "sqlite":
            return lambda v: None if v is None else json.dumps(list(v))
        return ob(self, dialect)

    def result(self, dialect, coltype):
        if dialect.name == "sqlite":
            return lambda v: None if v is None else json.loads(v)
        return orr(self, dialect, coltype)

    monkeypatch.setattr(PG_ARRAY, "bind_processor", bind)
    monkeypatch.setattr(PG_ARRAY, "result_processor", result)


@pytest.fixture(autouse=True)
def _tables(db, array_as_json):
    for m in (CollectionToken, CollectedAddressProfile, BuildingProfile,
              BuildingProfileVerification, AuditLog):
        sqlite_mirror_with_defaults(m.__table__).create(db.get_bind(), checkfirst=True)
    db.add(Company(id=OTHER, name="Other", slug="other", is_active=True))
    db.commit()


# ── builders ────────────────────────────────────────────────────────────────

def _token(db, company=SEED_COMPANY_ID, scope="company", revoked=False):
    t = CollectionToken(id=uuid.uuid4(), company_id=company, token=uuid.uuid4().hex,
                        label="Survey", scope=scope, dataset="addresses", daily_cap=500,
                        revoked_at=datetime.now(timezone.utc) if revoked else None)
    db.add(t)
    db.commit()
    return t


_seq = iter(range(10_000))


def _row(db, tok, address="433 West 32nd Street", btype="walkup", device=None, note=None,
         company="token", **kw):
    r = CollectedAddressProfile(
        id=uuid.uuid4(), company_id=tok.company_id if company == "token" else company,
        token_id=tok.id, address=address, door_key="", building_type=btype,
        workload_class="high_touch", workloads=["door_to_door"], device_id=device, note=note,
        collected_on=date(2026, 9, 1 + next(_seq) % 28),
        submitted_at=datetime(2026, 9, 1, tzinfo=timezone.utc).replace(minute=next(_seq) % 60),
        **kw)
    db.add(r)
    db.commit()
    return r


def _existing(db, address, company=SEED_COMPANY_ID, btype="elevator"):
    p = BuildingProfile(id=uuid.uuid4(), company_id=company, normalised_address=address,
                        block_key="b", building_type=btype, workload_class="standard",
                        submitted_by_name="Captain", building_type_status="locked")
    db.add(p)
    db.commit()
    return p


def _door(db, tok):
    doors = promo.doors_for(db, tok)
    assert len(doors) == 1, [d.address for d in doors]
    return doors[0]


def _promote(db, tok, *decisions, caller=None):
    caller = caller or make_employee(db, role="admin", name="Ada Admin")
    body = PromoteIn(decisions=[dict(d) for d in decisions])
    return C.promote_doors(token_id=tok.id, body=body, _={}, caller=caller, db=db)


def _profiles(db, company=SEED_COMPANY_ID, source="campaign"):
    return db.query(BuildingProfile).filter(BuildingProfile.company_id == company,
                                            BuildingProfile.collection_source == source).all()


# ── the canonical address ───────────────────────────────────────────────────

# Expected values were produced by running the page's canonicalAddress() under
# node (ADR-495 journal). Add a case here AND check it against the TS when either moves.
VECTOR = [
    ("433 West 32nd Street", "433 W 32 ST"),
    ("433 w. 32nd st, Apt 4A", "433 W 32 ST"),
    # ADR-582: the city's own spelling wins where AddressPoint has the street.
    # The web twin (a preview, ADR-582 D6) still gives "330 FIFTH AVE" and
    # "1 PENN PLAZA" for these two; the server is authoritative.
    ("330 Fifth Avenue", "330 5 AVE"),
    ("10 E 33rd St Floor 3", "10 E 33 ST"),
    ("2 east 33 street", "2 E 33 ST"),
    ("1 Penn Plaza", "1 PENN PLZ"),
    ("200 North End Ave Lobby", "200 N END AVE"),
    ("77 Lane Road", "77 LN RD"),
    ("12 Westend Ave", "12 WESTEND AVE"),
    ("5 Ave of the Americas", "5 AVE OF THE AMERICAS"),
    # The bug the vector found: a noise word that is the street's NAME.
    ("55 Front St", "55 FRONT ST"),
    ("55 Front Street Floor 2", "55 FRONT ST"),
    ("12 Rear Ave Unit 3", "12 REAR AVE"),
    ("10 Ground Rd", "10 GROUND RD"),
    ("433 W 32 St Front", "433 W 32 ST"),
]


@pytest.mark.parametrize("raw,want", VECTOR)
def test_canonical_address_matches_the_page(raw, want):
    assert canonical_address(raw) == want


def test_the_review_threshold_is_the_routers():
    from app.routers.building_profiles import _REVIEW_THRESHOLD
    assert promo.REVIEW_THRESHOLD == _REVIEW_THRESHOLD


# ── doors and states ────────────────────────────────────────────────────────

class TestDoors:
    def test_spellings_of_one_door_are_one_door(self, db):
        tok = _token(db)
        _row(db, tok, "433 West 32nd Street", device="d1")
        _row(db, tok, "433 W 32 ST Floor 3", device="d2")
        d = _door(db, tok)
        assert d.address == "433 W 32 ST" and d.state == promo.READY and len(d.observers) == 2

    def test_disagreement_is_a_conflict(self, db):
        tok = _token(db)
        _row(db, tok, btype="walkup")
        _row(db, tok, btype="elevator")
        assert _door(db, tok).state == promo.CONFLICT

    def test_a_door_the_company_has_is_exists(self, db):
        tok = _token(db)
        _existing(db, "433 W 32 ST")
        _row(db, tok)
        assert _door(db, tok).state == promo.EXISTS

    def test_another_companys_profile_does_not_make_it_exist(self, db):
        tok = _token(db)
        _existing(db, "433 W 32 ST", company=OTHER)
        _row(db, tok)
        assert _door(db, tok).state == promo.READY

    def test_a_bare_house_number_needs_an_address_check(self, db):
        tok = _token(db)
        _row(db, tok, "55")
        assert _door(db, tok).state == promo.CHECK_ADDRESS

    def test_rows_of_another_tenant_under_the_token_are_not_read(self, db):
        tok = _token(db)
        _row(db, tok, company=OTHER)
        assert promo.doors_for(db, tok) == []


# ── promotion ───────────────────────────────────────────────────────────────

class TestPromotion:
    def test_two_agreeing_observers_reach_review_never_verified(self, db):
        tok = _token(db)
        a = _row(db, tok, device="d1", opens_at=time(8), closes_at=time(18))
        b = _row(db, tok, "433 W 32 ST", device="d2")
        reviewer = make_employee(db, role="management", name="Mo Manager")
        out = _promote(db, tok, {"door_key": "433 w 32 st", "action": "promote"}, caller=reviewer)
        assert out.promoted == 1
        (p,) = _profiles(db)
        assert (p.building_type_status, p.building_type_agreement_count) == ("review", 2)
        assert p.normalised_address == "433 W 32 ST" and p.address_status == "pending"
        assert p.submitted_by == reviewer.id
        vs = db.query(BuildingProfileVerification).filter_by(profile_id=p.id).all()
        assert len(vs) == 2 and all(v.employee_id is None and v.weight == 1 for v in vs)
        db.expire_all()
        for r in (a, b):
            r = db.get(CollectedAddressProfile, r.id)
            assert r.review_status == "promoted" and r.reviewed_by == reviewer.id

    def test_one_device_twice_is_one_observer(self, db):
        tok = _token(db)
        _row(db, tok, device="same")
        _row(db, tok, "433 W 32 ST", device="same")
        _promote(db, tok, {"door_key": "433 w 32 st", "action": "promote"})
        (p,) = _profiles(db)
        assert (p.building_type_status, p.building_type_agreement_count) == ("pending", 1)
        assert db.query(BuildingProfileVerification).count() == 1

    def test_a_conflict_needs_a_choice_and_then_counts_one(self, db):
        tok = _token(db)
        _row(db, tok, btype="walkup", device="d1")
        chosen = _row(db, tok, btype="elevator", device="d2")
        out = _promote(db, tok, {"door_key": "433 w 32 st", "action": "promote"})
        assert out.outcomes[0].outcome == "needs_choice" and _profiles(db) == []
        out = _promote(db, tok, {"door_key": "433 w 32 st", "action": "promote",
                                 "use_row_id": str(chosen.id)})
        (p,) = _profiles(db)
        assert p.building_type == "elevator"
        assert (p.building_type_status, p.building_type_agreement_count) == ("pending", 1)

    def test_a_conflict_resets_to_one_even_when_two_rows_agree_with_the_choice(self, db):
        """Spellings merged into one door can hold three rows. Two that agree with
        the reviewer's pick are still a door the field disagreed about, and
        ADR-276 D4 resets a disagreement to one observation."""
        tok = _token(db)
        chosen = _row(db, tok, btype="walkup", device="d1")
        _row(db, tok, "433 W 32 ST", btype="walkup", device="d2")
        _row(db, tok, "433 W 32 St Floor 2", btype="elevator", device="d3")
        _promote(db, tok, {"door_key": "433 w 32 st", "action": "promote",
                           "use_row_id": str(chosen.id)})
        (p,) = _profiles(db)
        assert (p.building_type_status, p.building_type_agreement_count) == ("pending", 1)
        assert db.query(BuildingProfileVerification).count() == 1

    def test_a_choice_from_another_door_is_refused(self, db):
        tok = _token(db)
        _row(db, tok)
        stranger = _row(db, tok, "1 Penn Plaza")
        out = _promote(db, tok, {"door_key": "433 w 32 st", "action": "promote",
                                 "use_row_id": str(stranger.id)})
        assert out.outcomes[0].outcome == "invalid_choice" and _profiles(db) == []

    def test_an_existing_profile_is_skipped_and_untouched(self, db):
        tok = _token(db)
        mine = _existing(db, "433 W 32 ST", btype="elevator")
        r = _row(db, tok, btype="walkup")
        out = _promote(db, tok, {"door_key": "433 w 32 st", "action": "promote"})
        assert out.skipped == 1 and out.promoted == 0
        db.expire_all()
        mine = db.get(BuildingProfile, mine.id)
        assert (mine.building_type, mine.building_type_status) == ("elevator", "locked")
        assert db.get(CollectedAddressProfile, r.id).review_status == "skipped"

    def test_reject_stamps_without_writing_a_profile(self, db):
        tok = _token(db)
        r = _row(db, tok, "55")
        out = _promote(db, tok, {"door_key": "55", "action": "promote"})
        assert out.outcomes[0].outcome == "check_address"
        out = _promote(db, tok, {"door_key": "55", "action": "reject"})
        assert out.rejected == 1 and _profiles(db) == []
        db.expire_all()
        assert db.get(CollectedAddressProfile, r.id).review_status == "rejected"

    def test_a_stamped_door_is_never_promoted_again(self, db):
        tok = _token(db)
        _row(db, tok)
        _promote(db, tok, {"door_key": "433 w 32 st", "action": "reject"})
        out = _promote(db, tok, {"door_key": "433 w 32 st", "action": "promote"})
        assert out.outcomes[0].outcome == "already_reviewed" and _profiles(db) == []

    def test_the_note_is_scrubbed_and_collector_fields_are_dropped(self, db):
        tok = _token(db)
        _row(db, tok, note="Leave with super, call 212-555-0199", collected_by="Jay")
        _promote(db, tok, {"door_key": "433 w 32 st", "action": "promote"})
        (p,) = _profiles(db)
        assert "555-0199" not in (p.raw_note or "")
        assert "Jay" not in json.dumps({c.name: str(getattr(p, c.name))
                                        for c in BuildingProfile.__table__.columns})

    def test_the_audit_carries_counts_not_addresses(self, db):
        tok = _token(db)
        _row(db, tok)
        _promote(db, tok, {"door_key": "433 w 32 st", "action": "promote"})
        a = db.query(AuditLog).filter_by(action_type="collection.campaign.promote").one()
        assert a.after_snapshot["promoted"] == 1
        blob = json.dumps(a.after_snapshot)
        assert "W 32" not in blob and "West" not in blob


# ── who may ─────────────────────────────────────────────────────────────────

class TestScope:
    def test_promotion_is_management_and_admin_only(self):
        assert sorted(C._allow_promotion.allowed_roles) == ["admin", "management"]

    def test_another_companys_campaign_is_not_found(self, db):
        tok = _token(db, company=OTHER)
        with pytest.raises(HTTPException) as e:
            C.preview_promotion(token_id=tok.id, _={}, caller=make_employee(db, role="admin"), db=db)
        assert e.value.status_code == 404

    def test_an_unassigned_open_campaign_is_not_found(self, db):
        tok = _token(db, company=None, scope="open")
        with pytest.raises(HTTPException) as e:
            C.preview_promotion(token_id=tok.id, _={}, caller=make_employee(db, role="admin"), db=db)
        assert e.value.status_code == 404

    @pytest.mark.parametrize("body", [
        {"decisions": []},
        {"decisions": [{"door_key": "a", "action": "promote"}] * 2},
        {"decisions": [{"door_key": f"k{i}", "action": "reject"} for i in range(501)]},
        {"decisions": [{"door_key": "a", "action": "merge"}]},
        {"decisions": [{"door_key": "a", "action": "reject", "extra": 1}]},
    ], ids=["empty", "duplicate-door", "over-500", "bad-action", "extra-key"])
    def test_malformed_batches_are_refused(self, body):
        with pytest.raises(ValidationError):
            PromoteIn(**body)


# ── assignment (D3) was deleted by ADR-581 D8: open campaigns are retired,
#    so there is nothing to assign. test_adr581_no_tenant_writes_placetype pins
#    that the route is gone.

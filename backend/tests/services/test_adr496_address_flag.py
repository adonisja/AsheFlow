"""ADR-496 — an address that has lost its street is flagged, never silently stored.

The check exists for two failures. One is the input's (`55`). The other is OURS:
canonical_address() dropping a street the collector typed, which is how
`55 Front St` became `55` (ADR-495). The second is the one input validation can
never catch, so it has its own test that re-introduces the original bug.
"""
import re
import uuid
from datetime import date

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.models.audit_log import AuditLog
from app.models.building_profile import BuildingProfile
from app.models.building_profile_verification import BuildingProfileVerification
from app.models.collection import CollectedAddressProfile, CollectionToken
from app.routers import building_profiles as BP
from app.routers import collection as C
from app.schemas.collection import CollectionSubmitIn
from app.schemas.location_profile import BuildingProfileCreate
from app.services import door_key as DK
from tests.conftest import SEED_COMPANY_ID, make_employee, sqlite_mirror_with_defaults

# Expected values produced by the page's addressProblem() under node
# (--experimental-strip-types); the Python twin must agree with every one.
VECTOR = [
    ("55", "no_street"),
    ("55 W", "no_street"),
    ("55 Front", "no_street"),
    ("10 E 33", "no_street"),
    ("55 Front Plaza St", "street_lost"),   # today's canonicaliser still cuts this
    ("55 Front St", None),
    ("433 West 32nd Street", None),
    ("1 Penn Plaza", None),
    ("10 E 33 St Floor 3", None),
    ("5 Ave of the Americas", None),
    ("John Smith 380 W 33rd St", None),
    ("100-15 Astoria Blvd", None),
    ("12 Westend Ave", None),
    ("1 St Marks Pl", None),
]


@pytest.mark.parametrize("address,want", VECTOR)
def test_address_problem_matches_the_page(address, want):
    assert DK.address_problem(address) == want


def test_it_catches_the_original_bug_when_it_is_put_back(monkeypatch):
    """The point of `street_lost`: a canonicaliser regression is caught even
    though the input was a perfectly good address. Re-introduce the pre-ADR-495
    noise pattern (no street-name lookahead) and the original case must flag."""
    old = re.compile(
        r"\b(attn|attention|apt|unit|ground|floor|fl|host|suite|ste|basement|bsmt|lobby|rear|front)\b",
        re.IGNORECASE)
    monkeypatch.setattr(DK, "_NOISE", old)
    assert DK.canonical_address("55 Front St") == "55"
    assert DK.address_problem("55 Front St") == "street_lost"


# ── public submit: accepted AND flagged ─────────────────────────────────────

@pytest.fixture(autouse=True)
def _tables(db):
    for m in (CollectionToken, CollectedAddressProfile, BuildingProfile,
              BuildingProfileVerification, AuditLog):
        sqlite_mirror_with_defaults(m.__table__).create(db.get_bind(), checkfirst=True)


@pytest.fixture(autouse=True)
def _no_limiter():
    from app.api.ratelimit import limiter
    was = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = was


def _request():
    return Request({"type": "http", "method": "POST", "path": "/collection/submit",
                    "headers": [], "client": ("127.0.0.1", 1), "query_string": b""})


def _submit(db, *addresses, device="dev-0001"):
    tok = db.query(CollectionToken).first()
    if tok is None:
        tok = CollectionToken(id=uuid.uuid4(), company_id=None, token="t" * 32, label="L",
                              scope="open", dataset="addresses", daily_cap=500)
        db.add(tok)
        db.commit()
    body = CollectionSubmitIn(token=tok.token, device_id=device, profiles=[
        {"address": a, "building_type": "walkup", "workloads": ["door_to_door"],
         "collected_on": date.today().isoformat()} for a in addresses])
    return C.submit_profiles(request=_request(), body=body, db=db, caller=None)


class TestPublicSubmit:
    # "55" itself is under the schema's 3-character minimum; "455" is the same
    # failure at a length the schema accepts.
    def test_a_bare_number_is_accepted_and_flagged(self, db):
        out = _submit(db, "455", "433 W 32 ST")
        assert out.accepted == 2
        assert out.needs_review_addresses == ["455"]
        flags = {r.address: r.address_flag for r in db.query(CollectedAddressProfile)}
        assert flags == {"455": "no_street", "433 W 32 ST": None}

    def test_a_damaged_street_is_flagged_as_ours(self, db):
        _submit(db, "455 Front Plaza St")
        assert db.query(CollectedAddressProfile).one().address_flag == "street_lost"

    def test_a_correction_re_evaluates_the_flag(self, db):
        """ADR-426's update path recomputes rather than keeping the old flag: a
        row flagged under a buggier canonicaliser clears once resubmitted."""
        _submit(db, "433 W 32 ST")
        row = db.query(CollectedAddressProfile).one()
        row.address_flag = "street_lost"
        db.commit()
        out = _submit(db, "433 W 32 ST")
        assert out.updated == 1 and out.needs_review_addresses == []
        db.expire_all()
        assert db.query(CollectedAddressProfile).one().address_flag is None

    def test_a_device_resubmitting_is_flagged_again(self, db):
        """ADR-426's update path sets the flag too, and tells the collector."""
        _submit(db, "455")
        out = _submit(db, "455")
        assert out.updated == 1 and out.needs_review_addresses == ["455"]
        assert db.query(CollectedAddressProfile).one().address_flag == "no_street"

    def test_the_audit_counts_flags_without_addresses(self, db):
        _submit(db, "455")
        a = db.query(AuditLog).filter_by(action_type="collection.submit").one()
        assert a.after_snapshot["flagged"] == 1
        assert "455" not in str(a.after_snapshot)


# ── authenticated typed entry: refused with the remedy ──────────────────────

class TestManualEntry:
    def test_a_typed_bare_number_is_refused(self, db):
        caller = make_employee(db, role="captain")
        with pytest.raises(HTTPException) as e:
            BP.submit_building_profile(
                body=BuildingProfileCreate(normalised_address="455", building_type="walkup"),
                caller=caller, _={}, db=db)
        assert e.value.status_code == 422
        assert "street name" in e.value.detail
        assert db.query(BuildingProfile).count() == 0

    def test_a_stop_address_is_not_checked(self, db):
        """A stop's address came from GeoClient; block_key marks it."""
        caller = make_employee(db, role="captain")
        BP.submit_building_profile(
            body=BuildingProfileCreate(normalised_address="455", building_type="walkup",
                                       block_key="b"),
            caller=caller, _={}, db=db)
        assert db.query(BuildingProfile).count() == 1

    def test_bulk_confirm_re_checks_a_row_the_client_marked_ok(self, db):
        """The preview is not a trust boundary: `ok` is client-supplied."""
        from app.schemas.location_profile import BulkProfileConfirm, BulkProfileRow
        out = BP.confirm_bulk_profiles(
            body=BulkProfileConfirm(rows=[
                BulkProfileRow(line=2, address="455", building_type="walkup", ok=True),
                BulkProfileRow(line=3, address="433 W 32 ST", building_type="walkup", ok=True)]),
            caller=make_employee(db, role="captain"), _={}, db=db)
        assert (out.created, out.skipped) == (1, 1)
        assert [b.normalised_address for b in db.query(BuildingProfile)] == ["433 W 32 ST"]

    def test_the_bulk_preview_marks_the_row(self):
        rows = BP._parse_bulk_csv(b"address,building_type\n55,walkup\n433 W 32 ST,walkup\n")
        assert [(r.address, r.ok) for r in rows] == [("55", False), ("433 W 32 ST", True)]
        assert "street name" in rows[0].error


class TestPromotion:
    def test_a_damaged_street_cannot_be_promoted(self, db):
        """D4: recomputed from the address, so it holds for rows that predate the
        flag column too."""
        from app.services import collection_promotion as promo
        tok = CollectionToken(id=uuid.uuid4(), company_id=SEED_COMPANY_ID, token="c" * 32,
                              label="L", scope="company", dataset="addresses", daily_cap=500)
        db.add(tok)
        db.add(CollectedAddressProfile(
            id=uuid.uuid4(), company_id=SEED_COMPANY_ID, token_id=tok.id,
            address="455 Front Plaza St", door_key="", building_type="walkup",
            workload_class="high_touch", workloads=[], collected_on=date.today(),
            address_flag=None))   # as an old row would be
        db.commit()
        (door,) = promo.doors_for(db, tok)
        assert door.state == promo.CHECK_ADDRESS
        out = promo.promote(db, tok, [promo.Decision(door.key, "promote")],
                            make_employee(db, role="admin"))
        assert out[0].outcome == "check_address"
        assert db.query(BuildingProfile).count() == 0

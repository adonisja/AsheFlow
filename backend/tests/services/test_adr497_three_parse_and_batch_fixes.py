"""ADR-497 — three bugs found while building ADR-495/496, each pinned by the
failure it caused rather than by the fix's shape.

1. A duplicate inside a public collection batch rolled back the WHOLE batch,
   while the receipt still counted the earlier rows as accepted.
2. The routing parser cut "Front"/"Rear"/"Ground" street names as unit words,
   so `55 Front St` was unparseable.
3. A manual building profile whose address does not parse raised
   AttributeError (500): `UnparseableAddress` is truthy and has no block_key.
"""
import uuid
from datetime import date

import pytest
from sqlalchemy import UniqueConstraint
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
from app.services.derive_block_key import (
    ParsedBlock, UnparseableAddress, derive_block_key, strip_address_noise,
)
from tests.conftest import SEED_COMPANY_ID, make_employee, sqlite_mirror_with_defaults


@pytest.fixture(autouse=True)
def _tables(db):
    for m in (CollectionToken, BuildingProfile, BuildingProfileVerification, AuditLog):
        sqlite_mirror_with_defaults(m.__table__).create(db.get_bind(), checkfirst=True)
    # The mirror copies columns only, NOT unique constraints. Without the real
    # (token_id, collected_on, address) constraint no duplicate is ever raised,
    # and the first draft of these tests "reproduced" D1 by failing for exactly
    # that reason: 3 accepted, 0 duplicates. Add it back explicitly.
    t = sqlite_mirror_with_defaults(CollectedAddressProfile.__table__)
    t.append_constraint(UniqueConstraint("token_id", "collected_on", "address"))
    t.create(db.get_bind(), checkfirst=True)


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


def _token(db):
    tok = CollectionToken(id=uuid.uuid4(), company_id=SEED_COMPANY_ID, token="t" * 32, label="L",
                          scope="company", dataset="addresses", daily_cap=500)
    db.add(tok)
    db.commit()
    return tok



def _collector(db):
    """ADR-581 D8: open campaigns are retired, so a submission is a company
    campaign's, made by a signed-in employee of that company."""
    from app.models.employee import Employee
    emp = db.query(Employee).filter(Employee.company_id == SEED_COMPANY_ID).first()
    return emp or make_employee(db, role="captain")

def _submit(db, tok, *addresses, device):
    body = CollectionSubmitIn(token=tok.token, device_id=device, profiles=[
        {"address": a, "building_type": "walkup", "workloads": ["door_to_door"],
         "collected_on": date.today().isoformat()} for a in addresses])
    return C.submit_profiles(request=_request(), body=body, db=db, caller=_collector(db))


# ── 1. one duplicate must not discard the rest of the batch ─────────────────

class TestABatchSurvivesOneDuplicate:
    def test_rows_before_and_after_a_duplicate_are_kept(self, db):
        tok = _token(db)
        # Another device already sent this door today: the unique
        # (token, collected_on, address) constraint fires for it below.
        _submit(db, tok, "433 W 32 ST", device="other-device")
        out = _submit(db, tok, "1 PENN PLAZA", "433 W 32 ST", "10 E 33 ST", device="mine-0001")
        assert (out.accepted, out.duplicate) == (2, 1)
        db.expire_all()
        stored = sorted(r.address for r in db.query(CollectedAddressProfile))
        assert stored == ["1 PENN PLAZA", "10 E 33 ST", "433 W 32 ST"]

    def test_the_receipt_matches_the_table(self, db):
        """The bug's real harm: a receipt that said `accepted: 1` for a row the
        rollback had removed. Whatever the receipt says must be in the table."""
        tok = _token(db)
        _submit(db, tok, "433 W 32 ST", device="other-device")
        before = db.query(CollectedAddressProfile).count()
        out = _submit(db, tok, "1 PENN PLAZA", "433 W 32 ST", device="mine-0001")
        db.expire_all()
        assert db.query(CollectedAddressProfile).count() - before == out.accepted == 1


# ── 2. a street NAMED like a unit word is a street ──────────────────────────

class TestStreetNamesThatLookLikeUnitWords:
    @pytest.mark.parametrize("address,key", [
        ("55 Front St", "Front_St_0"),
        ("155 Front Street", "Front_St_100"),
        ("10 Ground Rd", "Ground_Rd_0"),
    ])
    def test_they_parse(self, address, key):
        parsed = derive_block_key(address, tba="")
        assert isinstance(parsed, ParsedBlock) and parsed.block_key == key

    @pytest.mark.parametrize("address,head", [
        ("607 W 23RD St Suite 301", "607 W 23RD St"),
        ("10 E 33 St Floor 3", "10 E 33 St"),
        ("433 W 32 St Front", "433 W 32 St"),
        ("55 Front St Rear", "55 Front St"),
    ])
    def test_real_unit_words_are_still_stripped(self, address, head):
        assert strip_address_noise(address) == head

    def test_the_routing_parser_and_the_collection_page_share_one_list(self):
        """ADR-496's failure mode: two noise lists drift. The routing pattern is
        BUILT from door_key's, so they cannot."""
        from app.services import derive_block_key as D
        assert D._NOISE_PATTERN == DK.NOISE_PATTERN


# ── 3. an unparseable typed address is stored, never a 500 ───────

class TestAnUnparseableManualAddress:
    # A lettered house number: common in Brooklyn and Queens, and the routing
    # parser reads it as "missing_house_number". ADR-496 passes it (it names a street).
    ADDR = "455A Main St"

    def test_it_really_is_unparseable(self):
        assert isinstance(derive_block_key(self.ADDR, tba=""), UnparseableAddress)
        assert DK.address_problem(self.ADDR) is None   # so ADR-496 lets it through

    def test_single_submit_stores_it_without_a_block_key(self, db):
        BP.submit_building_profile(
            body=BuildingProfileCreate(normalised_address=self.ADDR, building_type="walkup"),
            caller=make_employee(db, role="captain"), _={}, db=db)
        (p,) = db.query(BuildingProfile).all()
        assert p.block_key == "" and p.address_status == "pending"

    def test_bulk_confirm_stores_it_without_a_block_key(self, db):
        from app.schemas.location_profile import BulkProfileConfirm, BulkProfileRow
        out = BP.confirm_bulk_profiles(
            body=BulkProfileConfirm(rows=[BulkProfileRow(
                line=2, address=self.ADDR, building_type="walkup", ok=True)]),
            caller=make_employee(db, role="captain"), _={}, db=db)
        assert out.created == 1
        assert db.query(BuildingProfile).one().block_key == ""


# ── the backfill touches exactly the keys the old pattern produced ──────────

class TestTheBackfill:
    def _profile(self, db, address, key):
        p = BuildingProfile(id=uuid.uuid4(), company_id=SEED_COMPANY_ID,
                            normalised_address=address, block_key=key,
                            building_type="walkup", workload_class="standard",
                            submitted_by_name="W")
        db.add(p)
        db.commit()
        return p.id

    def test_empty_and_truncated_keys_are_fixed_and_nothing_else(self, db):
        import importlib.util, pathlib
        spec = importlib.util.spec_from_file_location(
            "rederive", pathlib.Path(__file__).parents[2] / "scripts" / "rederive_block_keys_adr497.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        empty = self._profile(db, "55 Front St", "")                    # old: unparseable
        truncated = self._profile(db, "455 Main Front St", "Main_400")  # old: cut at Front
        elsewhere = self._profile(db, "456 Main Front St", "Custom_Key")  # not the old output
        untouched = self._profile(db, "433 W 32 St", "W_32_St_400")     # unaffected address

        assert sum(mod.rederive(db).values()) == 2
        got = {i: db.get(BuildingProfile, i).block_key for i in (empty, truncated, elsewhere, untouched)}
        assert got == {empty: "Front_St_0", truncated: "Main_Front_St_400",
                       elsewhere: "Custom_Key", untouched: "W_32_St_400"}

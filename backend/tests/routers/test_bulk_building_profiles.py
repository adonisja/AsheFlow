"""ADR-277 D4/D5 — bulk building-profile seeding from a CSV.

Two failures these guard, both silent:

  * a bulk row landing at weight 2 (D5) — forty buildings pushed straight into
    `review` on one person's recollection, filling the sign-off queue with
    records nobody has recently seen
  * a confirm path trusting the preview — `ok=True` is client-supplied

building_profiles.py is proprietary; CI copies it in from AsheFlow-private
before pytest, so there is deliberately NO skip guard.
"""
import inspect

import pytest

from app.main import app
from app.routers import building_profiles as bp
from app.schemas.location_profile import (
    BulkProfileConfirm,
    BulkProfilePreview,
    BulkProfileRow,
)


def _parse(text: str):
    return bp._parse_bulk_csv(text.encode("utf-8"))


class TestRoutes:
    def test_both_endpoints_registered(self):
        paths = app.openapi()["paths"]
        assert "/api/v1/building-profiles/bulk/preview" in paths
        assert "/api/v1/building-profiles/bulk/confirm" in paths

    def test_drivers_cannot_bulk_seed(self):
        """The gate is _SIGNOFF_ROLES, not _allow_route_lead. Reusing a
        route-lead gate for a building question is the exact error ADR-276 had
        to correct — `_allow_delivery` records that a driver "does not walk
        blocks or assess difficulty"."""
        assert "driver" not in bp._SIGNOFF_ROLES
        src = inspect.getsource(bp.preview_bulk_profiles)
        assert "_allow_bulk_seed" in src
        assert "_allow_route_lead" not in src

        # Assert on the GATE OBJECT, not just the endpoint source. Widening it
        # happens at the definition (`_allow_bulk_seed = _allow_route_lead`),
        # which leaves the endpoint's own source untouched — a planted version
        # of exactly that slipped past the source checks above.
        allowed = set(getattr(bp._allow_bulk_seed, "allowed_roles", []))
        assert allowed, "could not read the gate's role list"
        assert "driver" not in allowed, (
            f"bulk seeding gate admits drivers: {sorted(allowed)}"
        )
        assert allowed == set(bp._SIGNOFF_ROLES)


class TestParsing:
    def test_happy_path(self):
        rows = _parse("address,building_type\n433 W 32 St,elevator\n")
        assert len(rows) == 1
        assert rows[0].ok and rows[0].building_type == "elevator"

    def test_bad_rows_are_kept_not_dropped(self):
        """The preview must show WHICH rows fail. A silently shortened list is
        how thirty rejected rows get discovered after the import."""
        rows = _parse(
            "address,building_type\n"
            "1 Good St,elevator\n"
            "2 Bad St,mansion\n"
            ",elevator\n"
            "4 No Type St,\n"
        )
        assert len(rows) == 4, "invalid rows must survive into the preview"
        assert [r.ok for r in rows] == [True, False, False, False]
        assert "mansion" in rows[1].error
        assert "address" in rows[2].error.lower()
        assert "building_type" in rows[3].error

    def test_line_numbers_match_the_file(self):
        """An operator fixes the file by line number, so row 1 of the data is
        line 2 — the header is line 1."""
        rows = _parse("address,building_type\n1 A St,elevator\n2 B St,walkup\n")
        assert [r.line for r in rows] == [2, 3]

    def test_header_aliases_and_excel_bom(self):
        """Operators type headers into a spreadsheet by hand, and Excel writes
        a UTF-8 BOM that would otherwise make the first column unmatchable."""
        rows = bp._parse_bulk_csv(
            "﻿Address,Building Type,Note\n1 A St,walkup,leave at desk\n".encode("utf-8")
        )
        assert rows[0].ok
        assert rows[0].raw_note == "leave at desk"

    def test_missing_address_column_is_rejected_with_guidance(self):
        with pytest.raises(Exception) as e:
            _parse("street,building_type\n1 A St,walkup\n")
        assert "address" in str(e.value).lower()

    def test_empty_and_headerless_files_are_rejected(self):
        for text in ("", "address,building_type\n"):
            with pytest.raises(Exception):
                _parse(text)

    def test_non_utf8_says_what_to_do(self):
        with pytest.raises(Exception) as e:
            bp._parse_bulk_csv(b"\xff\xfe\x00address")
        assert "CSV" in str(e.value)

    def test_row_cap_is_enforced_during_parse(self):
        """Bounded before building 10,000 objects, not after."""
        body = "".join(f"{i} Long St,walkup\n" for i in range(bp._MAX_BULK_ROWS + 5))
        with pytest.raises(Exception) as e:
            _parse("address,building_type\n" + body)
        assert str(bp._MAX_BULK_ROWS) in str(e.value)


class TestDuplicateMarking:
    def test_within_file_duplicates_are_caught(self):
        """Checking only the database would let a file containing the same
        address twice import once and silently drop the other."""
        src = inspect.getsource(bp._mark_duplicates)
        assert "Duplicate of an earlier row in this file" in src
        assert "seen" in src

    def test_database_duplicates_are_bulk_queried(self):
        """One query for the batch. Forty rows must not be forty round-trips."""
        src = inspect.getsource(bp._mark_duplicates)
        assert "normalised_address.in_(candidates)" in src

    def test_duplicate_lookup_is_company_scoped(self):
        src = inspect.getsource(bp._mark_duplicates)
        assert "company_id == caller.company_id" in src


class TestConfirmIsATrustBoundary:
    def test_it_revalidates_rather_than_trusting_ok(self):
        """`ok` is client-supplied. A client can post rows that were never
        previewed, or flip ok=True on a row the preview rejected."""
        src = inspect.getsource(bp.confirm_bulk_profiles)
        assert "row.ok" not in src, "confirm must not branch on the client's ok flag"
        assert "btype not in BUILDING_TYPES" in src

    def test_it_rechecks_duplicates_against_the_database(self):
        src = inspect.getsource(bp.confirm_bulk_profiles)
        assert "normalised_address.in_(wanted)" in src
        assert "company_id == caller.company_id" in src

    def test_request_schema_is_bounded_and_strict(self):
        """ADR-115 dim 9: a request body is attacker-controlled input."""
        assert BulkProfileConfirm.model_config.get("extra") == "forbid"
        assert BulkProfileRow.model_config.get("extra") == "forbid"
        meta = str(BulkProfileConfirm.model_fields["rows"].metadata)
        assert "500" in meta


class TestD5Weight:
    def test_bulk_rows_carry_weight_one_regardless_of_role(self):
        """THE D5 rule. A captain's confirmation is worth 2 (ADR-276 D1)
        because it pays for observation — someone who walked the building.
        Bulk entry is recollection at volume, so it is worth 1.

        The failure is silent: at weight 2 every row lands in `review`
        immediately and the sign-off queue fills with buildings nobody has
        recently seen."""
        # Strip comments: the code explains D5 by NAMING the helper it must not
        # use, and a naive substring search reads that explanation as the
        # offence. (Same trap as the ADR-280 seed scanner.)
        src = "\n".join(
            ln for ln in inspect.getsource(bp.confirm_bulk_profiles).splitlines()
            if not ln.lstrip().startswith("#")
        )
        src = "\n".join(ln.split("#")[0] for ln in src.splitlines())
        assert "_verify_weight" not in src, (
            "bulk must NOT use the role-weighting helper — that is exactly the "
            "authority D5 says recollection has not earned"
        )
        assert "weight        = 1" in src
        assert "building_type_agreement_count = 1" in src

    def test_bulk_rows_start_pending_not_review(self):
        src = inspect.getsource(bp.confirm_bulk_profiles)
        assert 'building_type_status          = "pending"' in src

    def test_bulk_addresses_are_queued_for_resolution(self):
        """Typed by a human, so they need canonicalising (D1). Unlike the
        single-submit path there is no stop context to say otherwise."""
        src = inspect.getsource(bp.confirm_bulk_profiles)
        assert 'address_status     = "pending"' in src
        assert "resolve_pending_addresses.delay()" in src

    def test_each_row_writes_its_own_verification(self):
        """ADR-276 D3: the count and the rows must agree, or the audit trail
        has a number with nothing explaining it."""
        src = inspect.getsource(bp.confirm_bulk_profiles)
        assert "BuildingProfileVerification(" in src

    def test_the_batch_is_audited(self):
        src = inspect.getsource(bp.confirm_bulk_profiles)
        assert "write_audit(" in src
        assert "building_profile.bulk_create" in src

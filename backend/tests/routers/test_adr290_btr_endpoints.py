"""ADR-290 — BTR sheet endpoints: preview never writes, confirm refuses a foreign sheet.

The load-bearing tests here are the refusals:

  - preview must have NO write path, because that is what forces an OCR read
    through a human (D3). A parser that could persist would make the
    confirmation step optional in practice.
  - confirm must reject a DSP mismatch OUTRIGHT (D6). Importing another DSP's
    sheet attributes their totes to this company, and a partial import is worse
    than none because it looks like it worked.
  - every row written must carry company_id directly (dim 1).
"""
import uuid
from datetime import date

import pytest
from fastapi import HTTPException

from app.models.btr_sheet import BTRSheet, BTRRoute, BTRBag, BTROVZone
from app.models.company import Company
from app.routers.btr_sheets import (
    BTRSheetConfirm, RouteIn, BagIn, OVZoneIn, _check_dsp, _to_out,
)
from app.services.btr_ingestor import CSVBTRIngestor


# ── request schema hardening (dim 9) ──────────────────────────────────────────

def test_confirm_payload_rejects_unknown_keys():
    with pytest.raises(Exception):
        BTRSheetConfirm(
            truck_id=uuid.uuid4(), sheet_date=date.today(), source="csv", bogus=1,
        )


def test_confirm_payload_rejects_an_invalid_source():
    """Literal, not a free string — `source` records provenance and drives
    whether a human confirmed the values."""
    with pytest.raises(Exception):
        BTRSheetConfirm(truck_id=uuid.uuid4(), sheet_date=date.today(), source="telepathy")


def test_counts_cannot_be_negative():
    with pytest.raises(Exception):
        RouteIn(amazon_route_name="WE37", package_count=-1)
    with pytest.raises(Exception):
        OVZoneIn(zone_label="A-27.2W", ov_count=-1)


def test_lists_are_bounded():
    """An unbounded list is an unbounded write. A truck carries ~12 routes; the
    cap is generous but finite."""
    with pytest.raises(Exception):
        BTRSheetConfirm(
            truck_id=uuid.uuid4(), sheet_date=date.today(), source="csv",
            routes=[RouteIn(amazon_route_name=f"WE{i}") for i in range(101)],
        )
    with pytest.raises(Exception):
        RouteIn(amazon_route_name="WE37",
                bags=[BagIn(bag_id=str(i)) for i in range(201)])


def test_counts_are_optional_not_defaulted_to_zero():
    """An unread cell is unknown. Zero is a measurement, and would make the
    full-mode reconciliation report a discrepancy that is really a camera miss."""
    r = RouteIn(amazon_route_name="WE37")
    assert r.package_count is None and r.bag_count is None and r.ov_count is None


def test_anchor_coordinates_are_range_checked():
    with pytest.raises(Exception):
        BTRSheetConfirm(truck_id=uuid.uuid4(), sheet_date=date.today(),
                        source="csv", amazon_anchor_lat=91.0)


# ── DSP validation (D6) ───────────────────────────────────────────────────────

def _company(db, slug: str, dsp_name=None) -> Company:
    c = Company(id=uuid.uuid4(), name=f"Co {slug}", slug=slug, is_active=True,
                amazon_dsp_name=dsp_name)
    db.add(c)
    db.commit()
    return c


def test_matching_dsp_passes(db):
    c = _company(db, "co-match", dsp_name="NYCD")
    assert _check_dsp(db, c.id, "NYCD") is None


def test_dsp_match_ignores_case_and_padding(db):
    c = _company(db, "co-case", dsp_name="nycd")
    assert _check_dsp(db, c.id, "  NYCD ") is None


def test_foreign_dsp_is_rejected(db):
    """The realistic mistake: photographing another DSP's sheet at a shared
    station. Importing it would attribute their totes to this company."""
    c = _company(db, "co-foreign", dsp_name="NYCD")
    msg = _check_dsp(db, c.id, "BOSD")
    assert msg is not None
    assert "another DSP's sheet" in msg


def test_unconfigured_dsp_name_is_not_a_free_pass(db):
    """With nothing configured we CANNOT validate. Treating that as a match
    would defeat the check for exactly the companies that never set it up."""
    c = _company(db, "co-unset", dsp_name=None)
    msg = _check_dsp(db, c.id, "NYCD")
    assert msg is not None
    assert "no Amazon DSP name is configured" in msg


def test_a_sheet_with_no_dsp_cell_is_not_blocked(db):
    """A cropped photo may miss the DSP cell entirely. That is unknown, not
    wrong — the reviewer still sees the sheet."""
    c = _company(db, "co-nodsp", dsp_name="NYCD")
    assert _check_dsp(db, c.id, None) is None


# ── preview shaping ───────────────────────────────────────────────────────────

_CSV = (
    "Route,Service Type,DSP,Anchor Point,Total Routes,"
    "Name,Package Count,Bag Count,OV Count,OV Sort Zones,Bag Labels\n"
    'BTR31,Box Truck Parcel (26ft) NYC,NYCD,40.75643 -73.99744,12,'
    'WE37,56,3,6,"A-27.2W | 2 A-27.3U | 2 A-28.2W | 1 A-27.3W | 1",'
    '"Green 5270, Green 7171, Orange 4772"\n'
)


def test_preview_output_carries_everything_a_reviewer_needs():
    out = _to_out(CSVBTRIngestor(_CSV).ingest())
    assert out.btr_loading_zone == "BTR31"
    assert out.dsp == "NYCD"
    assert out.total_bags == 3
    assert out.routes[0].amazon_route_name == "WE37"
    assert [b.bag_id for b in out.routes[0].bags] == ["5270", "7171", "4772"]
    # Each bag knows its Amazon route so a captain can cross-check Flex.
    assert out.routes[0].bags[0].amazon_route_name == "WE37"


def test_preview_surfaces_a_dsp_mismatch_without_refusing():
    """Preview SHOWS the problem; confirm is what refuses. A reviewer who cannot
    see the sheet cannot tell whether the mismatch is a typo or a wrong sheet."""
    out = _to_out(CSVBTRIngestor(_CSV).ingest(), dsp_mismatch="wrong DSP")
    assert out.dsp_mismatch == "wrong DSP"
    assert out.routes, "the sheet must still be visible"


def test_preview_endpoint_has_no_write_path():
    """D3, enforced structurally: parsing cannot persist, so an OCR read is
    physically incapable of reaching the database without a human."""
    import inspect
    from app.routers import btr_sheets

    src = inspect.getsource(btr_sheets.preview_btr_sheet)
    for writer in ("db.add", "db.commit", "db.flush", "db.delete"):
        assert writer not in src, f"preview must not call {writer}"


# ── persistence (dim 1 + cascade) ─────────────────────────────────────────────

def test_every_btr_model_carries_company_id_directly():
    """Reaching the tenant only through a join means a query starting from
    btr_bags has no filter and is one forgotten join from crossing companies."""
    for model in (BTRSheet, BTRRoute, BTRBag, BTROVZone):
        assert hasattr(model, "company_id"), f"{model.__name__} has no company_id"
        assert not model.company_id.nullable, f"{model.__name__}.company_id must be NOT NULL"


def test_children_cascade_so_a_replacement_leaves_no_orphans():
    """Re-importing a truck-day deletes the old sheet. Without cascade its bags
    would survive and be counted against the new one."""
    for col, table in (
        (BTRRoute.__table__.c.btr_sheet_id, "btr_sheets"),
        (BTRBag.__table__.c.btr_sheet_id, "btr_sheets"),
        (BTROVZone.__table__.c.btr_route_id, "btr_routes"),
    ):
        fk = list(col.foreign_keys)[0]
        assert fk.ondelete == "CASCADE", f"{col} must cascade"


def test_one_sheet_per_truck_per_day():
    """A second photo of the same sheet is a correction, not a second truck."""
    names = {c.name for c in BTRSheet.__table__.constraints}
    assert "uq_btr_sheets_truck_date" in names


def test_a_bag_is_unique_per_sheet():
    """Scoped to the sheet, not the route: the same physical tote cannot be on
    two Amazon routes, and the same id recurs across days and companies."""
    names = {c.name for c in BTRBag.__table__.constraints}
    assert "uq_btr_bags_sheet_bag" in names

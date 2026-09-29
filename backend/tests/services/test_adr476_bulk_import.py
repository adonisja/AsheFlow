"""A Transporter ID is the match; a name is how you bind it once (ADR-476).

ADR-475 fixed the scorecard vocabulary and left the workflow unusable -- "no one
wants to upload 50+ files one at a time". Amazon's DSP export is one row per
person per week, which is exactly this table's grain, so a week becomes one
upload.

The risk being designed against: a misrouted card is SILENT AND PERMANENT.
Someone sees a stranger's speeding events, and by the time anyone asks there is
no record of what the row said. A queue is an annoyance; a wrong match is a
data-integrity incident that also leaks one person's performance to another.
"""
import inspect
import re

import pytest

from app.models.employee import Employee
from app.models.scorecard_import import ScorecardImportPending
from app.routers import scorecards as SC
from app.services import scorecard_bulk as SB


# ── D1: the id is the match ─────────────────────────────────────────────────

def test_the_id_lives_on_the_employee_beside_the_adp_one():
    """Same pattern as hr_system_id_adp: an external id bound to the record
    once, then matched on forever."""
    cols = {c.name for c in Employee.__table__.columns}
    assert "transporter_id" in cols
    assert "hr_system_id_adp" in cols


def test_two_employees_cannot_hold_one_transporter_id():
    """An ambiguous id defeats the entire point of using one."""
    names = {c.name for c in Employee.__table__.constraints}
    assert "uq_employees_company_transporter" in names


def test_matching_is_an_exact_lookup_never_a_name_guess():
    """THE decision. A fuzzy match that is right 98% of the time misroutes one
    row in fifty, every week, silently."""
    src = inspect.getsource(SC.bulk_import_scorecards)
    code = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
    assert "bound.get(row.transporter_id)" in code
    assert "difflib" not in code, "the import path is guessing at names"


def test_the_roster_lookup_is_company_scoped():
    """Dimension 1. Matching across tenants would file another company's
    scorecard onto our employee."""
    src = inspect.getsource(SC.bulk_import_scorecards)
    assert "Employee.company_id == cid" in src


# ── D2: an unknown id is parked, not guessed ────────────────────────────────

def test_an_unknown_id_is_queued_with_its_payload():
    """Parked IN FULL so resolving it needs no re-upload."""
    src = inspect.getsource(SC.bulk_import_scorecards)
    assert "ScorecardImportPending(" in src
    assert 'outcome="queued"' in src


def test_the_queue_is_upserted_so_a_re_upload_corrects():
    """A second upload of the same file must correct, not pile up rows for the
    operator to wade through."""
    names = {c.name for c in ScorecardImportPending.__table__.constraints}
    assert "uq_scorecard_import_pending_week_transporter" in names


def test_suggestions_rank_but_never_select():
    """A suggestion orders the dropdown. The binding stays a human decision,
    because a wrong one is silent and permanent."""
    src = inspect.getsource(SC._rank_roster)
    assert "difflib" in src, "the suggestion should be ranked to be useful"

    bind = inspect.getsource(SC.bind_transporter_id)
    assert "_rank_roster" not in bind, "the binding auto-selects a suggestion"

    # Assert the QUERY filters on the caller's choice, not merely that the name
    # appears somewhere. A probe that removed the filter left the parameter in
    # the signature, so a presence check passed while the endpoint had started
    # picking an arbitrary employee.
    lookup = bind.split("db.query(Employee)", 1)[1].split(".first()", 1)[0]
    assert "Employee.id == payload.employee_id" in lookup, (
        "the employee is not looked up by the id the caller chose"
    )


def test_only_unbound_employees_are_suggested():
    """Offering someone who already carries an id invites the double-binding
    the unique constraint refuses."""
    src = inspect.getsource(SC.list_pending_bindings)
    assert "Employee.transporter_id.is_(None)" in src


def test_one_binding_releases_every_parked_week():
    """An id unseen for six weeks is six parked rows and ONE decision. This is
    what keeps week one survivable."""
    src = inspect.getsource(SC.bind_transporter_id)
    assert "ScorecardImportPending.transporter_id == payload.transporter_id" in src
    assert "db.delete(row)" in src


def test_rebinding_an_id_is_refused():
    """Silently moving a binding re-files somebody's history onto a different
    person -- the exact misroute this design refuses."""
    src = inspect.getsource(SC.bind_transporter_id)

    # TWO distinct guards, and a probe that disabled one left the other's text
    # in place -- so asserting on the message passed while rebinding was
    # allowed. Assert both conditions exist.
    assert "if emp.transporter_id and emp.transporter_id != payload.transporter_id:" in src, (
        "an employee can be silently moved to a different Transporter ID"
    )
    assert "if clash:" in src, (
        "a Transporter ID can be silently taken from another employee"
    )
    assert src.count("status_code=409") >= 2, "one of the two refusals is gone"


# ── D3: nothing ambiguous auto-saves ────────────────────────────────────────

def test_a_name_mismatch_imports_and_flags():
    """A bound id is authoritative -- Amazon issued it -- so the scorecard is
    not withheld. But a changed name usually means a rehire or a reassigned id,
    and accepting it silently is how a card lands on the wrong person
    permanently."""
    src = inspect.getsource(SC.bulk_import_scorecards)
    assert 'outcome="name_mismatch"' in src
    assert "out.imported += 1" in src


def test_name_comparison_is_order_insensitive():
    """Amazon writes "Doe, Jane" where we hold "Jane Doe". Comparing raw would
    flag every row and train the operator to ignore the flag."""
    assert SC._norm_name("Doe, Jane") == SC._norm_name("Jane Doe")
    assert SC._norm_name("Jane  Doe ") == SC._norm_name("Jane Doe")
    assert SC._norm_name("John Doe") != SC._norm_name("Jane Doe")


# ── D4/D5: per-row results, week from the row ───────────────────────────────

def test_one_bad_row_does_not_fail_the_file():
    src = inspect.getsource(SC.bulk_import_scorecards)
    assert "out.rows.append" in src
    assert "continue" in src


def test_the_row_count_is_capped():
    assert SC.MAX_BULK_ROWS > 0
    src = inspect.getsource(SC.bulk_import_scorecards)
    assert "MAX_BULK_ROWS" in src


def test_the_week_comes_from_the_row_not_the_filename():
    """The file is named "Trailing Six Week" while Amazon exports weekly, so
    trusting the filename would write one week's numbers under another week's
    label -- an error nobody catches, because the numbers look plausible."""
    src = inspect.getsource(SB.parse_export)
    assert 'cell("week")' in src
    write = inspect.getsource(SC._write_individual_scorecard)
    assert "Scorecard.week == row.week" in write


def test_a_row_with_no_week_is_an_error_not_a_guess():
    src = inspect.getsource(SC.bulk_import_scorecards)
    assert "if not row.week:" in src
    assert 'outcome="error"' in src


# ── D6: headers are normalised ──────────────────────────────────────────────

def test_a_trailing_space_on_the_identity_column_still_maps():
    """"Delivery Associate " carries the person's name and the space is
    invisible on screen."""
    assert SB._norm("Delivery Associate ") == "delivery associate"


def test_the_irregular_slash_spacing_still_maps():
    assert SB._norm("Sign/ Signal Violations Rate (per trip)") in SB._VALUE_COLUMNS


def test_every_mapped_key_is_a_registry_key():
    from app.services.company_config import METRIC_SHAPES

    unknown = sorted(
        set(SB._VALUE_COLUMNS.values()) - set(METRIC_SHAPES) - {"packages_delivered"}
    )
    assert not unknown, f"export keys not in the registry: {unknown}"


def test_an_unrecognised_header_is_reported():
    """A silently unmapped column is ADR-475's dropped row in a new place, and
    this is how a changed export announces itself."""
    csv = "Week,Transporter ID,Mystery Column\n2026-W38,ABC123,7\n"
    parsed = SB.parse_export(csv.encode())
    assert "Mystery Column" in parsed.unknown_headers


def test_the_tier_column_name_is_not_derived():
    """"Speeding Event Rate (per trip)" pairs with "Speeding Event Rate Tier" --
    the suffix is DROPPED -- and "DSB" pairs with "DSB DPMO Tier", which ADDS a
    word. Deriving f"{value} tier" looks obviously right and silently returned
    None for every rate tier."""
    assert SB._tier_header("speeding event rate (per trip)") == "speeding event rate tier"
    assert SB._tier_header("dsb") == "dsb dpmo tier"
    assert SB._tier_header("pod") == "pod tier"


# ── D7: absence in either spelling ──────────────────────────────────────────

def test_the_export_spells_absence_as_an_empty_string():
    """The card UI writes "No Data"; the export writes "". Same meaning, and
    both must resolve to absent rather than to zero."""
    assert SB.parse_value("") == (None, None)
    assert SB.parse_value("No Data") == (None, None)


def test_a_zero_is_a_real_measurement():
    """A zero seatbelt rate is PERFECT. Treating absence as zero makes an
    unmeasured walker look flawless."""
    assert SB.parse_value("0")[0] == 0.0
    assert SB.parse_value("0.0")[0] == 0.0


def test_a_percentage_is_parsed_with_its_unit():
    assert SB.parse_value("100.0%") == (100.0, "%")


def test_an_absent_value_is_stored_as_the_marker_not_zero():
    src = inspect.getsource(SC._write_individual_scorecard)
    assert "NO_DATA_VALUE" in src


def test_a_row_with_no_transporter_id_is_counted_not_dropped():
    csv = "Week,Transporter ID\n2026-W38,\n2026-W38,ABC123\n"
    parsed = SB.parse_export(csv.encode())
    assert parsed.skipped_no_id == 1
    assert len(parsed.rows) == 1


# ── the write is audited ────────────────────────────────────────────────────

def test_both_writes_are_audited():
    for fn, action in ((SC.bulk_import_scorecards, "scorecard.bulk_import"),
                       (SC.bind_transporter_id, "scorecard.transporter_bound")):
        assert f'action_type="{action}"' in inspect.getsource(fn)


# ── the client surface (ADR-381: an endpoint with no caller is not shipped) ──

import pathlib as _pathlib

_ROOT = _pathlib.Path(__file__).resolve().parents[3]
BULK_UI = _ROOT / "frontend/src/components/ScorecardBulkImport.tsx"
ENTRY_UI = _ROOT / "frontend/src/pages/ScorecardEntry.tsx"
TYPES = _ROOT / "frontend/src/api/types.ts"


def test_all_three_endpoints_have_callers():
    """ADR-381's failure, repeatedly in this codebase: a live endpoint, a clean
    build, and nothing calling it."""
    src = BULK_UI.read_text()
    for path in ("'/scorecards/bulk-import'",
                 "'/scorecards/pending-bindings'",
                 "'/scorecards/pending-bindings/bind'"):
        assert path in src, f"no caller for {path}"


def test_the_importer_is_mounted():
    """A component nothing renders is the same failure one layer in."""
    src = ENTRY_UI.read_text()
    assert "<ScorecardBulkImport />" in src


def test_bulk_is_offered_before_single_entry():
    """One export covers a whole week, so bulk is the normal path. Putting the
    single form first would make the exception look like the workflow."""
    src = ENTRY_UI.read_text()
    assert src.index("<ScorecardBulkImport />") < src.index("Enter one scorecard")


def test_the_dropdown_does_not_preselect():
    """The suggestion orders the list; the operator chooses. A pre-selected
    'best match' is a fuzzy match wearing a dropdown -- one careless Save and
    the misroute is permanent."""
    src = BULK_UI.read_text()
    assert "value={choice[p.transporter_id] ?? ''}" in src
    assert 'placeholder="Select the person…"' in src


def test_it_uses_the_house_dropdown_not_a_native_select():
    """ui/SelectMenu exists because a native select renders differently on every
    platform and cannot show a per-option hint. The hint is the ROLE here, which
    is what separates two people with similar names -- exactly the case this
    queue exists to get right."""
    src = BULK_UI.read_text()
    assert "SelectMenu" in src
    # Strip JSX comments: the explanation NAMES the native element it replaced,
    # and matching on prose rather than markup failed this test against correct
    # code -- the same slip as ADR-473's `le=100` and ADR-475's `_LOWER_IS_BETTER`.
    markup = re.sub(r"\{/\*.*?\*/\}", "", src, flags=re.S)
    assert "<select" not in markup, "a raw select bypasses the design system"
    assert "hint: s.role" in src, "the role hint is what disambiguates names"


def test_it_uses_the_house_drop_zone():
    """Dragging the export off a download folder is the natural gesture, and a
    bare button does not invite it. Mirrors components/BulkImportModal."""
    src = BULK_UI.read_text()
    assert "onDragOver" in src and "onDrop" in src
    assert "border-dashed" in src


def test_the_expected_columns_are_stated_before_upload():
    """An export whose columns changed should be recognisable as wrong BEFORE
    it is uploaded, not only from the unknown-header report after."""
    src = BULK_UI.read_text()
    assert "Expected columns" in src
    assert "Transporter ID" in src


def test_bind_is_disabled_until_someone_is_chosen():
    src = BULK_UI.read_text()
    assert "disabled={!choice[p.transporter_id]" in src


def test_unknown_headers_are_surfaced_to_the_operator():
    """This is how a changed export announces itself instead of quietly losing
    a column."""
    src = BULK_UI.read_text()
    assert "unknown_headers.length > 0" in src
    assert "did not recognise" in src


def test_only_rows_needing_attention_are_listed():
    """A list of every successful row is noise on a file of eighty, and noise is
    how the three rows that matter get missed."""
    src = BULK_UI.read_text()
    assert "r.outcome !== 'imported'" in src


def test_the_file_input_clears_so_the_same_file_can_be_re_uploaded():
    """Re-uploading after fixing bindings is the normal path; without this the
    second attempt fires no change event and looks broken."""
    src = BULK_UI.read_text()
    assert "e.target.value = ''" in src


def test_the_ts_types_mirror_the_response():
    from app.routers.scorecards import BulkImportResult, BulkRowResult

    ts = TYPES.read_text()
    for model, name in ((BulkImportResult, "BulkImportResult"),
                        (BulkRowResult, "BulkRowResult")):
        block = ts.split(f"export interface {name} {{", 1)[1].split("}", 1)[0]
        for field in model.model_fields:
            assert field in block, f"{name}.{field} missing from types.ts"

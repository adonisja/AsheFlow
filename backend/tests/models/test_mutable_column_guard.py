"""Guard: every ARRAY/JSONB column is a conscious decision (ADR-247).

A column holding a mutable container has two valid states:

  * wrapped in MutableList/MutableDict  -> in-place mutation persists
  * left unwrapped                      -> in-place mutation is SILENTLY
                                           DISCARDED, so the column must only
                                           ever be reassigned

Both are defensible. What is not defensible is arriving at one by accident,
which is what happened to `Route.tote_ids` and cost us a duplicated tote across
two routes (ADR-247, ADR-213).

This test fails when a mutable-typed column appears that is neither wrapped nor
listed in REASSIGN_ONLY below. It cannot be satisfied by ignoring it — the
author has to pick. Adding a name to REASSIGN_ONLY is a real choice and should
come with the reasoning in the same PR.

Note that this pins the *declaration*, not the call sites. Nothing here stops
someone writing `obj.unwrapped_col.append(x)`; see the AST scan in the ADR-247
journal for that sweep. This guard exists because the declaration is the point
where the decision is cheap and reviewable.
"""
import importlib
import pkgutil

import pytest
from sqlalchemy import ARRAY
from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY, JSON, JSONB
from sqlalchemy.ext.mutable import MutableDict, MutableList

import app.models as models_pkg
from app.models.base import Base

MUTABLE_TYPES = (ARRAY, PG_ARRAY, JSONB, JSON)

# Columns deliberately left unwrapped: they are written by whole-value
# assignment only, so mutation tracking would buy nothing but a deep copy on
# every load. Format: "Model.column": why.
REASSIGN_ONLY = {
    # ADR-263. Set at seed time and replaced wholesale on re-seed
    # (seed_training_curriculum.py assigns `exists.roles = list(roles)`), never
    # appended to. A curriculum item's track membership is restated from the
    # seed data as a unit, so there is no in-place-mutation path to lose.
    "TrainingCurriculum.roles":             "seed-managed; assigned as a whole list",
    # ADR-264 D10. Same shape as TrainingCurriculum.roles above: a question's
    # TRACK membership is a property of the question, restated as a unit rather
    # than appended to. Verified at authoring time: no write path mutates a
    # roles list in place anywhere in app/ (`grep -rn "\.roles\.append"` is
    # empty), and quiz templates have no in-app create/update endpoint yet — if
    # one is added, assign the whole list.
    "GraduationQuizTemplate.roles":         "track membership; assigned as a whole list",

    # ADR-273 sort telemetry. Every one of these is a histogram computed in a
    # single pass (compute_sort_metrics / roll_up_company_day) and assigned as a
    # whole dict. RouteSortRun is append-only by design — a re-sort writes a new
    # row rather than editing one — so its columns have no mutation path at all.
    # RouteSortDaily is refreshed by re-running the rollup for a date, which
    # likewise reassigns the whole dict.
    "RouteSortRun.block_group_sizes":       "computed once per run; run rows are never edited",
    "RouteSortRun.blocks_per_route_hist":   "computed once per run; run rows are never edited",
    "RouteSortRun.closed_reason_hist":      "computed once per run; run rows are never edited",
    "RouteSortDaily.blocks_per_route_hist": "assigned wholesale by the nightly rollup",
    "RouteSortDaily.by_effort_class":       "assigned wholesale by the nightly rollup",

    # Write-once payload snapshots — captured at creation, never edited.
    "ADPTimeCard.raw_payload":              "immutable API capture",
    "TimeCardAdjustment.adp_response_payload": "immutable API capture",
    "AuditLog.before_snapshot":             "immutable by definition — audit record",
    "AuditLog.after_snapshot":              "immutable by definition — audit record",

    # Config / definition data, replaced wholesale on edit.
    "BuildingProfile.days_open":            "replaced wholesale on profile edit",
    "BuildingProfileLibrary.days_open":     "replaced wholesale on promotion",
    "BuildingProfileLibrary.promoted_from_company_ids": "append via reassignment in promotion path",
    "CompanyZone.bounds":                   "polygon replaced wholesale",
    "GraduationQuizTemplate.choices":       "template definition, replaced on edit",
    "GraduationQuizTemplate.keywords":      "template definition, replaced on edit",

    # Computed outputs — built in memory, assigned once at persist time.
    "GraduationQuiz.weak_topics":           "computed at grading, assigned once",
    "LoadConfirmation.short_bag_ids":       "computed at confirmation, assigned once",
    "RTSReport.rts_packages":               "computed at report build, assigned once",
    "RouteHandoff.rts_package_ids":         "computed at handoff, assigned once",
    "StationArrival.missing_items":         "computed at arrival check, assigned once",
    "VehicleInspection.items":              "submitted as a whole form",
    "TruckZone.package_tbas":               "written by persist_zones as a whole",
    "TruckZone.tote_roster":                "written by persist_zones as a whole",
    "TruckZone.truck_polygon":              "written by persist_zones as a whole",
    "DeliveryStop.tba_numbers":             "set at stop creation, replaced on merge",
    "PackageRemoval.tba_numbers":           "set at removal creation",
    "ScorecardAppealItem.evidence":          "set at item creation, replaced on edit",
    "ScheduleChangeRequest.days_to_add":    "set at request creation",
    "ScheduleChangeRequest.days_to_drop":   "set at request creation",
    "ScheduleChangeRequest.proposed_schedule": "set at request creation",
}


def _load_all_models():
    for _, name, _ in pkgutil.iter_modules(models_pkg.__path__):
        try:
            importlib.import_module(f"app.models.{name}")
        except Exception:  # pragma: no cover - proprietary modules may be absent
            pass


def _mutable_columns():
    _load_all_models()
    seen, out = set(), []
    for mapper in Base.registry.mappers:
        table = mapper.local_table
        if table is None:
            continue
        for col in table.columns:
            if not isinstance(col.type, MUTABLE_TYPES):
                continue
            key = f"{mapper.class_.__name__}.{col.key}"
            if key in seen:
                continue
            seen.add(key)
            out.append((key, col.type, _is_tracked(mapper.class_, col.key), None))
    return out


def _is_tracked(cls, col_key):
    """Is this column wrapped in MutableList/MutableDict?

    Checked behaviourally, by assigning and seeing what the value coerces to.
    There is no marker to inspect: `as_mutable()` returns the *same* type
    object and attaches tracking to the mapped attribute instead, so
    `Column.type` looks identical wrapped or not (verified — a wrapped and an
    unwrapped ARRAY expose no differing attribute). Reading the type would
    report every column as unwrapped and this guard would pass vacuously.

    Construct via `cls()` rather than `cls.__new__(cls)`: the latter skips the
    instrumented `__init__`, so the coercion never runs and every column reads
    as unwrapped. Declarative models take no required constructor args, so
    `cls()` is safe here.
    """
    try:
        probe = cls()
        setattr(probe, col_key, [])
        return isinstance(getattr(probe, col_key), (MutableList, MutableDict))
    except Exception:
        return False


def test_every_mutable_column_is_wrapped_or_declared_reassign_only():
    undeclared = []
    for key, _type, wrapped, _attr in _mutable_columns():
        if not wrapped and key not in REASSIGN_ONLY:
            undeclared.append(key)

    assert not undeclared, (
        "These ARRAY/JSONB columns are neither wrapped in MutableList/MutableDict "
        "nor declared reassign-only:\n\n  "
        + "\n  ".join(sorted(undeclared))
        + "\n\nIn-place mutation (.append/.pop/[i]=x) on an unwrapped column is "
          "SILENTLY DISCARDED — no error, and a read in the same session still "
          "shows the change (ADR-247).\n\nEither:\n"
          "  1. wrap it:  Column(MutableList.as_mutable(ARRAY(Text())), ...)\n"
          "  2. or add it to REASSIGN_ONLY in this file with the reason, and only "
          "ever assign the column as a whole."
    )


def test_reassign_only_list_has_no_stale_entries():
    """A declared column that no longer exists means the list is drifting."""
    live = {key for key, _t, _w, _a in _mutable_columns()}
    stale = sorted(set(REASSIGN_ONLY) - live)
    assert not stale, (
        "REASSIGN_ONLY names columns that no longer exist — remove them so the "
        "list keeps describing the schema:\n  " + "\n  ".join(stale)
    )


@pytest.mark.parametrize("col", ["tote_ids", "tba_numbers", "block_keys",
                                 "normalised_addresses", "stops"])
def test_route_columns_are_tracked(col):
    """Route is the one model where mutation must persist — a live bug proved
    the cost of it not doing so (ADR-247). Pinned by name so removing a wrapper
    fails loudly rather than silently reopening the trap."""
    from sqlalchemy.ext.mutable import MutableList

    from app.models.walker_route import Route

    r = Route()
    setattr(r, col, [])
    assert isinstance(getattr(r, col), MutableList), (
        f"Route.{col} did not coerce to MutableList — the as_mutable() wrapper "
        f"was removed and in-place mutation is being discarded again."
    )

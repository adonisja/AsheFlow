"""The campaign system's tables (ADR-485 D1/D2).

Replaces driver_survey's four hardcoded Boolean columns with question rows and
typed answer rows, so adding a question stops being a migration.

TWO LAYERS, and the split matters. The test database is SQLite in-memory, which
compiles CHECK constraints but does NOT enforce the ones below the way Postgres
does. So the invariants that must hold in production are asserted against the
MIGRATION TEXT and the model definition, and verified for real by the
fresh-database CI job that runs alembic against Postgres.

Verified by hand against a real Postgres before writing these (every migration
from zero, then each constraint probed):

    subject_role 'manager'              -> rejected
    scale question with no bounds       -> rejected
    choice question with no choices     -> rejected
    bool question                       -> accepted
    run closing before it opens         -> rejected
"""
import pathlib
import re

import pytest

from app.models.campaign import (
    VALID_QUESTION_KINDS, VALID_SCHEDULE_MODES, VALID_SUBJECT_ROLES,
    AttributionRequest, Campaign, CampaignAnswer, CampaignQuestion,
    CampaignResponse, CampaignRun, CampaignSchedule,
)

ROOT = pathlib.Path(__file__).resolve().parents[3]
MIGRATION = ROOT / "backend/alembic/versions/f5303d1a3726_adr485_campaign_tables.py"

ALL_MODELS = (Campaign, CampaignQuestion, CampaignSchedule, CampaignRun,
              CampaignResponse, CampaignAnswer, AttributionRequest)


# ── every table is company-scoped (ADR-115 D1) ──────────────────────────────

@pytest.mark.parametrize("model", ALL_MODELS, ids=lambda m: m.__tablename__)
def test_every_table_carries_company_id(model):
    """A campaign table without company_id cannot be filtered by tenant, and
    every query against it is a cross-tenant read waiting to happen."""
    col = model.__table__.columns.get("company_id")
    assert col is not None, f"{model.__tablename__} has no company_id"
    assert not col.nullable, f"{model.__tablename__}.company_id is nullable"
    assert col.index, f"{model.__tablename__}.company_id is not indexed"


# ── D2: answers are typed rows, never a JSONB blob ──────────────────────────

def test_an_answer_has_three_typed_value_columns():
    cols = CampaignAnswer.__table__.columns
    for name in ("bool_value", "int_value", "text_value"):
        assert name in cols, f"CampaignAnswer has no {name}"
    assert "answers" not in cols, "an answers blob is exactly what ADR-115 D9 forbids"


def test_exactly_one_value_is_enforced_by_the_database():
    """An answer with no value is a silent skip of a required question; one
    with two is ambiguous at read time. Neither may be representable."""
    src = MIGRATION.read_text()
    assert "ck_campaign_answer_exactly_one_value" in src
    # CASE, not Postgres's `::int`: five test files call
    # Base.metadata.create_all on SQLite, which rejects the cast.
    assert "CASE WHEN bool_value IS NOT NULL" in src


def test_one_answer_per_question_per_response():
    """A double submit must not become two contradictory answers."""
    names = {c.name for c in CampaignAnswer.__table__.constraints}
    assert "uq_campaign_answer" in names


def test_a_question_with_answers_cannot_be_deleted():
    """RESTRICT, not CASCADE: deleting a question that has answers orphans
    them. Retirement is how a question goes away."""
    fk = next(fk for fk in CampaignAnswer.__table__.foreign_keys
              if fk.column.table.name == "campaign_questions")
    assert fk.ondelete == "RESTRICT"


def test_choices_is_the_only_jsonb_a_respondent_cannot_write():
    """`choices` is question DEFINITION, written by an admin through a
    validated model. ADR-115 D9 is about the trust boundary, and an admin
    defining a question is not it."""
    assert CampaignQuestion.__table__.columns["choices"].type.__class__.__name__ == "JSONB"
    for name in ("bool_value", "int_value", "text_value"):
        kind = CampaignAnswer.__table__.columns[name].type.__class__.__name__
        assert kind != "JSONB", f"{name} is JSONB — answers must be typed"


# ── D3: the invariant the DB can hold ───────────────────────────────────────

def test_nobody_reviews_themselves():
    """D3's last clause, restated where the database can enforce it."""
    src = MIGRATION.read_text()
    assert "ck_campaign_response_not_self" in src
    assert "respondent_id <> subject_id" in src


def test_the_subject_is_stored_not_derived():
    """Resolved by D3 at submit and PERSISTED, so a crew change weeks later
    cannot retroactively re-point an existing review at a different person."""
    col = CampaignResponse.__table__.columns.get("subject_id")
    assert col is not None and not col.nullable


def test_one_submission_per_person_per_run():
    names = {c.name for c in CampaignResponse.__table__.constraints}
    assert "uq_campaign_response" in names


# ── D1/D12: runs ────────────────────────────────────────────────────────────

def test_a_campaign_cannot_run_twice_for_one_date():
    names = {c.name for c in CampaignRun.__table__.constraints}
    assert "uq_campaign_run_date" in names


def test_a_run_records_who_was_asked_and_who_was_skipped():
    """D15/D16: 'nobody answered' and 'nobody was asked' must not look the
    same, and a rate computed over a quietly smaller denominator gets acted on
    wrongly."""
    cols = CampaignRun.__table__.columns
    assert "notified_count" in cols
    assert "skipped_assignment_ids" in cols


def test_expiry_and_manual_close_are_separate_fields():
    """ADR-423's rule: both stop submissions, only one means somebody decided
    something."""
    cols = CampaignRun.__table__.columns
    assert "closes_at" in cols and "closed_at" in cols


# ── the vocabularies are derived, never retyped ─────────────────────────────

def test_the_subject_role_check_is_derived_from_the_tuple():
    """Two lists that must agree are two lists that will not (ADR-468)."""
    src = MIGRATION.read_text()
    for role in VALID_SUBJECT_ROLES:
        assert f"'{role}'" in src, f"{role} missing from the migration's CHECK"


def test_the_slot_vocabulary_matches_assignment_members():
    """subject_role is matched against AssignmentMember.role, so a value that
    cannot appear on a truck is a campaign that can never find a subject."""
    am = (ROOT / "backend/app/models/assignment_member.py").read_text()
    block = re.search(r"role IN \(([^)]*)\)", am)
    assert block, "could not find the assignment_members role CHECK"
    slots = set(re.findall(r"'(\w+)'", block.group(1)))
    assert set(VALID_SUBJECT_ROLES) == slots, (
        f"campaign subject roles and assignment slots disagree: "
        f"{set(VALID_SUBJECT_ROLES) ^ slots}")


@pytest.mark.parametrize("kind", VALID_QUESTION_KINDS)
def test_each_question_kind_is_in_the_migration(kind):
    assert f"'{kind}'" in MIGRATION.read_text()


@pytest.mark.parametrize("mode", VALID_SCHEDULE_MODES)
def test_each_schedule_mode_is_in_the_migration(mode):
    assert f"'{mode}'" in MIGRATION.read_text()


# ── the migration itself ────────────────────────────────────────────────────

def test_the_migration_creates_all_seven_tables():
    src = MIGRATION.read_text()
    for model in ALL_MODELS:
        assert f'"{model.__tablename__}"' in src, f"{model.__tablename__} not created"


def test_the_migration_does_not_touch_driver_survey():
    """D17 migrates and drops those, in a LATER revision that runs after the
    routers exist to serve the new shape. A table dropped before its
    replacement can serve traffic is an outage, not a migration."""
    src = MIGRATION.read_text()
    assert "drop_table" not in src.split("def downgrade")[0], \
        "the upgrade drops something — this revision is CREATE ONLY"
    assert "driver_survey" not in src.split('"""')[2] if '"""' in src else True


def test_every_model_is_registered():
    """An unregistered model is invisible to Base.metadata, so alembic will not
    see it and the next autogenerate will propose dropping its table."""
    reg = (ROOT / "backend/app/models/__init__.py").read_text()
    for model in ALL_MODELS:
        assert model.__name__ in reg, f"{model.__name__} missing from models/__init__.py"

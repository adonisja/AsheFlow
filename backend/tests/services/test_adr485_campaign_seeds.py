"""The built-in campaigns (ADR-485 D8).

Driver and captain ship as ORDINARY Campaign rows differing only in
subject_role. The property that matters is that nothing in the engine knows
their names: a special-cased built-in is a second code path that drifts from
the one admins use, and the one admins use is the one that gets tested.
"""
import ast
import inspect
import pathlib
import re
import textwrap

import pytest

from app.models.campaign import VALID_QUESTION_KINDS, VALID_SUBJECT_ROLES
from app.services import campaign_seeds as S

ROOT = pathlib.Path(__file__).resolve().parents[3]
MIGRATION = next(
    (ROOT / "backend/alembic/versions").glob("*adr485_seed_builtin_campaigns.py"))


def _code(fn) -> str:
    """Source with docstrings removed — a docstring explaining a rule is not
    an implementation of it (six prose-not-code false matches this session)."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.Module)) \
                and ast.get_docstring(node):
            node.body = node.body[1:]
    return ast.unparse(tree)


# ── the seeds are ordinary campaigns ────────────────────────────────────────

def _module_code(path: pathlib.Path) -> str:
    """A whole module with every docstring and comment stripped.

    The first version of the test below read the raw file and failed on a
    DOCSTRING that quotes "Driver Survey" while explaining why the UI must show
    a date beside it. That is prose about the rule, not an implementation of a
    special case — the seventh prose-not-code false match in this work.
    """
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef, ast.Module)) and ast.get_docstring(node):
            node.body = node.body[1:]
    return ast.unparse(tree)   # ast.unparse never emits comments


def test_nothing_in_the_engine_knows_their_names():
    """THE property. A built-in that the router special-cases is a second code
    path; a tenant deleting both must lose no functionality."""
    for path in ("backend/app/routers/campaigns.py",
                 "backend/app/services/campaign_scope.py",
                 "backend/app/services/campaign_results.py"):
        src = _module_code(ROOT / path)
        for label in ("Driver Survey", "Captain Survey"):
            assert label not in src, f"{path} special-cases '{label}' in CODE"


@pytest.mark.parametrize("spec", S.BUILT_IN_CAMPAIGNS, ids=lambda s: s.label)
def test_each_seed_uses_a_real_assignment_slot(spec):
    """subject_role is matched against AssignmentMember.role, so a value that
    cannot appear on a truck is a campaign that can never find a subject."""
    assert spec.subject_role in VALID_SUBJECT_ROLES


@pytest.mark.parametrize("spec", S.BUILT_IN_CAMPAIGNS, ids=lambda s: s.label)
def test_every_seeded_question_has_a_valid_kind(spec):
    for q in spec.questions:
        assert q.kind in VALID_QUESTION_KINDS, f"{q.prompt!r} has kind {q.kind!r}"


@pytest.mark.parametrize("spec", S.BUILT_IN_CAMPAIGNS, ids=lambda s: s.label)
def test_no_seeded_question_needs_bounds_it_does_not_carry(spec):
    """A scale needs min/max and a choice needs options; the DB rejects either
    without them. The seeds use only bool and text, so none applies — this
    pins that, because adding a scale seed without bounds would fail at
    company creation, which is the worst place to find out."""
    for q in spec.questions:
        assert q.kind in ("bool", "text"), (
            f"{q.prompt!r} is a {q.kind} — it needs bounds or options, and "
            "SeedQuestion carries neither")


def test_the_optional_question_is_the_only_optional_one():
    """A required free-text field means a walker who has nothing to add cannot
    submit at all."""
    for spec in S.BUILT_IN_CAMPAIGNS:
        optional = [q for q in spec.questions if not q.required]
        assert len(optional) == 1 and optional[0].kind == "text"


# ── the two sets are genuinely different ────────────────────────────────────

def test_the_captain_set_is_not_the_driver_set_reworded():
    """ADR-256: a captain leads the route on foot and a driver drives it, so
    "were the routes organised" asked about a captain is a question about
    somebody else's job."""
    driver = {q.prompt for q in S.DRIVER_CAMPAIGN.questions}
    captain = {q.prompt for q in S.CAPTAIN_CAMPAIGN.questions}
    shared = driver & captain
    assert shared == {"Anything else? (optional)"}, shared


def test_the_captain_set_asks_about_correctness_and_fairness_separately():
    """A route can be built correctly and split unfairly, or shared evenly and
    still be wrong underfoot — different remedies, so different questions.
    Correctness has to be asked because in workforce mode there is no manifest
    (ADR-291) and the system holds no independent ground truth."""
    prompts = [q.prompt for q in S.CAPTAIN_CAMPAIGN.questions]
    assert any("blocks next to each other" in p for p in prompts), "no correctness question"
    assert any("distributed fairly" in p for p in prompts), "no fairness question"


def test_no_seeded_question_uses_retired_wave_vocabulary():
    """wave_number named a truck-wide re-issue counter rather than a wave; a
    walker's first re-issue could read as wave 3."""
    for spec in S.BUILT_IN_CAMPAIGNS:
        for q in spec.questions:
            assert "wave" not in q.prompt.lower(), q.prompt


# ── seeding behaviour ───────────────────────────────────────────────────────

def test_it_is_idempotent_by_subject_role_not_label():
    """A tenant who renames "Driver Survey" has one driver campaign, and
    re-running must not give them a second."""
    src = _code(S.seed_campaigns_for)
    assert "Campaign.subject_role == spec.subject_role" in src
    assert "Campaign.label" not in src


def test_it_does_not_commit():
    """The caller owns the transaction: a half-created company with campaigns
    but no config is worse than one with neither."""
    src = _code(S.seed_campaigns_for)
    assert "db.commit()" not in src


def test_company_creation_seeds_them():
    src = (ROOT / "backend/app/routers/companies.py").read_text()
    assert "seed_campaigns_for(db, company.id" in src


# ── the backfill migration ──────────────────────────────────────────────────

def test_the_migration_duplicates_the_text_rather_than_importing_it():
    """A migration that imports live code breaks when that code is renamed
    (ADR-427), and these rows are a historical fact about what was seeded."""
    src = MIGRATION.read_text()
    assert "from app." not in re.sub(r'"""[\s\S]*?"""', "", src, count=1)


def test_the_migration_seeds_the_same_questions_as_the_service():
    """Duplicated text that silently diverges is worse than an import."""
    src = MIGRATION.read_text()
    for spec in S.BUILT_IN_CAMPAIGNS:
        for q in spec.questions:
            assert q.prompt in src, f"migration is missing: {q.prompt!r}"


def test_the_migration_is_idempotent():
    src = MIGRATION.read_text()
    assert "AND subject_role = :r" in src and "if exists:" in src


def test_the_downgrade_spares_a_campaign_the_tenant_has_used():
    """A tenant who ran or edited it has made it theirs, and ON DELETE CASCADE
    would take the questions, the runs and every response with it.

    Verified against a real Postgres: a campaign with a run and a campaign with
    an extra question both survived the downgrade."""
    body = MIGRATION.read_text().split("def downgrade")[1]
    assert "NOT EXISTS" in body and "campaign_runs" in body
    assert "count(*) FROM campaign_questions" in body

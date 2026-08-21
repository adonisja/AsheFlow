"""Every table a migration touches must exist in the ORM metadata.

WHY THIS EXISTS. Migration ff90779895f6 added `discord_role_trainer` to `companies`.
The discord_* columns live on `company_configs`. On Postgres the migration would have
failed with "column discord_role_captain does not exist" — but nothing caught it,
because the test suite builds SQLite tables from `Base.metadata` and never executes a
migration. A green suite says nothing about whether the migration chain runs.

This is the cheap half of that gap: it cannot prove a migration is correct, but it
catches a table name that does not exist at all — the typo, the wrong-table paste,
the singular/plural slip. Running the real chain against Postgres is the other half
and is not something a unit test can do.
"""
import pathlib
import re

import pytest

from app.models.base import Base
# Import the models package so every table registers on Base.metadata.
import app.models  # noqa: F401


VERSIONS_DIR = pathlib.Path(__file__).resolve().parents[2] / "alembic" / "versions"

# Tables created by a migration and then dropped, or belonging to a model that no
# longer exists. A name here is an assertion that its absence from the ORM is known.
_KNOWN_ABSENT: set[str] = {
    "alembic_version",
    # Renamed after these migrations were written. The old migrations still say the
    # old name, which is CORRECT — a migration describes the schema at its own point
    # in history and must not be rewritten to match a later model.
    "location_profiles",        # -> building_profiles
    "location_profile_library", # -> building_profile_library
    "walker_routes",            # -> routes (ADR-212 era)
    "adp_timecard_segments",    # dropped; no surviving model
}

# Ops whose FIRST positional argument is the table name. Deliberately narrow:
# drop_constraint / create_check_constraint / create_index take the CONSTRAINT or
# INDEX name first and the table second, so including them here reads a constraint
# name as a table and produces noise instead of signal.
_TABLE_FIRST_RE = re.compile(
    r'op\.(?:add_column|drop_column|alter_column)\(\s*\n?\s*["\']([^"\']+)["\']'
)
# Ops that name the table as a keyword or as the SECOND positional argument.
_TABLE_KWARG_RE = re.compile(r'table_name=["\']([^"\']+)["\']')
_TABLE_SECOND_RE = re.compile(
    r'op\.(?:drop_constraint|create_check_constraint|create_unique_constraint|'
    r'create_foreign_key)\(\s*\n?\s*["\'][^"\']+["\'],\s*\n?\s*["\']([^"\']+)["\']'
)


def _migration_files():
    return sorted(p for p in VERSIONS_DIR.glob("*.py") if not p.name.startswith("__"))


def _tables_touched(src: str) -> set[str]:
    """Tables named as the FIRST argument to a column/constraint-level op.

    `op.create_table` is excluded on purpose — it defines a table that may legitimately
    not be in the ORM yet at that point in history. What matters here is an op that
    ASSUMES a table already exists.
    """
    return (
        set(_TABLE_FIRST_RE.findall(src))
        | set(_TABLE_KWARG_RE.findall(src))
        | set(_TABLE_SECOND_RE.findall(src))
    )


@pytest.mark.parametrize(
    "migration",
    _migration_files(),
    ids=lambda p: p.name.split("_")[0],
)
def test_migration_targets_a_real_table(migration):
    src = migration.read_text(encoding="utf-8", errors="replace")
    orm_tables = set(Base.metadata.tables) | _KNOWN_ABSENT

    # Tables this migration itself creates are fair game for its own later ops.
    created_here = set(re.findall(r'op\.create_table\(\s*\n?\s*["\']([^"\']+)["\']', src))

    unknown = _tables_touched(src) - orm_tables - created_here
    assert not unknown, (
        f"{migration.name} targets table(s) not present in the ORM: {sorted(unknown)}. "
        "Either the name is wrong, or the model was removed without retiring the "
        "migration. ff90779895f6 shipped with exactly this bug — 'companies' instead "
        "of 'company_configs'."
    )


_ADD_COLUMN_RE = re.compile(
    r'op\.add_column\(\s*\n?\s*["\']([^"\']+)["\'],\s*\n?\s*sa\.Column\(\s*\n?\s*["\']([^"\']+)["\']',
    re.MULTILINE,
)


def test_discord_columns_are_added_to_company_configs():
    """Every discord_* column must be added to `company_configs`, never `companies`.

    Written after three failed attempts at a GENERAL heuristic for "column added to
    the wrong table". Each one passed on the real bug:

      - "does the table exist?"  -> `companies` exists, so it passed
      - "does the ORM have this column here?" -> flagged ADR-212's legitimately
        removed `routes.assigned_to`, a false positive
      - "...only if a sibling table owns it" -> `companies`/`company_configs` do not
        share a stem, so the filter excluded the exact case it was built for

    The general property is genuinely hard: a migration describes history, so a
    column absent from today's model is often correct. This narrow assertion is not
    clever, but it actually fails when the bug is present — which the clever ones did
    not. A specific test that works beats a general one that does not.
    """
    # trucks.discord_channel_id is per-TRUCK (each truck has its own crew channel),
    # so it correctly lives on `trucks`. The rule is about company-level Discord
    # settings, which are all on company_configs.
    allowed_elsewhere = {("trucks", "discord_channel_id")}

    offenders = []
    for migration in _migration_files():
        src = migration.read_text(encoding="utf-8", errors="replace")
        for table, column in _ADD_COLUMN_RE.findall(src):
            if not column.startswith("discord_"):
                continue
            if table == "company_configs" or (table, column) in allowed_elsewhere:
                continue
            offenders.append(f"{migration.name}: {table}.{column}")

    assert not offenders, (
        "discord_* columns belong on company_configs, not companies:\n  "
        + "\n  ".join(offenders)
    )


def test_discord_columns_live_on_company_configs():
    """Pin the specific confusion that caused the bug.

    `Company` and `CompanyConfig` are two tables one import apart, and the discord_*
    columns are on the second. Asserted directly so a future migration author can see
    the answer without reading the model.
    """
    company_cols = set(Base.metadata.tables["companies"].columns.keys())
    config_cols = set(Base.metadata.tables["company_configs"].columns.keys())

    discord_on_config = {c for c in config_cols if c.startswith("discord_")}
    discord_on_company = {c for c in company_cols if c.startswith("discord_")}

    assert discord_on_config, "expected discord_* columns on company_configs"
    assert not discord_on_company, (
        f"discord_* columns found on `companies`: {sorted(discord_on_company)} — "
        "they belong on company_configs"
    )
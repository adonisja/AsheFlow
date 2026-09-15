"""A migration may not import application code (ADR-423).

No skip guards (ADR-311).
"""
import pathlib
import re

VERSIONS = pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions"

# `from app.x import y` or `import app.x`, anywhere in the file — including
# inside a function, which is where the two offenders hid.
_APP_IMPORT = re.compile(r"^\s*(from\s+app[\s.]|import\s+app[\s.])", re.MULTILINE)


def test_no_migration_imports_application_code():
    """A migration runs against TODAY's code but must describe the schema as it
    was at ITS OWN revision.

    This is not style. Migration 46f04059c09f imported NOT_APPLICABLE from
    app.schemas.building_taxonomy; ADR-419 renamed that constant to OTHER, and
    `alembic upgrade head` on an EMPTY database then died with ImportError —
    while every existing database, already past that revision, kept working. A
    deploy to a new environment would have failed and no local run would have
    shown it.

    Inline what the migration needs. The values are frozen at the revision by
    definition, so duplicating them is correct rather than redundant: the
    application's copy is free to change, and the migration's must not.
    """
    offenders = []
    for path in sorted(VERSIONS.glob("*.py")):
        for m in _APP_IMPORT.finditer(path.read_text()):
            line = path.read_text()[: m.start()].count("\n") + 1
            offenders.append(f"{path.name}:{line}  {m.group(0).strip()}")

    assert not offenders, (
        "these migrations import application code, which changes underneath "
        "them:\n  " + "\n  ".join(offenders)
        + "\n\nInline the values instead — a migration must describe the schema "
          "at its own revision, and its only safe dependency is the standard "
          "library."
    )

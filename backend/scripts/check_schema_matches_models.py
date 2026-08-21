"""Diff a migrated database against the ORM models (ADR-248).

    python scripts/check_schema_matches_models.py     # reads DATABASE_URL

Exits non-zero if any model table or column is missing from the database.

## Why this exists separately from `alembic upgrade head`

A migration chain can complete successfully and still leave the schema wrong.
That is not hypothetical — it happened while fixing ADR-248: guarding an
`ALTER TABLE` that ran before its table existed stopped the crash, and in doing
so meant those columns were added on the already-migrated path and never on the
fresh one. `alembic upgrade head` was GREEN on both paths. The whole test suite
was green. Only diffing the result against the models found it.

So the migration answers "did anything error", and this answers "is the result
correct". They are different questions and CI needs both.

Deliberately one-directional: it fails on things the models declare and the
database lacks. Extra columns in the database are not failed — a dropped model
field often outlives its column on purpose, and failing on those would make the
check noisy enough to be ignored.
"""
from __future__ import annotations

import importlib
import os
import pkgutil
import sys

import sqlalchemy as sa


def _load_all_models() -> None:
    import app.models as models_pkg

    for _, name, _ in pkgutil.iter_modules(models_pkg.__path__):
        try:
            importlib.import_module(f"app.models.{name}")
        except Exception:
            # Proprietary model modules are absent from a public checkout.
            pass


def main() -> int:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    _load_all_models()
    from app.models.base import Base

    insp = sa.inspect(sa.create_engine(url))
    db_tables = set(insp.get_table_names())
    model_tables = set(Base.metadata.tables)

    missing_tables = sorted(model_tables - db_tables)
    missing_columns: list[tuple[str, list[str]]] = []

    for table in sorted(model_tables & db_tables):
        have = {c["name"] for c in insp.get_columns(table)}
        want = set(Base.metadata.tables[table].columns.keys())
        gap = sorted(want - have)
        if gap:
            missing_columns.append((table, gap))

    print(f"model tables: {len(model_tables)}   database tables: {len(db_tables)}")

    if not missing_tables and not missing_columns:
        print("OK — every model table and column is present in the database")
        return 0

    print("\nSCHEMA DRIFT — the migration chain completed but the result is wrong:\n")
    for t in missing_tables:
        print(f"  MISSING TABLE   {t}")
    for t, cols in missing_columns:
        print(f"  MISSING COLUMNS {t}: {', '.join(cols)}")
    print(
        "\nFix with a NEW revision at the head that adds what is missing — not by\n"
        "editing a shipped revision. Both fresh and already-migrated databases\n"
        "pass through the head, so that is the only place a reconciliation lands\n"
        "for everyone (ADR-248)."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

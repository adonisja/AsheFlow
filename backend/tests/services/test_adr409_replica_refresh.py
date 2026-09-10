"""ADR-409 D8 — the refresh job's three properties, pinned in source.

The behaviours were verified against a real Postgres replica during
development: 584 rows copied, a second run changing nothing, a replica-only row
surviving, and a tampered row restored from the master. Those runs are gone;
these assertions keep the properties from being edited away.

Source-text, deliberately. Standing up two databases in CI to re-prove what was
already proven against real Postgres would be slow and would test psycopg2 more
than it tests this decision.
"""
import re
from pathlib import Path

import pytest

SCRIPT = (Path(__file__).resolve().parents[2]
          / "scripts" / "refresh_placetype_replica.py")


@pytest.fixture(scope="module")
def src() -> str:
    assert SCRIPT.exists(), f"the refresh job is gone: {SCRIPT}"
    text = SCRIPT.read_text()
    # Vacuity guard: every assertion below passes against a file that no longer
    # copies anything.
    assert "INSERT INTO" in text, "the script no longer writes"
    return text


def _code(src: str) -> str:
    """Source with comments and docstrings stripped.

    A test in this repo once asserted a feature's ABSENCE and matched the
    comment explaining why it was absent. Comments describe; only code acts.
    """
    out = re.sub(r'""".*?"""', "", src, flags=re.S)
    return re.sub(r"#[^\n]*", "", out)


class TestAdditive:
    def test_it_never_deletes(self, src: str) -> None:
        """D8. A row missing from the master must NOT be removed from a replica.

        A deletion propagating from a bad master run would empty a working
        environment, and it would look like a successful sync — which is worse
        than failing, because nobody investigates a green job.
        """
        code = _code(src)
        for verb in ("DELETE FROM", "TRUNCATE", "DROP TABLE"):
            assert verb not in code.upper(), (
                f"the refresh job contains {verb!r}; it must be additive, so a "
                f"replica-only row survives and a bad master run cannot empty "
                f"an environment (ADR-409 D8)"
            )

    def test_it_upserts_rather_than_replacing(self, src: str) -> None:
        code = _code(src)
        assert "ON CONFLICT" in code and "DO UPDATE SET" in code, (
            "the refresh no longer upserts — DELETE-then-INSERT would drop "
            "replica-only rows between the two statements"
        )


class TestIdempotent:
    def test_a_conflicting_row_keeps_its_local_id(self, src: str) -> None:
        """The surrogate key is per-database (see _SKIP_COLUMNS).

        `id` must be absent from the SET clause, or every refresh renumbers
        every row — which makes the job non-idempotent at the storage layer even
        though the data looks unchanged.
        """
        code = _code(src)
        assert 'updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c != key)' in code
        assert '"id"' in code and "_SKIP_COLUMNS" in code, (
            "the id column is no longer excluded from the copy"
        )


class TestReportsRatherThanAsserts:
    def test_a_column_mismatch_does_not_fail_the_run(self, src: str) -> None:
        """D8. During a deploy window the replica may run an older migration.

        Copying a column it lacks fails the whole refresh; copying only the
        intersection degrades to a partial refresh that COMPLETES and reports
        what it skipped.
        """
        code = _code(src)
        assert "cols = [c for c in src_cols if c in dst_cols]" in code, (
            "the refresh no longer intersects columns, so a schema skew during "
            "a deploy fails the whole run"
        )
        assert "columns_missing_in_replica" in code, "the skew is not reported"

    def test_it_does_not_assert_row_counts_match(self, src: str) -> None:
        """Counts differ until the first run completes, so a job that failed on
        a mismatch would fail every time until it happened to succeed once."""
        code = _code(src)
        assert "assert" not in code, (
            "the refresh job asserts; it must report, because row counts "
            "legitimately differ before the first successful run"
        )


class TestSafety:
    def test_production_refreshing_itself_is_a_no_op(self, src: str) -> None:
        """Production WRITES the master. Pointing the job at itself must do
        nothing rather than rewrite every row with itself."""
        assert "if master == replica:" in _code(src)

    def test_only_the_two_placetype_tables_are_copied(self, src: str) -> None:
        """`building_profiles` and `company_zones` are TENANT data (ADR-409 D1).

        Copying either across environments would move customer observations
        between deployments — the thing the public/tenant split exists to
        prevent.
        """
        code = _code(src)
        tables = set(re.findall(r'\("(\w+)", "\w+"\)', code))
        assert tables == {"street_segments", "building_profile_library"}, (
            f"the refresh copies {sorted(tables)}; only the two tables the "
            f"ADR-237 boundary owns may cross environments"
        )

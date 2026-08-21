"""CI gate: no in-place mutation of unwrapped ARRAY/JSONB columns (ADR-247).

`test_mutable_column_guard.py` pins the declarations. This pins the call sites
— the place the actual bug lived, where `route.tote_ids.pop()` was discarded
and left one tote recorded on two routes.

The scanner lives in `scripts/scan_mutable_mutations.py` so it can also be run
by hand for a report.

**The canary tests below are not decoration.** A scanner that is silently
broken and a codebase that is clean produce identical output, and during the
ADR-247 work a scan printed nothing twice while actually failing. Any check
whose *negative* result gates a merge needs a positive control, so
`test_scanner_detects_*` plant each shape and assert it is caught. If those
fail, `test_no_in_place_mutation` proves nothing.
"""
import textwrap

import pytest

from scripts.scan_mutable_mutations import MUTATORS, scan


@pytest.fixture
def planted(tmp_path):
    """Write a source file into a scratch tree and scan it for a fake column."""
    def _plant(source: str, columns=frozenset({"tote_roster"})):
        (tmp_path / "bait.py").write_text(textwrap.dedent(source))
        return scan(tmp_path, set(columns))
    return _plant


# ── the gate ────────────────────────────────────────────────────────────────

def test_no_in_place_mutation():
    findings = scan("app")
    assert not findings, (
        "In-place mutation of an unwrapped ARRAY/JSONB column — these writes "
        "are SILENTLY DISCARDED at commit (ADR-247):\n\n  "
        + "\n  ".join(str(f) for f in findings)
        + "\n\nFix by reassigning the column as a whole:\n"
          "    obj.col = list(obj.col or []) + [x]\n"
          "or wrap the column in MutableList so mutation is tracked, or — if it "
          "is a relationship collection rather than the column of the same name "
          "— add it to ALLOWLIST in scripts/scan_mutable_mutations.py with the "
          "reason."
    )


# ── canaries: prove the scanner actually detects each shape ─────────────────

def test_scanner_detects_direct_call(planted):
    found = planted("def f(z): z.tote_roster.append(1)")
    assert [f.kind for f in found] == ["direct"]


def test_scanner_detects_aliased_mutation(planted):
    """The shape grep cannot see — the reason this is an AST pass."""
    found = planted("""
        def f(z):
            s = z.tote_roster
            s.append(1)
    """)
    assert [f.kind for f in found] == ["alias"]


def test_scanner_detects_subscript_assignment(planted):
    found = planted("def f(z): z.tote_roster[0] = 1")
    assert [f.kind for f in found] == ["subscript"]


def test_scanner_detects_nested_subscript_assignment(planted):
    """`stops[0]["k"] = v` — the nested case MutableList does not track either."""
    found = planted('def f(z): z.tote_roster[0]["k"] = 1')
    assert [f.kind for f in found] == ["subscript"]


def test_scanner_detects_augmented_assignment(planted):
    found = planted("def f(z): z.tote_roster += [1]")
    assert [f.kind for f in found] == ["augassign"]


@pytest.mark.parametrize("method", sorted(MUTATORS))
def test_scanner_detects_every_mutator(planted, method):
    assert planted(f"def f(z): z.tote_roster.{method}()")


# ── the scanner must not cry wolf ───────────────────────────────────────────

def test_reassignment_is_not_flagged(planted):
    """The correct idiom must stay silent, or the gate trains people to ignore it."""
    assert not planted("def f(z): z.tote_roster = list(z.tote_roster or []) + [1]")


def test_copy_then_mutate_is_not_flagged(planted):
    """`list(...)` yields a new list; mutating it cannot affect the column."""
    found = planted("""
        def f(z):
            local = list(z.tote_roster)
            local.append(1)
            return local
    """)
    assert not found


def test_read_only_use_is_not_flagged(planted):
    found = planted("""
        def f(z):
            n = len(z.tote_roster)
            return set(z.tote_roster), n
    """)
    assert not found


def test_unrelated_attribute_is_not_flagged(planted):
    assert not planted("def f(z): z.something_else.append(1)")


def test_wrapped_columns_are_excluded():
    """A wrapped column must drop out of the watch set, or ADR-247's own fix
    would be reported as a violation.

    Checked on names unique to Route. `tba_numbers` is deliberately NOT here:
    see the name-collision test below.
    """
    from scripts.scan_mutable_mutations import mutable_column_names

    unwrapped = mutable_column_names()
    for col in ("tote_ids", "block_keys", "normalised_addresses", "stops"):
        assert col not in unwrapped, (
            f"Route.{col} is reported as unwrapped — either the MutableList "
            f"wrapper was removed, or the behavioural detection broke."
        )


def test_a_name_shared_with_an_unwrapped_column_stays_watched():
    """The cost of resolving by name, made explicit.

    `tba_numbers` is wrapped on Route but NOT on DeliveryStop or
    PackageRemoval. Since the scanner cannot tell which model a given
    `x.tba_numbers` belongs to, the name must stay in the watch set — dropping
    it because Route is safe would blind the gate to the two models that are
    not.

    The consequence is that a genuinely-safe `route.tba_numbers.append(...)`
    would be flagged. That is the correct trade (false positives over false
    negatives) and is resolved by ALLOWLIST if it ever comes up.
    """
    from scripts.scan_mutable_mutations import mutable_column_names

    assert "tba_numbers" in mutable_column_names(), (
        "tba_numbers dropped out of the watch set — if DeliveryStop and "
        "PackageRemoval were both wrapped this is correct and the test should "
        "be removed; otherwise the gate has gone blind to them."
    )

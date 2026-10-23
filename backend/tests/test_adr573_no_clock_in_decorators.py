"""No test reads the clock inside a decorator's arguments (ADR-573).

A decorator argument -- most often @pytest.mark.parametrize -- is evaluated when
the module is imported at collection, not when the test runs. A CI run that
collected before midnight UTC and ran the test after made
`date.today() + timedelta(days=1)` today, and a "future date is refused" case
passed validation (test_adr492, CI run 39874023131).

Module-level constants are not flagged: a frozen date passed explicitly to the
code under test is stable. A clock read in a decorator only ever feeds a
comparison against the code's own clock, which is the flaky shape.
"""
import ast
from pathlib import Path

_TESTS = Path(__file__).resolve().parent
_CLOCK = {"today", "now", "utcnow"}


def test_no_clock_reads_in_decorator_arguments():
    hits = []
    for path in sorted(_TESTS.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            for deco in getattr(node, "decorator_list", []):
                for n in ast.walk(deco):
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in _CLOCK:
                        hits.append(f"{path.relative_to(_TESTS)}:{n.lineno} {ast.unparse(n)}")
    # A clock read inside a lambda runs when the lambda is CALLED (in the test),
    # so it is allowed: drop calls whose nearest enclosing node is a Lambda.
    allowed = set()
    for path in sorted(_TESTS.rglob("*.py")):
        for lam in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(lam, ast.Lambda):
                for n in ast.walk(lam):
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in _CLOCK:
                        allowed.add(f"{path.relative_to(_TESTS)}:{n.lineno} {ast.unparse(n)}")
    hits = [h for h in hits if h not in allowed]
    assert not hits, (
        "these read the clock when the module is IMPORTED, so a run crossing midnight UTC "
        f"compares a stale date with the code's live one: {hits}. Compute it inside the test."
    )

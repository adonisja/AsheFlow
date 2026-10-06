#!/usr/bin/env python3
"""Fail on a local wall-clock time relabelled as UTC (ADR-485 D18).

WHY THIS EXISTS
CompanyConfig and the building rows store times as naive `Time` columns,
documented as "read in the company's own timezone". Two ways of turning one
into an instant are wrong:

    datetime.combine(d, t).replace(tzinfo=timezone.utc)   # relabels: 4-5h off
    datetime.combine(d, t).astimezone(timezone.utc)       # uses the SERVER zone

The second is the quieter one -- accidentally right wherever the server runs
UTC, silently wrong everywhere else. Both are replaced by
`local_date.company_datetime(tz, d, t)` / `company_midnight(tz, d)`.

NOT flagged: `.replace(tzinfo=timezone.utc)` on a value that genuinely IS UTC --
a naive timestamp read back from the database. That is correct and common.
Only a `combine(...)` immediately followed by one of the two forms is a defect.

Usage:
    python3 scripts/check_no_naive_utc_relabel.py
"""
import pathlib
import ast
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent / "backend/app"

# combine(...) -> .replace(tzinfo=timezone.utc) or .astimezone(...), allowing
# the call to wrap across lines.
# The combine(...) must be NAIVE for this to be a relabel. `combine(d, t,
# tzinfo=tz)` builds an AWARE datetime in the tenant's zone, so a following
# .astimezone(utc) genuinely CONVERTS -- that is the correct implementation,
# and it lives in local_date.company_datetime.
#
# The first version of this pattern did not check, so it flagged the fix it
# exists to enforce. That was papered over with EXEMPT = {"services/
# local_date.py"}, which silenced the whole module: a REAL relabel added there
# would have passed. Excluding tzinfo= from the combine args fixes the pattern
# instead, and the exemption is gone.
_BAD = re.compile(
    r"(?:datetime|_dt)\.combine\((?![^()]*tzinfo\s*=)(?:[^()]|\([^()]*\))*\)\s*"
    r"\.(?:replace\(\s*tzinfo\s*=\s*(?:timezone\.)?utc\s*\)|astimezone\()",
    re.S,
)
_COMMENT = re.compile(r"^\s*#.*$", re.M)


def _code_only(src: str) -> str:
    """Strip comments AND docstrings before matching.
    Comments were stripped from the first version; docstrings were not, and
    that gap cost a false positive the day a module explained the rule in its
    own docstring -- correct code, quoting the forbidden form to say what NOT
    to write. The gate flagged the explanation.

    The existing answer was an EXEMPT entry per file, which does not scale and
    silences a whole MODULE rather than its prose: services/local_date.py was
    exempt entirely, so a real relabel introduced there would have passed.
    Stripping docstrings fixes the class of problem instead of its instances.

    AST rather than a triple-quote regex: a regex cannot tell a docstring from
    a multi-line string that is DATA, and blanking the latter could hide a real
    hit inside, say, a SQL literal.
    """
    src = _COMMENT.sub("", src)
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return src      # unparseable: match raw text rather than skip the file

    blank = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef,
                                 ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if (isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            blank.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))

    if not blank:
        return src
    return "\n".join(
        "" if (i + 1) in blank else line
        for i, line in enumerate(src.splitlines())
    )


# No per-file exemptions. services/local_date.py previously needed one because
# its docstring demonstrates both wrong forms by design -- now handled by
# stripping docstrings everywhere, which also means a REAL relabel in that
# module is no longer invisible.
EXEMPT: set[str] = set()


def main() -> int:
    hits = []
    for path in sorted(ROOT.rglob("*.py")):
        if any(str(path).endswith(e) for e in EXEMPT):
            continue
        src = _code_only(path.read_text())
        for m in _BAD.finditer(src):
            line = src[: m.start()].count("\n") + 1
            hits.append((path.relative_to(ROOT.parent.parent), line,
                         " ".join(m.group(0).split())[:90]))

    if not hits:
        print("OK — no naive local time relabelled as UTC")
        return 0

    print(f"{len(hits)} naive-UTC relabel(s):\n")
    for rel, line, snippet in hits:
        print(f"  {rel}:{line}\n      {snippet}")
    print(
        "\nUse local_date.company_datetime(tz, d, t) or company_midnight(tz, d).\n"
        "A stored Time is LOCAL; attaching UTC relabels it instead of converting\n"
        "(ADR-485 D18), and .astimezone() on a naive value uses the SERVER zone."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())

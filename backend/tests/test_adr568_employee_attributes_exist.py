"""Every attribute read off an Employee-typed argument exists on Employee (ADR-568).

CLAUDE.md Dimension 3 asks reviewers to confirm each model attribute a change
references exists. That rule came after the ADR-446 incident (2026-09-20);
collection.py's `caller.first_name` shipped 2026-09-14 and returned 500 for every company
admin until 2026-10-22, because a rule written later re-checks nothing older.
This test re-checks everything, every run.

Scope: functions in app/routers, app/services and app/tasks with an argument
annotated EXACTLY as the Employee model (`Employee`, `Employee | None`,
`Optional[Employee]`). Exact, because a substring match also catches request
schemas like EmployeeUpdate and reports their fields (17 false positives on
the first run). Untyped variables (`emp = db.query(Employee)...`) are not
covered: the annotation is what makes the type knowable without running code.
"""
import ast
import pathlib
import re

import app.main  # noqa: F401  registers every model
from app.models.employee import Employee

APP = pathlib.Path(__file__).resolve().parents[1] / "app"
EXACT = re.compile(r"^(Optional\[Employee\]|Employee( \| None)?|None \| Employee)$")


def _missing_attributes() -> tuple[int, list[str]]:
    have = set(dir(Employee))
    found, functions = [], 0
    for path in sorted(p for d in ("routers", "services", "tasks") for p in (APP / d).glob("*.py")):
        for fn in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            typed = {a.arg for a in fn.args.args + fn.args.kwonlyargs
                     if a.annotation is not None and EXACT.match(ast.unparse(a.annotation))}
            if not typed:
                continue
            functions += 1
            for n in ast.walk(fn):
                if (isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
                        and n.value.id in typed and n.attr not in have):
                    found.append(f"{path.relative_to(APP.parent)}:{n.lineno} {fn.name}: {n.value.id}.{n.attr}")
    return functions, sorted(set(found))


def test_every_attribute_read_off_an_employee_exists():
    functions, missing = _missing_attributes()
    assert functions > 100, f"only {functions} functions matched: did the annotation style change?"
    assert not missing, (
        "these read attributes Employee does not have; each is an AttributeError at request "
        f"time that `import app.main` cannot see (ADR-568): {missing}"
    )

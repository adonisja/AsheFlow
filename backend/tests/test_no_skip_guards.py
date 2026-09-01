"""No test may skip because a proprietary import failed (ADR-311).

CI clones AsheFlow-private with a read-only deploy key and copies the
proprietary routers and services into place BEFORE pytest runs, so a failed
import is never "the public repo is missing this file" — it is a broken or
stale private sync, which CI must surface.

A guard cannot prevent a real failure here. It can only hide one. Measured
2026-08-26: with the proprietary code absent, 16 guarded files went from 202
passing to 35 passing and pytest still exited 0. 167 tests vanished silently.

This test is the mechanical half of the CLAUDE.md rule — a convention an agent
can overlook, enforced as something the suite rejects.
"""
import ast
import subprocess
from pathlib import Path

TESTS = Path(__file__).parent


def _tracked(p: Path) -> bool:
    """Only files in the PUBLIC repo. Gitignored tests live in AsheFlow-private
    and are copied in by CI; they are not ours to police here."""
    return subprocess.run(
        ["git", "ls-files", "--error-unmatch", str(p)],
        capture_output=True, cwd=TESTS.parent,
    ).returncode == 0


def _skip_calls(tree: ast.AST):
    """Every pytest.skip(...) call in the module, module-level or in a body."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Attribute) and f.attr == "skip":
            yield node


def test_no_test_skips_on_a_failed_import():
    """The banned shape: `except ImportError: pytest.skip(...)`."""
    offenders = []
    for path in sorted(TESTS.rglob("test_*.py")):
        if path.name == Path(__file__).name or not _tracked(path):
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            for handler in node.handlers:
                names = ast.dump(handler.type) if handler.type else ""
                if "ImportError" not in names and "ModuleNotFoundError" not in names:
                    continue
                if any(_skip_calls(ast.Module(body=handler.body, type_ignores=[]))):
                    rel = path.relative_to(TESTS.parent)
                    offenders.append(f"{rel}:{handler.lineno}")

    assert not offenders, (
        "These tests skip when a proprietary import fails:\n  "
        + "\n  ".join(offenders)
        + "\n\nCI copies the proprietary modules in from AsheFlow-private BEFORE "
          "pytest runs, so the import always resolves. A guard here cannot prevent "
          "a real failure — it can only hide a broken or stale private sync, and "
          "turn a red build green. Import the module directly and let a missing "
          "one be a collection error. See ADR-311 and the CLAUDE.md rule."
    )


def test_no_module_level_skip_guards_at_all():
    """`allow_module_level=True` silently removes a WHOLE FILE from the run —
    the widest available blast radius, and invisible in a passing summary."""
    offenders = []
    for path in sorted(TESTS.rglob("test_*.py")):
        if path.name == Path(__file__).name or not _tracked(path):
            continue
        tree = ast.parse(path.read_text())
        for call in _skip_calls(tree):
            for kw in call.keywords:
                if kw.arg == "allow_module_level" and getattr(kw.value, "value", False) is True:
                    offenders.append(f"{path.relative_to(TESTS.parent)}:{call.lineno}")

    assert not offenders, (
        "Module-level skip guards found:\n  " + "\n  ".join(offenders)
        + "\n\nA module-level skip drops the entire file from the suite while CI "
          "still reports success. If the module genuinely cannot be imported, that "
          "is a failure worth seeing. See ADR-311."
    )

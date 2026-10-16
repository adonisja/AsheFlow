"""ADR-520: no undefined name anywhere in the backend.

`python -c "import app.main"` passes for a function that names a variable it
never receives: the NameError waits for the line to run. Seven such lines were
live on 2026-10-15, including dispatch publishing (every dispatch_assignment
notification) and every walker stop action. This walks the source instead.
"""
import io
import pathlib

from pyflakes.api import checkPath
from pyflakes.reporter import Reporter

APP = pathlib.Path(__file__).resolve().parents[1] / "app"


def test_no_undefined_names_in_app():
    out, err = io.StringIO(), io.StringIO()
    for p in sorted(APP.rglob("*.py")):
        checkPath(str(p), Reporter(out, err))
    undefined = [line for line in out.getvalue().splitlines() if "undefined name" in line]
    assert not undefined, (
        f"{len(undefined)} undefined name(s): each is a NameError the first time its line "
        f"runs, invisible to an import check:\n  " + "\n  ".join(undefined))


def test_the_check_sees_the_whole_app():
    assert len(list(APP.rglob("*.py"))) > 100

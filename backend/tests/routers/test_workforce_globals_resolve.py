"""Every global a workforce endpoint references must exist at import time.

`python -c "import app.main"` proves a MODULE imports. It says nothing about the
bodies of its functions, because a name inside a function is looked up when that
line runs. So a missing import in a branch nobody exercised is a NameError that
waits for a real request.

That bug shipped twice in one session (2026-09-08/09):
  - `parts.get(route.id)` in assign_walker with no `parts = _participants(...)`
    above it;
  - `func.count(...)` in the OV seed endpoint with no `from sqlalchemy import
    func`.

Both modules imported cleanly. Both would have 500'd on the first call.

Disassembling for LOAD_GLOBAL finds them statically: it asks "which names does
this function look up in module scope", then checks each against the module and
builtins. Attribute access (`db.query`) is LOAD_ATTR and correctly ignored.
"""
import builtins
import dis
import types

import pytest

import app.routers.workforce_routes as W
import app.routers.manual_returns as MR


def _unresolved(module) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for name, fn in vars(module).items():
        if not isinstance(fn, types.FunctionType) or fn.__module__ != module.__name__:
            continue
        missing = sorted({
            i.argval for i in dis.get_instructions(fn)
            if i.opname == "LOAD_GLOBAL"
            and i.argval not in module.__dict__
            and not hasattr(builtins, i.argval)
        })
        if missing:
            out[name] = missing
    return out


@pytest.mark.parametrize("module", [W, MR], ids=lambda m: m.__name__.rsplit(".", 1)[-1])
def test_no_function_references_a_missing_global(module) -> None:
    # Vacuity guard: a module whose functions all vanished would pass trivially.
    scanned = sum(
        1 for _, f in vars(module).items()
        if isinstance(f, types.FunctionType) and f.__module__ == module.__name__
    )
    assert scanned > 5, f"only {scanned} functions found in {module.__name__}"

    missing = _unresolved(module)
    assert not missing, (
        "these functions reference names that do not exist in module scope — "
        "they import cleanly and NameError on the first request:\n  "
        + "\n  ".join(f"{fn}: {names}" for fn, names in missing.items())
    )

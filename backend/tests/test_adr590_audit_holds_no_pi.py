"""ADR-590 — an audit row points at its record; it does not copy the package
id or the customer's address.

Walks every write_audit call in app/ and fails on a literal detail/before/after
key naming a TBA or an address, outside the allowlist below (each with its
reason). A count under len() is not the value and passes.
"""
import ast
import pathlib
import re

BACKEND = pathlib.Path(__file__).resolve().parents[1]
PI_KEY = re.compile(
    r"(^|_)(tba|tbas|tba_number|tba_numbers|package_tbas|address|addresses|"
    r"normalised_address|raw_address)($|_)", re.I)

ALLOWED = {
    # D3: the field-added feed (ADR-246) reads its rows from these audit rows;
    # the TBA is what dispatch looks for. Blanked at 90 days, erasable.
    ("app/routers/package_intake.py", "_resolve"),
    # The DSP's own staging point, not a customer (exempt in erasure too).
    ("app/routers/trucks.py", "set_truck_anchor"),
    ("app/routers/trucks.py", "set_truck_anchor2"),
    # ADR-431 D3: a HARD delete's audit is the only record of what it destroyed,
    # and a collected building observation is not a customer delivery address.
    ("app/routers/collection.py", "delete_collected_profile"),
    ("app/routers/collection.py", "delete_profiles_by_device"),
}


def _offenders():
    out = []
    for p in sorted((BACKEND / "app").rglob("*.py")):
        rel = str(p.relative_to(BACKEND))
        tree = ast.parse(p.read_text())
        parent = {c: n for n in ast.walk(tree) for c in ast.iter_child_nodes(n)}

        def fn_of(n):
            while n in parent:
                n = parent[n]
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    return n.name
            return "<module>"
        for n in ast.walk(tree):
            if not (isinstance(n, ast.Call) and
                    (getattr(n.func, "id", None) or getattr(n.func, "attr", None)) == "write_audit"):
                continue
            for k in n.keywords:
                if k.arg not in ("detail", "before", "after") or not isinstance(k.value, ast.Dict):
                    continue
                for key, val in zip(k.value.keys, k.value.values):
                    if (isinstance(key, ast.Constant) and isinstance(key.value, str)
                            and PI_KEY.search(key.value)
                            and not (isinstance(val, ast.Call) and getattr(val.func, "id", None) == "len")):
                        out.append((rel, fn_of(n), key.value, n.lineno))
    return out


def test_no_audit_row_copies_a_tba_or_an_address():
    bad = [o for o in _offenders() if o[:2] not in ALLOWED]
    assert not bad, (
        "These audit rows copy a TBA or an address (ADR-590). Point at the row "
        f"with target_id instead, or add the call to ALLOWED with its reason: {bad}")


def test_the_walk_sees_the_allowed_writes():
    """Vacuity guard: if the walk finds none of the known ones, it finds nothing."""
    seen = {o[:2] for o in _offenders()}
    assert ("app/routers/package_intake.py", "_resolve") in seen


def test_every_allowed_entry_still_writes_one():
    """A stale entry would quietly cover a future write in a function of that name."""
    seen = {o[:2] for o in _offenders()}
    assert not sorted(ALLOWED - seen), sorted(ALLOWED - seen)


def test_a_count_is_not_the_value():
    src = 'write_audit(db, detail={"tbas": len(x), "tba": t})'
    tree = ast.parse(src)
    call = tree.body[0].value
    keys = [k.value for k, v in zip(call.keywords[0].value.keys, call.keywords[0].value.values)
            if PI_KEY.search(k.value) and not (isinstance(v, ast.Call) and getattr(v.func, "id", None) == "len")]
    assert keys == ["tba"]

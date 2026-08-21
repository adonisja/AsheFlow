"""Find in-place mutation of unwrapped ARRAY/JSONB columns (ADR-247).

An unwrapped mutable column discards `.append()` / `.pop()` / `[i] = x`
silently — no error, and a read in the same session still shows the change.
`tests/models/test_mutable_column_guard.py` pins the *declarations*; this pins
the *call sites*, which is where the real bug lived (a duplicated tote across
two routes, ADR-213/ADR-247).

Run standalone for a report:

    python scripts/scan_mutable_mutations.py app

`tests/models/test_mutable_mutation_scan.py` imports `scan()` and fails CI on
any finding.

## Why this is name-based, and what that costs

Resolving `x.items.append(...)` to a model attribute needs type inference,
which Python does not give us statically. So a column name is treated as
interesting wherever it appears as an attribute access.

That is deliberately over-broad: it can only produce false *positives*, never
false negatives, which is the correct direction for a guard. False positives
are silenced explicitly in ALLOWLIST, so each one is a recorded decision.

Exactly one mutable column name currently collides with a relationship name
(`items`: `VehicleInspection.items` is JSONB, `ScorecardAppeal.items` is a
relationship collection that SQLAlchemy tracks natively). Rather than drop the
name — which would blind the scanner to the real column — the known-safe
receivers are allowlisted by variable name.
"""
from __future__ import annotations

import ast
import pathlib
import sys
from dataclasses import dataclass

# Mutating methods. `update`/`setdefault`/`popitem` are dict-side; the rest list.
MUTATORS = frozenset({
    "append", "extend", "insert", "pop", "remove", "clear", "sort", "reverse",
    "update", "setdefault", "popitem",
})

# (file_suffix, receiver_name, attribute) triples that are known-safe.
# Each entry needs a reason — this is the record of a decision, not a mute button.
ALLOWLIST = {
    # `appeal.items` is a relationship collection of ScorecardAppealItem rows,
    # not VehicleInspection's JSONB column of the same name. SQLAlchemy tracks
    # relationship collections natively, so mutation persists correctly.
    ("routers/scorecard_appeals.py", "appeal", "items"),
}


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    kind: str
    detail: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}  [{self.kind}] {self.detail}"


def mutable_column_names() -> set[str]:
    """Names of every ARRAY/JSONB column that is NOT mutation-tracked.

    Wrapped columns drop out: mutating those is correct and is the whole point
    of ADR-247. Detection is behavioural — see the guard test for why the type
    object cannot be inspected.

    A name survives if it is unwrapped on *any* model. `tba_numbers` is wrapped
    on Route but not on DeliveryStop or PackageRemoval, so it stays watched —
    dropping it because one model is safe would blind the scan to the two that
    are not. The cost is that a safe `route.tba_numbers.append(...)` would be
    flagged; ALLOWLIST is the escape hatch if that ever occurs.
    """
    import importlib
    import pkgutil

    from sqlalchemy import ARRAY
    from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY, JSON, JSONB
    from sqlalchemy.ext.mutable import MutableDict, MutableList

    import app.models as models_pkg
    from app.models.base import Base

    for _, name, _ in pkgutil.iter_modules(models_pkg.__path__):
        try:
            importlib.import_module(f"app.models.{name}")
        except Exception:  # proprietary modules may be absent from this checkout
            pass

    names: set[str] = set()
    for mapper in Base.registry.mappers:
        table = mapper.local_table
        if table is None:
            continue
        for col in table.columns:
            if not isinstance(col.type, (ARRAY, PG_ARRAY, JSONB, JSON)):
                continue
            try:
                probe = mapper.class_()
                setattr(probe, col.key, [])
                if isinstance(getattr(probe, col.key), (MutableList, MutableDict)):
                    continue  # tracked — mutation is safe
            except Exception:
                pass
            names.add(col.key)
    return names


def _receiver(node: ast.AST) -> str:
    """Best-effort source name of the object being mutated ('route', 'appeal')."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return "?"


def _allowed(rel_path: str, receiver: str, attr: str) -> bool:
    return any(
        rel_path.endswith(suffix) and receiver == recv and attr == a
        for suffix, recv, a in ALLOWLIST
    )


def scan(root: str | pathlib.Path, columns: set[str] | None = None) -> list[Finding]:
    cols = mutable_column_names() if columns is None else columns
    root = pathlib.Path(root)
    findings: list[Finding] = []

    for path in sorted(root.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text())
        except (SyntaxError, UnicodeDecodeError):
            continue
        rel = str(path)

        # Locals bound straight to a column: `s = route.stops` (a list()/copy
        # wrapper is a different node type and correctly not matched).
        aliases: dict[str, tuple[str, int]] = {}
        for node in ast.walk(tree):
            if (isinstance(node, ast.Assign)
                    and isinstance(node.value, ast.Attribute)
                    and node.value.attr in cols
                    and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)):
                aliases[node.targets[0].id] = (node.value.attr, node.lineno)

        for node in ast.walk(tree):
            # obj.col.append(...)
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in MUTATORS
                    and isinstance(node.func.value, ast.Attribute)
                    and node.func.value.attr in cols):
                recv = _receiver(node.func.value.value)
                if not _allowed(rel, recv, node.func.value.attr):
                    findings.append(Finding(
                        rel, node.lineno, "direct",
                        f"{recv}.{node.func.value.attr}.{node.func.attr}()"))

            # s = obj.col ; s.append(...)
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in MUTATORS
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id in aliases):
                col, bound = aliases[node.func.value.id]
                if not _allowed(rel, node.func.value.id, col):
                    findings.append(Finding(
                        rel, node.lineno, "alias",
                        f"{node.func.value.id}.{node.func.attr}() "
                        f"-> .{col} bound line {bound}"))

            # obj.col[i] = x   /   obj.col[i]["k"] = x
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    inner = target
                    while isinstance(inner, ast.Subscript):
                        inner = inner.value
                    if (isinstance(target, ast.Subscript)
                            and isinstance(inner, ast.Attribute)
                            and inner.attr in cols
                            and not _allowed(rel, _receiver(inner.value), inner.attr)):
                        findings.append(Finding(
                            rel, node.lineno, "subscript", f"{inner.attr}[...] ="))

            # obj.col += [...]
            if (isinstance(node, ast.AugAssign)
                    and isinstance(node.target, ast.Attribute)
                    and node.target.attr in cols
                    and not _allowed(rel, _receiver(node.target.value), node.target.attr)):
                findings.append(Finding(
                    rel, node.lineno, "augassign", f"{node.target.attr} +="))

    return findings


def main() -> int:
    # Running as a script puts scripts/ on sys.path, not the backend root, so
    # `import app` fails. Under pytest the rootdir is already there and this is
    # a no-op.
    backend_root = str(pathlib.Path(__file__).resolve().parent.parent)
    if backend_root not in sys.path:
        sys.path.insert(0, backend_root)

    root = sys.argv[1] if len(sys.argv) > 1 else "app"
    cols = mutable_column_names()
    findings = scan(root, cols)

    print(f"Scanning {root} for in-place mutation of "
          f"{len(cols)} unwrapped mutable columns\n")
    if not findings:
        print("  clean — no in-place mutation found")
        return 0
    for f in findings:
        print(f"  {f}")
    print(f"\n{len(findings)} finding(s). These writes are SILENTLY DISCARDED "
          f"(ADR-247).\nReassign the column instead, wrap it in MutableList, or "
          f"allowlist with a reason.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

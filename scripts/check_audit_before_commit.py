#!/usr/bin/env python3
"""An audit row written after the commit is not written (ADR-490).

WHAT THIS CATCHES
-----------------
    db.commit()          # the state change lands HERE
    write_audit(...)     # the audit row is added AFTER

At best that is a window: anything raising in between commits the change and
loses its record. At worst the row is never persisted at all, because `get_db`
only closes the session:

    def get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()        # an uncommitted session is DISCARDED

Measured when this was written: 220 call sites, 212 already correct, 7 genuine
defects. Three of the seven never persisted their row — the whole employee
lifecycle (create, bulk import, update) wrote no audit trail from the day it
shipped, and `employee.create` had 0 rows against 22 employees.

WHY THIS IS NOT A POSITION CHECK
--------------------------------
The obvious implementation compares the FIRST `db.commit()` to the FIRST
`write_audit(...)`. That is what found the seven, and it also produced EIGHT
false positives — more noise than signal. All three exclusions below are
required; a gate without them fails on correct code, somebody adds an EXEMPT
list, and the list silences whole modules. ADR-488's naive-UTC gate did exactly
that and hid a real relabel in the one file it existed to protect.

  A. The audit rides the NEXT commit, with the mutations it describes.
     A function that does several things has several transactions, and each
     audit belongs with the one it describes — not with the first:

         db.commit()                   # lands the publish
         assignment.status = "active"  # ← the work the audit describes
         db.add(DockAssignment(...))
         write_audit(...)              # describes THOSE
         db.commit()                   # and lands with them

     5 of the 8. Excluded by requiring NO uncommitted mutation between the
     last preceding commit and the audit.

  B. The preceding commit is CONDITIONAL.

         if any(w["type"] == "ban_override_reassignment" for w in warnings):
             db.commit()      # only on one branch
         write_audit(...)     # has its own commit below

     1 of the 8. Excluded by ignoring commits nested in an `if`.

  C. A service helper whose CALLER commits. This repo's service layer
     deliberately does not commit — the same convention as `write_notification`
     and `seed_platform_notices`. 2 of the 8. Excluded by checking only
     functions that are endpoints or Celery tasks.

The documented exception (CLAUDE.md) also stays an exception: a `write_audit`
inside an `except IntegrityError` block legitimately follows a commit, because
the handler re-queries after a unique-constraint race. One real call site.
"""
from __future__ import annotations

import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP = ROOT / "backend" / "app"

#: Text that means "something was changed and not yet committed". Deliberately
#: broad: a false NEGATIVE here (treating a defect as Pattern A) is quiet, while
#: a false POSITIVE fails the build on correct code.
MUTATION_MARKERS = ("db.add(", "db.flush()", ".delete(", " = ", ".append(")


def _is_endpoint_or_task(fn: ast.AST, src: str) -> bool:
    """Only endpoints and Celery tasks own their transaction (exclusion C)."""
    for d in getattr(fn, "decorator_list", []):
        text = ast.get_source_segment(src, d) or ""
        if "router." in text or "celery_app.task" in text or ".task(" in text:
            return True
    return False


def _in_integrity_handler(node: ast.AST, parents: dict) -> bool:
    """The one documented exception, per CLAUDE.md."""
    cur = node
    while cur in parents:
        cur = parents[cur]
        if isinstance(cur, ast.ExceptHandler):
            if "IntegrityError" in ast.unparse(cur.type) if cur.type else False:
                return True
        if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return False
    return False


def _branch_path(node: ast.AST, parents: dict, fn: ast.AST) -> tuple:
    """The chain of `if` branches enclosing `node`, innermost last.

    Each entry identifies both the `if` AND which arm — `(lineno, "body")` vs
    `(lineno, "orelse")` — because a commit in the `if` and an audit in the
    `else` are never reached together.
    """
    chain = []
    cur = node
    while cur in parents:
        prev, cur = cur, parents[cur]
        if cur is fn:
            break
        if isinstance(cur, ast.If):
            arm = "body" if any(prev is st or prev in ast.walk(st)
                                for st in cur.body) else "orelse"
            chain.append((cur.lineno, arm))
    return tuple(reversed(chain))


def _commit_always_precedes(commit: ast.AST, audit: ast.AST,
                            parents: dict, fn: ast.AST) -> bool:
    """Does reaching `audit` imply `commit` already ran?

    Only then does the audit describe state that is already durable. The test is
    DIRECTIONAL, and both directions were got wrong once:

      * An absolute "is the commit conditional?" test excluded
        `adp_sync.sync_adp_employees`, whose commit AND audit sit inside the same
        `for`/`if`. Both are conditional; both are reached together; that is the
        defect.

      * A symmetric "is one chain a prefix of the other?" test then flagged
        `dispatch.trigger_dispatch`, whose commit is inside
        `if any(... ban_override ...)` while its audit is at function level. An
        empty chain is a prefix of everything, so the two compared as equal —
        but the audit runs whether or not that branch did.

    So the commit's branch chain must be a prefix of the AUDIT's, not the other
    way round: the commit may be at the same depth or shallower, never deeper.
    """
    pc = _branch_path(commit, parents, fn)
    pa = _branch_path(audit, parents, fn)
    return len(pc) <= len(pa) and pa[:len(pc)] == pc


def _check_file(path: pathlib.Path) -> list[tuple[str, int, str, str]]:
    src = path.read_text()
    if "write_audit" not in src:
        return []
    try:
        tree = ast.parse(src)
    except SyntaxError:
        # A file that does not parse is a different failure; the parse gate
        # catches it. Reporting it here would be a confusing second voice.
        return []

    parents: dict = {}
    for n in ast.walk(tree):
        for c in ast.iter_child_nodes(n):
            parents[c] = n

    lines = src.splitlines()
    out = []

    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not _is_endpoint_or_task(fn, src):
            continue

        # `ast.walk` descends into NESTED functions, and a `write_audit` inside
        # one is at the nested def's line — which may be above every commit even
        # when nobody calls it. `create_employee` does exactly this: its audit
        # lives in an `_audit_created()` closure defined before the branches.
        #
        # So a nested helper is replaced by the lines where it is CALLED. A probe
        # that deleted one of the two call sites went undetected before this,
        # because the closure's own position still satisfied "commit after audit".
        nested = {
            n.name: n for n in fn.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        nested_with_audit = {
            name for name, node in nested.items()
            if any(
                isinstance(c, ast.Call)
                and getattr(c.func, "id", getattr(c.func, "attr", "")) == "write_audit"
                for c in ast.walk(node)
            )
        }

        def _in_nested(node: ast.AST) -> bool:
            cur = node
            while cur in parents:
                cur = parents[cur]
                if cur in nested.values():
                    return True
                if cur is fn:
                    return False
            return False

        commit_nodes = [
            n for n in ast.walk(fn)
            if isinstance(n, ast.Expr)
            and ast.unparse(n).strip() == "db.commit()"
            and not _in_nested(n)
        ]

        audits = [
            n for n in ast.walk(fn)
            if isinstance(n, ast.Call)
            and getattr(n.func, "id", getattr(n.func, "attr", "")) == "write_audit"
            and not _in_integrity_handler(n, parents)
            and not _in_nested(n)
        ]
        # Plus the CALL SITES of any nested helper that audits — those are where
        # the row is actually written, so those are the lines that matter.
        for n in ast.walk(fn):
            if (isinstance(n, ast.Call)
                    and getattr(n.func, "id", "") in nested_with_audit
                    and not _in_nested(n)):
                audits.append(n)

        # A nested audit helper that nobody calls writes nothing. Flagged here
        # rather than left to Dimension 5's dead-code sweep, because this one is
        # unambiguous: a function whose whole body is a `write_audit` and which
        # has zero call sites is not scaffolding, it is a lost audit trail.
        #
        # Found by a probe that removed BOTH `_audit_created()` calls from
        # `create_employee` and saw the gate stay quiet: with no reachable
        # audit, `audits` was empty and the function was skipped entirely.
        for name in nested_with_audit:
            called = any(
                isinstance(n, ast.Call) and getattr(n.func, "id", "") == name
                for n in ast.walk(fn)
            )
            if not called:
                out.append((
                    str(path.relative_to(ROOT)), nested[name].lineno, fn.name,
                    f"{name}() contains the only write_audit and is never "
                    f"called — nothing writes an audit row for this endpoint",
                ))

        if not audits:
            continue

        audit_lines = sorted(a.lineno for a in audits)
        all_commits = [
            n.lineno for n in ast.walk(fn)
            if isinstance(n, ast.Expr) and ast.unparse(n).strip() == "db.commit()"
        ]

        # The severe case: nothing commits the row at all.
        if not [c for c in all_commits if c > max(audit_lines)]:
            out.append((
                str(path.relative_to(ROOT)), max(audit_lines), fn.name,
                "NO COMMIT AFTER THE AUDIT — the row is discarded when get_db "
                "closes the session",
            ))
            continue

        first_audit_node = min(audits, key=lambda n: n.lineno)
        first_audit = first_audit_node.lineno
        # Only commits that are reached TOGETHER with this audit (exclusion B).
        prior = [
            c.lineno for c in commit_nodes
            if c.lineno < first_audit
            and _commit_always_precedes(c, first_audit_node, parents, fn)
        ]
        if not prior:
            continue

        # Exclusion A: uncommitted work between that commit and the audit means
        # the audit rides the NEXT commit together with it.
        between = lines[max(prior):first_audit - 1]
        if any(
            m in line for line in between
            for m in MUTATION_MARKERS
            if not line.strip().startswith("#")
        ):
            continue

        out.append((
            str(path.relative_to(ROOT)), first_audit, fn.name,
            f"db.commit() at line {max(prior)} lands the state change before the "
            f"audit records it",
        ))

    return out


def main() -> int:
    hits = []
    for path in sorted(APP.rglob("*.py")):
        hits.extend(_check_file(path))

    if not hits:
        print("OK — every audit row joins the transaction it describes")
        return 0

    print(f"{len(hits)} audit row(s) written outside their transaction:\n")
    for rel, line, fn, why in hits:
        print(f"  {rel}:{line}  in {fn}()")
        print(f"      {why}\n")
    print(
        "The sequence is flush -> write_audit -> commit, so the audit row and the\n"
        "state change land together or not at all (CLAUDE.md, checklist item 3).\n"
        "If the audit legitimately describes work committed LATER in the function,\n"
        "leave the mutations between the commit and the audit — this gate reads\n"
        "that as correct (ADR-490, Pattern A)."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())

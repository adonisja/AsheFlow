#!/usr/bin/env python3
"""Every admin_create_user must pass MessageAction="SUPPRESS" (ADR-444).

The pool sends through our own SES identity
(EmailConfiguration.SourceArn = identity/asheflow.com), so Cognito's stock
template — "Your username is {username} and temporary password is {####}" —
arrives from no-reply@asheflow.com looking like something we designed. It is a
bare one-liner with a live temporary password in it and no branding at all.

ADR-444 fixed the three call sites and rejected setting the pool's
InviteMessageTemplate, on the grounds that "with both paths suppressed there is
no Cognito-sent email left to style". That reasoning holds only while EVERY
path suppresses, and nothing enforced it — a new call site added without the
kwarg silently reintroduces the stock email.

AST rather than grep: MessageAction might be on any line of a multi-line call,
and a grep for "SUPPRESS" near "admin_create_user" matches a comment about it
just as happily as the argument itself.
"""
from __future__ import annotations

import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP = ROOT / "backend" / "app"


def main() -> int:
    if not APP.exists():
        print(f"FAIL: {APP.relative_to(ROOT)} is missing.")
        return 1

    violations: list[str] = []
    checked = 0

    for path in sorted(APP.rglob("*.py")):
        src = path.read_text()
        if "admin_create_user" not in src:
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError as exc:
            print(f"FAIL: {path.relative_to(ROOT)} does not parse: {exc}")
            return 1

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if getattr(node.func, "attr", "") != "admin_create_user":
                continue
            checked += 1
            suppressed = any(
                kw.arg == "MessageAction"
                and isinstance(kw.value, ast.Constant)
                and kw.value.value == "SUPPRESS"
                for kw in node.keywords
            )
            if not suppressed:
                violations.append(
                    f"  {path.relative_to(ROOT)}:{node.lineno}: "
                    "admin_create_user without MessageAction=\"SUPPRESS\""
                )

    if violations:
        print("FAIL: Cognito would send its own unbranded email\n")
        print("\n".join(violations))
        print(
            "\nThe pool sends via our SES identity, so Cognito's stock template "
            "arrives\nfrom no-reply@asheflow.com with a live temporary password "
            "and no branding.\nSuppress it and send one of the templates in "
            "app/services/email.py (ADR-444)."
        )
        return 1

    print(f"OK: all {checked} admin_create_user call(s) suppress Cognito's email")
    return 0


if __name__ == "__main__":
    sys.exit(main())

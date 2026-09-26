#!/usr/bin/env python3
"""No literal \\uXXXX escape sequences in frontend source strings.

A Python-style "\\u2019" written into a TSX single-quoted string is not an
escape -- it is six characters, and the UI renders "account\\u2019s" to the
user. It type-checks, it builds, and only a human looking at the screen catches
it. That is exactly the failure a gate should hold.

This happens when copy is written by a script (a heredoc, an edit tool) rather
than typed: the generating language interprets the escape, the target language
does not.

JavaScript DOES interpret \\uXXXX in string literals, so this is not universally
a bug -- but in this codebase user-facing copy is written as literal characters
("don't", "→", "“"), so any \\uXXXX in a .tsx/.ts file is far more likely to be
a paste artefact than an intention. Genuine uses (regex character classes,
\\u0000 sentinels) are exempted by pattern below.
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "frontend" / "src"

# \uXXXX appearing anywhere in a line, unless the line is a regex or a
# deliberate control-character reference.
ESCAPE_RE = re.compile(r"\\u[0-9a-fA-F]{4}")
EXEMPT_RE = re.compile(r"(new RegExp|/\^|\\u00[01][0-9a-fA-F]|charCodeAt|codePointAt)")


def main() -> int:
    if not SRC.exists():
        print(f"FAIL: {SRC.relative_to(ROOT)} is missing.")
        return 1

    violations: list[str] = []
    for path in sorted([*SRC.rglob("*.ts"), *SRC.rglob("*.tsx")]):
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            if not ESCAPE_RE.search(line) or EXEMPT_RE.search(line):
                continue
            found = ESCAPE_RE.findall(line)
            violations.append(
                f"  {path.relative_to(ROOT)}:{lineno}: {', '.join(sorted(set(found)))}"
                f"\n      {line.strip()[:100]}"
            )

    if violations:
        print("FAIL: literal \\uXXXX escapes in frontend copy\n")
        print("\n".join(violations))
        print(
            "\nWrite the character itself (’ → “ ”). A Python-style escape in a "
            "TSX string\nrenders as six visible characters to the user."
        )
        return 1

    print("OK: no literal \\uXXXX escapes in frontend copy")
    return 0


if __name__ == "__main__":
    sys.exit(main())

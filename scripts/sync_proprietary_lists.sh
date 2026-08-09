#!/usr/bin/env bash
# sync_proprietary_lists.sh — regenerate .gitignore's proprietary block from
# PROPRIETARY.txt, so the two can never drift.
#
# Rewrites only the region between the markers; the rest of .gitignore is left
# byte-for-byte alone. Idempotent — running twice changes nothing.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 - "$REPO_ROOT/.gitignore" "$REPO_ROOT/PROPRIETARY.txt" <<'PY'
import os, re, sys

gitignore, manifest = sys.argv[1], sys.argv[2]
BEGIN = "# >>> PROPRIETARY (generated from PROPRIETARY.txt — do not edit by hand) >>>"
END   = "# <<< PROPRIETARY <<<"

if not os.path.exists(manifest):
    sys.exit(f"ERROR: {manifest} not found.")

paths = [l.rstrip("\n") for l in open(manifest)
         if l.strip() and not l.lstrip().startswith("#")]
if not paths:
    sys.exit("ERROR: manifest has no paths.")

block = "\n".join([BEGIN, *paths, END])
src = open(gitignore).read() if os.path.exists(gitignore) else ""

pat = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.S)
if pat.search(src):
    out = pat.sub(block, src)
else:
    out = src.rstrip("\n") + "\n\n" + block + "\n"

open(gitignore, "w").write(out)
print(f"  ✓ .gitignore proprietary block regenerated ({len(paths)} paths)")
PY

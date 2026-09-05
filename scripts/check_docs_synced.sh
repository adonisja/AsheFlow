#!/usr/bin/env bash
# check_docs_synced.sh — is local docs/ newer than the last private-repo sync?
#
# WHY THIS EXISTS
#
# docs/decisions/, docs/journals/, docs/LEARNING_GUIDE.md and CLAUDE.md are
# gitignored from the public repo and reach AsheFlow-private only through the
# pre-push hook. The hook fires on `git push`. A DESIGN-ONLY session -- an ADR
# written, a decision superseded, no code touched -- has nothing to push, so the
# hook never runs and the documentation exists on exactly one laptop.
#
# That is not hypothetical: ADR-377 was written, correct, complete, and unsynced
# until a documentation audit went looking for it. Three such audits this week
# found the artifacts present every time and the SYNC missing once. The failure
# mode is not "we forget to write docs" -- it is "writing docs does not push".
#
# So this compares mtimes rather than trusting anyone to remember.
#
# USAGE
#   bash scripts/check_docs_synced.sh          # report; exit 1 if stale
#   bash scripts/check_docs_synced.sh --quiet  # exit code only
#
# EXIT CODES
#   0  in sync, or nothing to sync
#   1  local docs are newer than the last sync  -> run the sync
#   2  never synced on this machine             -> run the sync
#
# Deliberately NOT wired into pre-push: by the time a push runs, the sync is
# about to happen anyway. This is for the case where no push is coming.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MARKER="$REPO_ROOT/.git/last_private_sync"
QUIET=false
[ "${1:-}" = "--quiet" ] && QUIET=true

say() { $QUIET || echo "$@"; }

# Everything the sync mirrors that the public repo does not track.
WATCHED=(
  "$REPO_ROOT/docs/decisions"
  "$REPO_ROOT/docs/journals"
  "$REPO_ROOT/docs/LEARNING_GUIDE.md"
  "$REPO_ROOT/CLAUDE.md"
)

newest=0
newest_file=""
for target in "${WATCHED[@]}"; do
  [ -e "$target" ] || continue
  # -newer against a reference file would be simpler, but we want to NAME the
  # file that is ahead -- "docs are stale" sends people hunting.
  while IFS= read -r f; do
    [ -f "$f" ] || continue
    m=$(stat -f %m "$f" 2>/dev/null || stat -c %Y "$f" 2>/dev/null || echo 0)
    if [ "$m" -gt "$newest" ]; then
      newest=$m
      newest_file="${f#$REPO_ROOT/}"
    fi
  done < <(find "$target" -type f ! -path '*/.git/*' 2>/dev/null)
done

if [ "$newest" -eq 0 ]; then
  say "docs-sync: nothing to sync."
  exit 0
fi

if [ ! -f "$MARKER" ]; then
  say ""
  say "docs-sync: this machine has never synced to AsheFlow-private."
  say "  newest doc: $newest_file"
  say ""
  say "  Run: bash scripts/setup_private_repo.sh --docs-only"
  say ""
  exit 2
fi

last=$(cat "$MARKER" 2>/dev/null || echo 0)

if [ "$newest" -gt "$last" ]; then
  age=$(( (newest - last) / 60 ))
  say ""
  say "docs-sync: local documentation is NEWER than the last private sync."
  say "  newest doc : $newest_file"
  say "  ahead by   : ${age} minute(s)"
  say ""
  say "  These files are gitignored from the public repo. Until they sync they"
  say "  exist only on this machine."
  say ""
  say "  Run: bash scripts/setup_private_repo.sh --docs-only"
  say ""
  exit 1
fi

say "docs-sync: up to date (docs older than the last sync)."
exit 0

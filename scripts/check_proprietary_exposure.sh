#!/usr/bin/env bash
# check_proprietary_exposure.sh — fail if anything in PROPRIETARY.txt is public.
#
# Two independent checks, because a file can leak in two different ways and
# each is silent on its own:
#
#   TRACKED   the path is in the git index right now. Every future push
#             publishes it. This is the one that caught run_sort.py,
#             persist_zones.py and sort_analysis.py — all three were being
#             synced to AsheFlow-private while ALSO sitting in the public repo.
#
#   HISTORY   the path is absent now but present in some earlier commit.
#             Gitignoring does not undo this: `git log -- <path>` still serves
#             the content to anyone who asks. Only a history rewrite removes it.
#
# Exit 1 on TRACKED (always a live defect).
# Exit 1 on HISTORY too, unless --allow-history is passed — used to gate the
# window between "classified as proprietary" and "purge executed".
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST="$REPO_ROOT/PROPRIETARY.txt"
ALLOW_HISTORY=0
[ "${1:-}" = "--allow-history" ] && ALLOW_HISTORY=1

[ -f "$MANIFEST" ] || { echo "ERROR: $MANIFEST not found."; exit 1; }

cd "$REPO_ROOT"

tracked_hits=()
history_hits=()

while IFS= read -r path; do
  case "$path" in ''|\#*) continue ;; esac

  # Directories: check the prefix rather than an exact path.
  if [[ "$path" == */ ]]; then
    if git ls-files --error-unmatch "$path" >/dev/null 2>&1 \
       || [ -n "$(git ls-files "$path" 2>/dev/null | head -1)" ]; then
      tracked_hits+=("$path")
    fi
    continue
  fi

  if git ls-files --error-unmatch "$path" >/dev/null 2>&1; then
    tracked_hits+=("$path")
  fi

  n=$(git log --all --oneline -- "$path" 2>/dev/null | wc -l | tr -d ' ')
  [ "${n:-0}" != "0" ] && history_hits+=("$path ($n commits)")
done < "$MANIFEST"

status=0

if [ ${#tracked_hits[@]} -gt 0 ]; then
  echo "FAIL: proprietary paths are TRACKED in the public repo:"
  printf '  %s\n' "${tracked_hits[@]}"
  echo ""
  echo "  Fix: git rm --cached <path> && commit."
  echo "  If it was already pushed, it is also in history — see below."
  status=1
else
  echo "OK: no proprietary path is tracked."
fi

if [ ${#history_hits[@]} -gt 0 ]; then
  echo ""
  if [ "$ALLOW_HISTORY" -eq 1 ]; then
    echo "KNOWN (--allow-history): proprietary paths still in git history:"
    printf '  %s\n' "${history_hits[@]}"
    echo "  A purge is pending. See docs/decisions/ADR-265."
  else
    echo "FAIL: proprietary paths are present in git HISTORY:"
    printf '  %s\n' "${history_hits[@]}"
    echo ""
    echo "  Gitignoring does not remove these — the content is still served by"
    echo "  'git log -- <path>'. A history rewrite is required."
    status=1
  fi
else
  echo "OK: no proprietary path appears in history."
fi

exit $status

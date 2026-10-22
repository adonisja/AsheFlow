#!/usr/bin/env bash
# Promote private `staging` to private `main`, right before a staging -> master
# merge (ADR-569).
#
# WHY
# CI pulls proprietary code from AsheFlow-private by the rule master -> main,
# everything else -> same name. The pre-push hook syncs proprietary code to
# private `staging` only, so a staging -> master PR carries public code whose
# proprietary half is still on private `staging`. check_private_branch_ready.sh
# blocks that merge (2026-08-21, 08-23 and 10-22 all hit it); this is the fix,
# made one command instead of a pasted recipe.
#
# WHY NOT IN THE PRE-PUSH HOOK
# Advancing private `main` on every push to staging would put it AHEAD of public
# `master`: a prod-only fix or a re-run on master would then pair old public
# code with newer proprietary code -- the same mismatch, reversed. Private `main`
# moves exactly when public `master` does: at the promotion.
#
# WHAT IT DOES
#   - fast-forwards private main to private staging, and ONLY a fast-forward
#     (never --force: if main has commits staging lacks, it stops and prints
#     the manual procedure, because those commits are someone's work);
#   - shows the proprietary CODE files that will change before it pushes;
#   - asks first, unless --yes.
#
# Usage: scripts/promote_private_main.sh [--yes]
set -euo pipefail

REPO="${PRIVATE_REPO:-git@github.com:adonisja/AsheFlow-private.git}"
YES=0
[ "${1:-}" = "--yes" ] && YES=1

# Must match ci.yml, setup_private_repo.sh and check_private_branch_ready.sh;
# tests/test_private_branch_mapping.py pins all of them together.
map_branch() { [ "$1" = "master" ] && echo "main" || echo "$1"; }

FROM="$(map_branch staging)"
TO="$(map_branch master)"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

if ! git clone -q --bare --filter=blob:none "$REPO" "$TMP/priv" 2>/dev/null; then
  echo "Could not clone the private repo ($REPO)." >&2
  exit 1
fi
G() { git -C "$TMP/priv" "$@"; }

FROM_SHA="$(G rev-parse --verify -q "refs/heads/$FROM")" || { echo "No private '$FROM' branch." >&2; exit 1; }
TO_SHA="$(G rev-parse --verify -q "refs/heads/$TO")"     || { echo "No private '$TO' branch." >&2; exit 1; }

echo "private ${FROM} ${FROM_SHA:0:7} -> ${TO} ${TO_SHA:0:7}"

if [ "$FROM_SHA" = "$TO_SHA" ]; then
  echo "Private '${TO}' is already at '${FROM}'. Nothing to promote."
  exit 0
fi

if ! G merge-base --is-ancestor "$TO_SHA" "$FROM_SHA"; then
  cat >&2 <<MSG
Private '${TO}' has commits that '${FROM}' does not, so this is not a
fast-forward and the script will not force it. Those commits:
$(G log --oneline "${FROM_SHA}..${TO_SHA}" | head -10 | sed 's/^/  /')

Decide what to keep, then follow the manual sync printed by
scripts/check_private_branch_ready.sh (it archives '${TO}' under a tag first).
MSG
  exit 2
fi

COMMITS="$(G rev-list --count "${TO_SHA}..${FROM_SHA}")"
CODE="$(G diff --name-only "${TO_SHA}" "${FROM_SHA}" -- \
  backend/app backend/tests backend/asheflow_private asheflow_private)"
echo "${COMMITS} commit(s) to promote. Proprietary code files that change on '${TO}':"
if [ -n "$CODE" ]; then echo "$CODE" | sed 's/^/  /'; else echo "  (none: docs only)"; fi

if [ "$YES" -ne 1 ]; then
  read -r -p "Fast-forward private '${TO}' to '${FROM}'? [y/N] " ok
  [ "$ok" = "y" ] || { echo "Not promoted."; exit 1; }
fi

# A plain push: it is refused if '${TO}' moved since the clone, which is the
# only race that matters here.
G push -q origin "${FROM_SHA}:refs/heads/${TO}"
echo "Promoted: private '${TO}' is now ${FROM_SHA:0:7}. Re-run the PR's 'Private branch ready for merge' check."

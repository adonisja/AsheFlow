#!/usr/bin/env bash
# Fail a PR when the private branch its BASE maps to is behind the one its HEAD
# maps to.
#
# WHY THIS EXISTS
# ---------------
# CI pulls proprietary code from AsheFlow-private, mapping the public branch to
# a private one: master -> main, everything else -> same name. The pre-push hook
# syncs proprietary code to private `staging` only.
#
# So a staging -> master PR carries the public tests but NOT the proprietary
# source they exercise. The PR goes green, the merge is clean, and `Deploy →
# PROD` is then skipped because Backend tests fail on master against stale
# proprietary code.
#
# That has now happened twice:
#   2026-08-21  ImportError: cannot import name 'WalkerRoute'   (a stale rename)
#   2026-08-23  AttributeError: no attribute '_handle_driver_decline'
#
# Both were found AFTER the merge landed. This check moves the discovery before
# it, where the fix is one sync instead of a merge to unpick.
#
# Usage: check_private_branch_ready.sh <base-branch> <head-branch>
set -uo pipefail

BASE="${1:?usage: $0 <base-branch> <head-branch>}"
HEAD_BRANCH="${2:?usage: $0 <base-branch> <head-branch>}"
REPO="${PRIVATE_REPO:-git@github.com:adonisja/AsheFlow-private.git}"

# Must match the mapping in ci.yml and scripts/setup_private_repo.sh. Three
# copies of one rule is itself a risk; the test suite pins them together.
map_branch() { [ "$1" = "master" ] && echo "main" || echo "$1"; }

BASE_PRIV="$(map_branch "$BASE")"
HEAD_PRIV="$(map_branch "$HEAD_BRANCH")"

echo "public  ${HEAD_BRANCH} -> ${BASE}"
echo "private ${HEAD_PRIV} -> ${BASE_PRIV}"

if [ "$BASE_PRIV" = "$HEAD_PRIV" ]; then
  echo "Both sides map to the same private branch — nothing to compare."
  exit 0
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

if ! git clone -q --bare --filter=blob:none "$REPO" "$TMP/priv" 2>/dev/null; then
  echo "::error::Could not clone the private repo to verify branch readiness."
  echo "Check PRIVATE_REPO_DEPLOY_KEY is present and valid for this job."
  exit 1
fi

for b in "$BASE_PRIV" "$HEAD_PRIV"; do
  if ! git -C "$TMP/priv" rev-parse --verify -q "refs/heads/$b" >/dev/null; then
    # A feature branch with no private counterpart falls back to staging at pull
    # time, which is the documented behaviour — not a drift condition.
    echo "Private branch '$b' does not exist; the pull falls back to staging. Skipping."
    exit 0
  fi
done

BEHIND="$(git -C "$TMP/priv" rev-list --count "${BASE_PRIV}..${HEAD_PRIV}")"

# Only CODE drift can fail a deploy. The private repo also carries docs/ — ADRs,
# journals, templates — which the pre-push hook syncs on every push, so the
# branches diverge by documentation within minutes of any commit. Failing a PR
# over a journal file is friction that gets a check disabled, and a disabled
# check catches nothing.
#
# Scope to what CI actually pulls: routers, services, asheflow_private, and the
# proprietary tests (see the copy step in ci.yml).
CODE_DRIFT="$(git -C "$TMP/priv" diff --name-only "${BASE_PRIV}..${HEAD_PRIV}" -- \
  backend/app backend/tests backend/asheflow_private asheflow_private 2>/dev/null | wc -l | tr -d ' ')"

if [ "$BEHIND" -eq 0 ] || [ "$CODE_DRIFT" -eq 0 ]; then
  if [ "$BEHIND" -gt 0 ]; then
    echo "Private '${BASE_PRIV}' is ${BEHIND} commit(s) behind, but no CODE differs —"
    echo "docs only, which CI does not pull. Safe to merge."
  else
    echo "Private '${BASE_PRIV}' is up to date with '${HEAD_PRIV}'. Safe to merge."
  fi
  exit 0
fi

echo "::error::Private '${BASE_PRIV}' is missing ${CODE_DRIFT} proprietary code file(s) from '${HEAD_PRIV}'."
cat <<MSG

Merging this PR puts public code from '${HEAD_BRANCH}' onto '${BASE}', where CI
pulls proprietary code from private '${BASE_PRIV}' — which is missing the files
below. Backend tests would fail on '${BASE}' AFTER the merge, and the deploy
would be skipped.

Proprietary code files that differ:
MSG
git -C "$TMP/priv" diff --name-only "${BASE_PRIV}..${HEAD_PRIV}" -- \
  backend/app backend/tests backend/asheflow_private asheflow_private | head -20 | sed 's/^/  /'

cat <<MSG

To fix, sync the private branch, then re-run this check:

  git clone -b ${HEAD_PRIV} ${REPO} /tmp/priv && cd /tmp/priv
  git checkout -B sync origin/${HEAD_PRIV}
  # keep any files that exist only on ${BASE_PRIV}:
  git checkout origin/${BASE_PRIV} -- \$(git diff --diff-filter=D --name-only origin/${BASE_PRIV} origin/${HEAD_PRIV})
  git commit -m "sync ${BASE_PRIV} with ${HEAD_PRIV}"
  git tag archive/private-${BASE_PRIV}-\$(date +%Y-%m-%d) origin/${BASE_PRIV}
  git push origin archive/private-${BASE_PRIV}-\$(date +%Y-%m-%d)
  git push --force-with-lease origin sync:${BASE_PRIV}
MSG
exit 1

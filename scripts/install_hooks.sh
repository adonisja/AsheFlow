#!/usr/bin/env bash
# install_hooks.sh
#
# Installs git hooks for the AsheFlow repo.
# Run once after cloning or when hooks change:
#
#   bash scripts/install_hooks.sh
#
# Hooks installed:
#   pre-push — checks ADR documentation coverage, then syncs proprietary files
#              to AsheFlow-private. Coverage runs first so a push that is about
#              to be rejected does not publish docs the public repo lacks.
#              Aborts the push if the sync fails so the two repos stay in lockstep.
#
# NOT covered by any hook, on purpose: a design-only session. An ADR written with
# no code change has nothing to push, so pre-push never fires and the doc stays
# on one machine (this is how ADR-377 went unsynced). For that case:
#
#   bash scripts/check_docs_synced.sh          # am I ahead of the private repo?
#   bash scripts/setup_private_repo.sh --docs-only
#
# A hook cannot catch it -- there is no git event to hang off when nothing is
# committed.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOOKS_DIR="$REPO_ROOT/.git/hooks"

if [ ! -d "$HOOKS_DIR" ]; then
  echo "ERROR: .git/hooks directory not found. Are you in a git repo?"
  exit 1
fi

# ── pre-push ─────────────────────────────────────────────────────────────────
cat > "$HOOKS_DIR/pre-push" << 'HOOK'
#!/usr/bin/env bash
# Pre-push hook: sync proprietary files to AsheFlow-private before every push.
# Abort the push if the sync fails — prevents public and private repos drifting.

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"

# git writes "<local ref> <local sha> <remote ref> <remote sha>" to our stdin.
# It can only be read once, so capture it up front.
STDIN_PAYLOAD="$(cat)"

# ADR coverage (ADR-366). The three-artifact rule has been in CLAUDE.md the whole
# time and was skipped twice in three days, the second time after its own lesson
# had been written -- so it is enforced here rather than remembered.
#
# Runs BEFORE the sync: a push about to be rejected should not first publish
# documentation to the private repo. Placed above the sync-script guard below,
# which exits 0 and would otherwise skip this entirely.
COVERAGE="$REPO_ROOT/scripts/check_adr_coverage.py"
if [ -f "$COVERAGE" ] && [ "${ALLOW_UNDOCUMENTED:-}" != "1" ]; then
  if ! python3 "$COVERAGE" <<< "$STDIN_PAYLOAD"; then
    echo ""
    echo "Push aborted: documentation is missing for a cited ADR."
    exit 1
  fi
fi
SYNC_SCRIPT="$REPO_ROOT/scripts/setup_private_repo.sh"

if [ ! -f "$SYNC_SCRIPT" ]; then
  echo "pre-push: sync script not found at $SYNC_SCRIPT — skipping."
  exit 0
fi

echo "pre-push: syncing proprietary files to AsheFlow-private..."
bash "$SYNC_SCRIPT"

if [ $? -ne 0 ]; then
  echo ""
  echo "ERROR: private repo sync failed. Push aborted."
  echo "Fix the sync error above, then re-run git push."
  exit 1
fi

echo "pre-push: sync complete."
exit 0
HOOK

chmod +x "$HOOKS_DIR/pre-push"
echo "✓ pre-push hook installed at $HOOKS_DIR/pre-push"

echo ""
echo "Done. Every git push will now sync proprietary files to AsheFlow-private"
echo "before the push completes. The push is aborted if the sync fails."

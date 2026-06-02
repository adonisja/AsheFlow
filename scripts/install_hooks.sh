#!/usr/bin/env bash
# install_hooks.sh
#
# Installs git hooks for the AsheFlow repo.
# Run once after cloning or when hooks change:
#
#   bash scripts/install_hooks.sh
#
# Hooks installed:
#   pre-push — syncs proprietary files to AsheFlow-private before every push.
#              Aborts the push if the sync fails so the two repos stay in lockstep.

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

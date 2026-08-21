#!/usr/bin/env bash
# Dated tarball of the docs vault, independent of git and of AsheFlow-private.
# Offline safety net: if the vault repo is corrupted or a bad bulk edit is
# committed and pushed everywhere, these archives still have yesterday's copy.
#
# Install (runs daily at 13:00):
#   cp scripts/com.asheflow.docsbackup.plist ~/Library/LaunchAgents/
#   launchctl load ~/Library/LaunchAgents/com.asheflow.docsbackup.plist
set -euo pipefail

VAULT="${VAULT:-$HOME/Documents/ClassAssignments/GitHub_Projects/AsheFlow/docs}"
DEST="${DEST:-$HOME/Backups/asheflow-docs}"
KEEP="${KEEP:-30}"

[ -d "$VAULT" ] || { echo "vault not found: $VAULT" >&2; exit 1; }
mkdir -p "$DEST"

STAMP=$(date +%Y%m%d-%H%M%S)
ARCHIVE="$DEST/asheflow-docs-$STAMP.tgz"

# Excludes editor state and the plugin binary; keeps .git so history travels
# with the archive.
tar --exclude='.obsidian/workspace.json' \
    --exclude='.obsidian/plugins/*/main.js' \
    --exclude='.DS_Store' \
    -czf "$ARCHIVE" -C "$(dirname "$VAULT")" "$(basename "$VAULT")"

# Verify the archive is readable before trusting it and pruning older ones.
if ! tar -tzf "$ARCHIVE" >/dev/null 2>&1; then
  echo "archive failed verification, removing: $ARCHIVE" >&2
  rm -f "$ARCHIVE"
  exit 1
fi

COUNT=$(tar -tzf "$ARCHIVE" | grep -c '\.md$' || true)
echo "$(date '+%F %T')  $ARCHIVE  ($(du -h "$ARCHIVE" | cut -f1), $COUNT markdown files)"

# Prune all but the newest $KEEP archives.
ls -1t "$DEST"/asheflow-docs-*.tgz 2>/dev/null | tail -n +$((KEEP + 1)) | while read -r old; do
  rm -f "$old"
  echo "pruned $(basename "$old")"
done

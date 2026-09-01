#!/usr/bin/env bash
# Runs the backup and reports the outcome to the PlatformAlert board (ADR-344 D5).
#
# Split from asheflow-db-backup.sh so the dump does not depend on the backend
# container being healthy: if the app is down, the backup must still run, and the
# reporting step is what degrades.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="${BACKEND:-asheflow_backend}"

"$SCRIPT_DIR/asheflow-db-backup.sh"
RC=$?

# Resolve on success, raise on failure. Self-resolve reuses ADR-335 D3: the
# natural close for "backups are failing" is "a backup succeeded", not a click.
if [ "$RC" -eq 0 ]; then
  ACTION="clear"
else
  ACTION="raise"
fi
# Write the reporting step to a file rather than inlining a heredoc after a
# `||` handler: `cmd <<'EOF' || { ... }` binds the brace block BEFORE the
# heredoc body, so the Python is swallowed as shell text and the alert silently
# never runs -- precisely the failure this alerting exists to prevent.
REPORTER=$(mktemp)
trap 'rm -f "$REPORTER"' EXIT

cat > "$REPORTER" <<'PYEOF'
import os
from app.database import SessionLocal
from app.services.integration_alerts import (
    BACKUP_FAILED, BACKUP_FAILED_MESSAGE,
    raise_platform_alert, clear_integration_alert,
)

db = SessionLocal()
try:
    if os.environ["ACTION"] == "clear":
        n = clear_integration_alert(db, alert_type=BACKUP_FAILED, company_id=None)
        print(f"  backup alert cleared: {n}")
    else:
        raise_platform_alert(
            db,
            alert_type=BACKUP_FAILED,
            company_id=None,
            message=BACKUP_FAILED_MESSAGE,
            severity="critical",
        )
        print("  backup alert raised")
    db.commit()
finally:
    db.close()
PYEOF

if ! docker exec -i -e ACTION="$ACTION" "$BACKEND" python3 - < "$REPORTER"; then
  echo "$(date '+%F %T')  WARNING: could not reach $BACKEND to report backup status" >&2
fi

exit "$RC"

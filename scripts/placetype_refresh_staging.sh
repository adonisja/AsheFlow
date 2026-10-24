#!/usr/bin/env bash
# ADR-583 D1 — refresh staging's PlaceType replica from prod's master.
# Run on the OWNER'S machine (needs SSM on both servers and S3 read on the
# backup bucket, to sign the download link):
#
#   bash scripts/placetype_refresh_staging.sh
#
# 1. prod: dump PlaceType and upload it to s3://asheflow-db-backups/prod/placetype/
# 2. here: sign a 1-hour GET link for that object
# 3. staging: download, restore into its placetype database, print the counts
set -euo pipefail
PROD=i-095bf2ed310c86741
STAGING=i-0adb5030b967854b2
REPO=/home/ubuntu/AsheFlow
HERE="$(cd "$(dirname "$0")" && pwd)"
# Ship THIS checkout's refresh script with each command, so it works whatever
# version of the code a server is on (prod waits for its seed before a merge).
B64=$(base64 < "$HERE/placetype_refresh.sh" | tr -d '\n')
REFRESH="echo $B64 | base64 -d > /tmp/placetype_refresh.sh && REPO_DIR=$REPO bash /tmp/placetype_refresh.sh"

run() {   # instance, command → stdout (fails on a failed command)
  local id cmd status
  cmd=$(python3 -c 'import json,sys; print(json.dumps({"commands":[sys.argv[1]]}))' "cd $REPO && $2")
  id=$(aws ssm send-command --instance-ids "$1" --document-name AWS-RunShellScript \
        --parameters "$cmd" --timeout-seconds 3600 --query Command.CommandId --output text)
  for _ in $(seq 1 600); do
    status=$(aws ssm get-command-invocation --command-id "$id" --instance-id "$1" --query Status --output text 2>/dev/null || true)
    case "$status" in Success|Failed|Cancelled|TimedOut) break ;; esac; sleep 3
  done
  aws ssm get-command-invocation --command-id "$id" --instance-id "$1" --query StandardOutputContent --output text
  [ "$status" = Success ] || { aws ssm get-command-invocation --command-id "$id" --instance-id "$1" \
                                  --query StandardErrorContent --output text >&2; return 1; }
}

echo "1/3 dumping prod…"
OUT=$(run "$PROD" "$REFRESH dump")
echo "$OUT" | grep '^size:'
KEY=$(echo "$OUT" | sed -n 's/^key: //p')
[ -n "$KEY" ] || { echo "no key from prod"; exit 1; }
echo "2/3 signing a 1-hour link for $KEY"
URL=$(aws s3 presign "s3://asheflow-db-backups/$KEY" --expires-in 3600)
echo "3/3 restoring on staging…"
run "$STAGING" "$REFRESH restore '$URL'"

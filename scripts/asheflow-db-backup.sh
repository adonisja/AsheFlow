#!/usr/bin/env bash
# Nightly verified Postgres dump -> local disk -> S3 (ADR-344).
#
# Postgres runs in-container on a Docker volume, so there are no RDS snapshots.
# A dump kept only on this box dies with the box; S3 is the copy that survives.
#
# The instance role has PutObject on its own prefix and nothing else (ADR-344 D2),
# so this script cannot read its uploads back or prune S3 -- expiry is a bucket
# lifecycle rule, and verification happens locally, before upload.
#
# Install: see docs/runbooks/prod-backups.md
set -euo pipefail

ENVIRONMENT="${ENVIRONMENT:-prod}"
BUCKET="${BUCKET:-asheflow-db-backups}"
DEST="${DEST:-/home/ubuntu/backups}"
KEEP_DAYS="${KEEP_DAYS:-14}"
CONTAINER="${CONTAINER:-asheflow_postgres}"
REGION="${REGION:-us-east-2}"
ENV_FILE="${ENV_FILE:-/home/ubuntu/AsheFlow/.env}"

log() { echo "$(date '+%F %T')  $*"; }
fail() { log "FAILED: $*"; exit 1; }

# Credentials come from the container's own environment, never the command line,
# where they would be visible in `ps` to any user on the box (ADR-344, Dim 6).
PGUSER=$(grep -E '^POSTGRES_USER=' "$ENV_FILE" | cut -d= -f2-)
PGDB=$(grep -E '^POSTGRES_DB=' "$ENV_FILE" | cut -d= -f2-)
PGPASS=$(grep -E '^POSTGRES_PASSWORD=' "$ENV_FILE" | cut -d= -f2-)
: "${PGUSER:?POSTGRES_USER not found in $ENV_FILE}"
: "${PGDB:?POSTGRES_DB not found in $ENV_FILE}"
: "${PGPASS:?POSTGRES_PASSWORD not found in $ENV_FILE}"

docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null | grep -qx true \
  || fail "container $CONTAINER is not running"

mkdir -p "$DEST"
STAMP=$(date -u +%Y%m%d-%H%M%S)
NAME="asheflow-${ENVIRONMENT}-${STAMP}.sql.gz"
ARCHIVE="$DEST/$NAME"

# --clean --if-exists so the dump can be replayed into a non-empty database.
# PGPASSWORD via -e, never on the command line where `ps` would expose it.
# Required because pg_hba.conf differs by environment: prod's `local ... trust`
# lets docker exec in without one, staging's `local all all md5` does not. A
# script that works only where trust happens to be configured is not portable,
# and the failure looks like a hang waiting on a password prompt.
docker exec -e PGPASSWORD="$PGPASS" "$CONTAINER" \
  pg_dump -U "$PGUSER" -d "$PGDB" --clean --if-exists \
  | gzip -9 > "$ARCHIVE" || fail "pg_dump failed"

# ---- Verify before trusting it (ADR-344 D3) ------------------------------
# pg_dump exiting 0 does not prove the file is usable: a truncated write or a
# full disk still leaves a plausible-looking archive.
gzip -t "$ARCHIVE" 2>/dev/null || fail "archive is truncated or corrupt: $ARCHIVE"

# NOTE: `gunzip -c f | grep -q` exits non-zero even on a GOOD dump -- grep -q
# closes the pipe on its first match, gunzip dies of SIGPIPE, and `set -o
# pipefail` surfaces that as failure. Count with grep -c over the whole stream
# instead, so nothing closes the pipe early. A false failure here is worse than
# no check: it would raise a critical alert every night on healthy backups.
TABLES=$(gunzip -c "$ARCHIVE" | grep -c 'CREATE TABLE' || true)
[ "${TABLES:-0}" -gt 0 ] \
  || fail "no CREATE TABLE in dump -- schema missing: $ARCHIVE"

# A dump that cannot say which migration it matches is nearly useless in a
# restore, because it cannot be lined up against a code revision.
# Assert the migration ROW, not merely that the table was created. A dump
# containing an empty alembic_version still cannot be lined up against a code
# revision, and that is the case worth catching -- matching the CREATE TABLE
# line alone would pass it.
# 2>/dev/null on gunzip: awk exits at the first data row, so gunzip takes a
# SIGPIPE and prints "gzip: stdout: Broken pipe". Harmless, but it looks like an
# error in journald, and an operator who learns to ignore noise in this log will
# ignore a real failure too.
REVISION=$(gunzip -c "$ARCHIVE" 2>/dev/null \
  | awk '/^COPY public.alembic_version /{f=1;next} f&&/^\\\.$/{exit} f{print;exit}' \
  | tr -d '[:space:]' || true)
[ -n "$REVISION" ] \
  || fail "alembic_version has no row -- dump cannot be matched to a migration: $ARCHIVE"

SIZE=$(du -h "$ARCHIVE" | cut -f1)
log "dump verified: $NAME ($SIZE, $TABLES tables, migration $REVISION)"

# ---- Off-box copy --------------------------------------------------------
aws s3 cp "$ARCHIVE" "s3://${BUCKET}/${ENVIRONMENT}/${NAME}" \
  --region "$REGION" --only-show-errors \
  || fail "upload to s3://${BUCKET}/${ENVIRONMENT}/ failed"
log "uploaded to s3://${BUCKET}/${ENVIRONMENT}/${NAME}"

# ---- Prune local copies (S3 expiry is a lifecycle rule) -------------------
find "$DEST" -name "asheflow-${ENVIRONMENT}-*.sql.gz" -type f -mtime +"$KEEP_DAYS" -print -delete \
  | while read -r old; do log "pruned local $(basename "$old")"; done

log "backup complete"

#!/usr/bin/env bash
# ADR-583 D1 / ADR-409 D6 — copy PlaceType's master (prod) into a replica.
# Runs ON a server, from the repo root:
#
#   bash scripts/placetype_refresh.sh dump              # prod: dump + upload, prints the S3 key
#   bash scripts/placetype_refresh.sh restore '<url>'   # replica: download + restore + check
#
# The replica never connects to prod (ADR-409 D6). Prod uploads with the
# PutObject it already holds on asheflow-db-backups/prod/*; the owner's machine
# signs a short-lived GET URL (scripts/placetype_refresh_staging.sh does all three).
# PlaceType is public city geography with nothing tenant-derived (ADR-580), which
# is what makes a replica on staging acceptable.
set -euo pipefail
cd "${REPO_DIR:-$(dirname "$0")/..}"
PGUSER="$(grep -E '^POSTGRES_USER=' .env 2>/dev/null | cut -d= -f2- || true)"; PGUSER="${PGUSER:-asheflow}"
BUCKET="asheflow-db-backups"
DUMP=/tmp/placetype.dump
# Postgres tools inside the container, authenticated with the password the
# container already holds (POSTGRES_PASSWORD). Staging's socket requires it;
# prod's happened not to. Nothing reaches a host command line.
pgx() { local tool="$1"; shift; docker exec -i asheflow_postgres sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" exec "$0" "$@"' "$tool" "$@"; }

case "${1:-}" in
  dump)
    pgx pg_dump -U "$PGUSER" -d placetype -Fc --no-owner --no-privileges \
      -t building_profile_library -t street_segments > "$DUMP"
    KEY="prod/placetype/placetype-$(date -u +%Y%m%dT%H%M%SZ).dump"
    aws s3 cp --only-show-errors "$DUMP" "s3://$BUCKET/$KEY"
    echo "size: $(du -h "$DUMP" | cut -f1)"
    rm -f "$DUMP"
    echo "key: $KEY"
    ;;
  restore)
    URL="${2:?usage: $0 restore '<presigned url>'}"
    [ -s .placetype-writer.env ] || { echo "run scripts/placetype_db_setup.sh on this server first"; exit 1; }
    curl -fsS -o "$DUMP" "$URL"
    pgx pg_restore -U "$PGUSER" -d placetype --clean --if-exists \
      --no-owner --role=placetype_writer --single-transaction < "$DUMP"
    rm -f "$DUMP"
    # Tables re-created by the writer pick up its default privileges; re-grant anyway.
    pgx psql -U "$PGUSER" -d placetype -qc \
      "GRANT SELECT ON ALL TABLES IN SCHEMA public TO placetype_reader"
    pgx psql -U "$PGUSER" -d placetype -qtAc \
      "select 'doors', count(*), count(geo_enriched_at) from building_profile_library
       union all select 'segments', count(*), count(from_lion_node_id) from street_segments"
    ;;
  *) echo "usage: $0 dump | restore '<presigned url>'"; exit 2 ;;
esac

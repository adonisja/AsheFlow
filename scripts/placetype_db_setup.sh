#!/usr/bin/env bash
# ADR-583 D2 — create PlaceType's own database and its two roles. Owner-run,
# ON the server, from the repo root:
#
#     bash scripts/placetype_db_setup.sh              # create; API not switched yet
#     bash scripts/placetype_db_setup.sh --activate   # also point the API at the reader
#
# - placetype_writer owns the tables; only the seed uses it. Its URL goes to
#   .placetype-writer.env (mode 600), which docker compose never loads, so the
#   API and Celery never hold the write credential.
# - placetype_reader has CONNECT + SELECT only. Its URL goes to
#   .placetype-reader.env, and with --activate into backend/.env as
#   PLACETYPE_DATABASE_URL (then recreate backend/celery: a restart keeps the old env).
#
# Passwords are generated here, sent to psql on stdin, and never printed.
# Idempotent: existing roles and database are kept (pass --rotate to reset the
# passwords).
set -euo pipefail
cd "$(dirname "$0")/.."

ACTIVATE=0; ROTATE=0
for a in "$@"; do
  case "$a" in --activate) ACTIVATE=1 ;; --rotate) ROTATE=1 ;; *) echo "unknown flag $a"; exit 2 ;; esac
done

PGUSER="$(grep -E '^POSTGRES_USER=' .env 2>/dev/null | cut -d= -f2- || true)"; PGUSER="${PGUSER:-asheflow}"
PSQL=(docker exec -i asheflow_postgres psql -v ON_ERROR_STOP=1 -qtA -U "$PGUSER")

role_exists() { [ "$("${PSQL[@]}" -d postgres -c "SELECT 1 FROM pg_roles WHERE rolname='$1'")" = "1" ]; }
db_exists()   { [ "$("${PSQL[@]}" -d postgres -c "SELECT 1 FROM pg_database WHERE datname='placetype'")" = "1" ]; }

ensure_role() {   # name, env file, env var
  local name="$1" file="$2" var="$3" pw
  if role_exists "$name" && [ "$ROTATE" = 0 ] && [ -s "$file" ]; then
    echo "role $name exists; keeping it"; return
  fi
  pw="$(openssl rand -hex 24)"
  if role_exists "$name"; then
    printf "ALTER ROLE %s LOGIN PASSWORD '%s';\n" "$name" "$pw" | "${PSQL[@]}" -d postgres
  else
    printf "CREATE ROLE %s LOGIN PASSWORD '%s';\n" "$name" "$pw" | "${PSQL[@]}" -d postgres
  fi
  umask 077
  printf '%s=postgresql://%s:%s@postgres:5432/placetype\n' "$var" "$name" "$pw" > "$file"
  chmod 600 "$file"
  echo "role $name ready; URL written to $file"
}

ensure_role placetype_writer .placetype-writer.env PLACETYPE_WRITER_URL
ensure_role placetype_reader .placetype-reader.env PLACETYPE_DATABASE_URL

if db_exists; then
  echo "database placetype exists; keeping it"
else
  "${PSQL[@]}" -d postgres -c "CREATE DATABASE placetype OWNER placetype_writer"
  echo "database placetype created"
fi

"${PSQL[@]}" -d placetype <<'SQL'
REVOKE ALL ON DATABASE placetype FROM PUBLIC;
GRANT CONNECT ON DATABASE placetype TO placetype_reader, placetype_writer;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO placetype_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO placetype_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE placetype_writer IN SCHEMA public GRANT SELECT ON TABLES TO placetype_reader;
SQL
echo "grants applied: reader = CONNECT + SELECT"

if [ "$ACTIVATE" = 1 ]; then
  touch backend/.env
  grep -v '^PLACETYPE_DATABASE_URL=' backend/.env > backend/.env.tmp || true
  cat .placetype-reader.env >> backend/.env.tmp
  mv backend/.env.tmp backend/.env
  # `docker restart` keeps a container's original environment, so it would NOT
  # pick this up; the containers must be recreated.
  echo "backend/.env now points the API at the reader. Recreate (a restart is not enough):"
  echo "  docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --force-recreate --no-deps backend celery_worker celery_beat"
fi

# The check: the reader must be refused a write.
READER_URL="$(cut -d= -f2- .placetype-reader.env)"
if docker exec -i asheflow_postgres psql "$READER_URL" -v ON_ERROR_STOP=1 -qc \
     "CREATE TABLE adr583_probe (x int)" >/dev/null 2>&1; then
  docker exec -i asheflow_postgres psql "$READER_URL" -qc "DROP TABLE adr583_probe" >/dev/null 2>&1 || true
  echo "FAIL: the reader role could create a table"; exit 1
fi
echo "check passed: the reader role is refused a write"

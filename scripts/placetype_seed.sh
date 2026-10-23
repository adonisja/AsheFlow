#!/usr/bin/env bash
# ADR-583 D6 — run the city seed as its own container. Owner-run, ON the
# server, from the repo root:
#
#     bash scripts/placetype_seed.sh schema addresspoint            # ~10 min
#     bash scripts/placetype_seed.sh geoclient --limit 200           # trial
#     bash scripts/placetype_seed.sh geoclient nodes                 # ~22h
#     docker logs -f placetype_seed                                  # progress (counts only)
#
# A plain `docker run`, NOT `docker compose run`: every deploy does
# `compose down --remove-orphans`, which would kill a compose-run container
# mid-pass. This one is outside the project, and its loop restarts the stage
# (each stage is resumable) after a deploy restarts postgres.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -s .placetype-writer.env ] || { echo "run scripts/placetype_db_setup.sh first"; exit 1; }
[ $# -ge 1 ] || { echo "usage: $0 <stage>... [--limit N]"; exit 2; }

IMAGE="$(docker inspect asheflow_backend --format '{{.Config.Image}}')"
NET="$(docker inspect asheflow_postgres --format '{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{end}}')"
docker rm -f placetype_seed >/dev/null 2>&1 || true

# Values come from env files, so no credential appears in the command line.
docker run -d --name placetype_seed --network "$NET" \
  --env-file backend/.env --env-file .placetype-writer.env \
  -e PLACETYPE_DATABASE_URL= \
  "$IMAGE" sh -c 'n=0; until python -m app.placetype.seed "$@"; do n=$((n+1)); [ "$n" -ge 30 ] && { echo "seed failed 30 times; giving up"; exit 1; }; echo "seed exited; retry $n in 60s"; sleep 60; done' \
  seed "$@"
echo "started placetype_seed ($*). Follow with: docker logs -f placetype_seed"

#!/bin/bash
# Usage:
#   ./start.sh          — Docker stack + web frontend (Vite)
#   ./start.sh mobile   — Docker stack + iOS simulator + Metro bundler
#   ./start.sh --mobile — same as above

cd "$(dirname "$0")"

echo "Starting AsheFlow backend stack (Postgres, Redis, FastAPI, Bot, Celery)..."
if ! docker compose up -d; then
  echo ""
  echo "ERROR: docker-compose failed. Check that .env exists at the project root and contains all required variables (see .env.example)."
  exit 1
fi

# Wait until the backend is accepting connections before handing off to the
# dev server. Avoids "connection refused" errors on first API call after boot.
echo "Waiting for backend to be ready..."
until curl -sf http://localhost:8000/health > /dev/null 2>&1; do
  sleep 1
done
echo "Backend is up."
echo ""

if [ "${1}" = "mobile" ] || [ "${1}" = "--mobile" ]; then
  echo "Launching iPhone 16 Pro simulator and installing app..."
  cd mobile

  # Kill any stale Metro process on 8081 before starting a fresh one.
  STALE=$(lsof -ti tcp:8081 2>/dev/null)
  if [ -n "$STALE" ]; then
    echo "Killing stale Metro process on port 8081..."
    kill -9 $STALE 2>/dev/null
    sleep 1
  fi

  npx react-native start --reset-cache &
  METRO_PID=$!

  echo "Waiting for Metro to be ready..."
  until curl -sf http://localhost:8081/status > /dev/null 2>&1; do
    sleep 1
  done
  echo "Metro is up."
  echo ""

  echo "Building and launching on iPhone 16 Pro..."
  npx react-native run-ios --simulator "iPhone 16 Pro"

  # Keep Metro in the foreground after the build so hot reload keeps working.
  echo ""
  echo "App launched. Metro is running — press ^C to stop."
  wait $METRO_PID
else
  echo "Starting AsheFlow web frontend (Vite)..."
  echo "Press ^C to stop the frontend server."
  echo ""
  cd frontend && npm run dev
fi

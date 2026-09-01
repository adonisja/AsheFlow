#!/bin/bash
# Usage:
#   ./start.sh                    — Docker stack + web frontend (Vite)
#   ./start.sh ios [Simulator]    — Docker stack + Metro + iOS app (default: iPhone 16 Pro)
#   ./start.sh android [AVD]      — Docker stack + Metro + Android app (boots AVD if none running)
#   ./start.sh mobile             — legacy alias for `ios`
#
# Each platform also accepts its dashed spellings (-ios/--ios, -android/--android,
# -web/--web). Anything else exits 1 with usage — an unrecognised argument used to
# fall through to the web branch, so `-ios` silently started Vite and the simulator
# never opened. Invoke as ./start.sh, not `sh start.sh`: the latter ignores the
# shebang above and runs under /bin/sh, where the bashisms here aren't guaranteed.

cd "$(dirname "$0")"

PLATFORM="${1:-web}"
DEVICE_ARG="${2:-}"

echo "Starting AsheFlow backend stack (Postgres, Redis, FastAPI, Bot, Celery)..."
# The dev overlay is REQUIRED, not optional: docker-compose.yml alone exposes
# 8000 only on the Docker network (for Caddy) and never publishes it to the
# host, so the readiness check below — and the mobile app, which targets
# http://<LAN_IP>:8000 — both find nothing listening. It also enables --reload.
if ! docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d; then
  echo ""
  echo "ERROR: docker-compose failed. Check that .env exists at the project root and contains all required variables (see .env.example)."
  exit 1
fi

# Wait until the backend is accepting connections before handing off to the
# dev server. Avoids "connection refused" errors on first API call after boot.
echo "Waiting for backend to be ready..."
# Bounded. An unbounded loop here hangs forever on a backend that will never
# come up (bad .env, failed migration, unpublished port) with no clue why —
# the failure looks like a hung script rather than a broken container.
# 60s was too tight: a cold start runs migrations before uvicorn binds, and with
# --reload that regularly overran the bound. The script then exited before ever
# reaching the ios/android branch, so a slow backend looked like "the simulator
# won't start". Bail out early if the container has actually died, so a genuinely
# broken backend still fails fast instead of burning the full timeout.
BACKEND_TIMEOUT=180
for _ in $(seq 1 "$BACKEND_TIMEOUT"); do
  curl -sf http://localhost:8000/health > /dev/null 2>&1 && break
  if [ -z "$(docker ps -q -f name=asheflow_backend -f status=running)" ]; then
    echo ""
    echo "ERROR: the asheflow_backend container is not running."
    echo "Its last log lines:"
    docker logs asheflow_backend --tail 30 2>&1 | sed 's/^/  /'
    exit 1
  fi
  sleep 1
done
if ! curl -sf http://localhost:8000/health > /dev/null 2>&1; then
  echo ""
  echo "ERROR: backend did not become ready within ${BACKEND_TIMEOUT}s."
  echo "Its last log lines:"
  docker logs asheflow_backend --tail 30 2>&1 | sed 's/^/  /'
  exit 1
fi
echo "Backend is up."
echo ""

# ── Shared Metro startup (iOS + Android) ─────────────────────────────────────
start_metro() {
  # No bare `cd` here: this function used to leave the caller in mobile/, so the
  # iOS branch checked Pods at mobile/ios/Pods (root-relative) but ran run-ios
  # from mobile/. Two assumed working directories in one branch, and a second
  # call would resolve mobile/mobile. Metro is launched in a subshell instead so
  # the caller's directory is never mutated.

  # Reuse a HEALTHY Metro instead of killing it. Both simulators share one
  # bundler; killing it here is what made ios/android runs order-dependent —
  # the second platform's start.sh killed the first's Metro mid-session, and
  # whichever app was connected went stale until something restarted it.
  if curl -sf http://localhost:8081/status > /dev/null 2>&1; then
    echo "Metro already running on 8081 — reusing it (both apps share one bundler)."
    echo "NOTE: if you changed mobile/.env, kill Metro first (kill \$(lsof -ti tcp:8081))"
    echo "      so the next start.sh run restarts it with --reset-cache."
    METRO_PID=""
    return
  fi

  # A process squatting on 8081 that doesn't answer /status is a zombie — clear it.
  STALE=$(lsof -ti tcp:8081 2>/dev/null)
  if [ -n "$STALE" ]; then
    echo "Killing unresponsive process on port 8081..."
    kill -9 $STALE 2>/dev/null
    sleep 1
  fi

  (cd mobile && npx react-native start --reset-cache) &
  METRO_PID=$!

  echo "Waiting for Metro to be ready..."
  until curl -sf http://localhost:8081/status > /dev/null 2>&1; do
    sleep 1
  done
  echo "Metro is up."
  echo ""
}

# After the app launches: keep Metro foreground if this run owns it.
finish_metro() {
  echo ""
  if [ -n "$METRO_PID" ]; then
    echo "App launched. Metro is running — press ^C to stop."
    wait $METRO_PID
  else
    echo "App launched against the already-running Metro. This terminal is free."
  fi
}

case "$PLATFORM" in

  ios|-ios|--ios|mobile|-mobile|--mobile)
    SIMULATOR="${DEVICE_ARG:-iPhone 16 Pro}"
    echo "Launching $SIMULATOR simulator and installing app..."

    # First run on a fresh checkout: install CocoaPods deps. UTF-8 locale is
    # required — CocoaPods crashes with "Unicode Normalization not appropriate
    # for ASCII-8BIT" under the default shell locale.
    if [ ! -d mobile/ios/Pods ]; then
      echo "CocoaPods not installed yet — running bundle/pod install..."
      export LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8
      (cd mobile && bundle install && cd ios && bundle exec pod install) || exit 1
    fi

    start_metro

    echo "Building and launching on $SIMULATOR..."
    (cd mobile && npx react-native run-ios --simulator "$SIMULATOR") || exit 1

    finish_metro
    ;;

  android|-android|--android)
    # Android SDK tools aren't on PATH by default on this machine.
    export ANDROID_HOME="${ANDROID_HOME:-$HOME/Library/Android/sdk}"
    export PATH="$PATH:$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator"

    # Gradle needs a JDK; fall back to Android Studio's bundled one.
    if [ -z "$JAVA_HOME" ] && [ -d "/Applications/Android Studio.app/Contents/jbr/Contents/Home" ]; then
      export JAVA_HOME="/Applications/Android Studio.app/Contents/jbr/Contents/Home"
    fi

    # Boot an emulator only if no device/emulator is already attached.
    if ! adb devices | grep -qE "device$"; then
      AVD="${DEVICE_ARG:-$(emulator -list-avds 2>/dev/null | head -1)}"
      if [ -z "$AVD" ]; then
        echo "ERROR: no Android AVD found. Create one in Android Studio > Device Manager."
        exit 1
      fi
      # -no-snapshot: this AVD's quickboot snapshot has corrupted before
      # ("Failed to restore previous context") — cold boot is slower but reliable.
      echo "Booting Android emulator: $AVD..."
      emulator -avd "$AVD" -no-snapshot -netdelay none -netspeed full > /dev/null 2>&1 &

      echo "Waiting for Android to finish booting..."
      adb wait-for-device
      until [ "$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = "1" ]; do
        sleep 2
      done
      echo "Android is up."
      echo ""
    fi

    start_metro

    echo "Building and launching on Android..."
    # run-android sets up `adb reverse tcp:8081` for Metro automatically; the
    # app itself reaches the backend via 10.0.2.2:8000 (see mobile/src/api/client.ts).
    (cd mobile && npx react-native run-android) || exit 1

    finish_metro
    ;;

  web|-web|--web)
    echo "Starting AsheFlow web frontend (Vite)..."
    echo "Press ^C to stop the frontend server."
    echo ""
    cd frontend && npm run dev
    ;;

  # An unrecognised platform used to fall through to `web|*)`, so a typo like
  # `-ios` silently started Vite and the simulator never opened — the script
  # gave no hint it had ignored the argument. Fail loudly instead.
  *)
    echo "ERROR: unknown platform '$PLATFORM'."
    echo ""
    echo "Usage:"
    echo "  ./start.sh              — Docker stack + web frontend (Vite)"
    echo "  ./start.sh ios [Sim]    — Docker stack + Metro + iOS app"
    echo "  ./start.sh android [AVD]— Docker stack + Metro + Android app"
    exit 1
    ;;

esac

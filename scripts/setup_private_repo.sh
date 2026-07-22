#!/usr/bin/env bash
# setup_private_repo.sh
#
# Two modes:
#
#   INIT (first time only):
#     bash scripts/setup_private_repo.sh --init
#     Creates the private repo structure, writes register.py, README, .gitignore,
#     and pushes an initial commit to both `main` and `staging` branches.
#     Run once after creating the AsheFlow-private GitHub repo.
#
#   SYNC (normal use — called automatically by the pre-push hook):
#     bash scripts/setup_private_repo.sh
#     Copies proprietary files into a fresh clone of AsheFlow-private, commits,
#     and pushes to the branch matching the current public branch
#     (staging → staging, master → main, anything else → staging).
#
# Prerequisites (one-time setup):
#   1. Create AsheFlow-private on GitHub (private, empty — no README)
#
#   2. Generate a deploy key:
#        ssh-keygen -t ed25519 -C "asheflow-private-deploy" \
#          -f ~/.ssh/asheflow_private_deploy -N ""
#
#   3. Add the PUBLIC key to AsheFlow-private with write access:
#        GitHub → AsheFlow-private → Settings → Deploy keys → Add deploy key
#        Title: "local-dev-push", paste ~/.ssh/asheflow_private_deploy.pub
#        Check "Allow write access"
#
#   4. Store the PRIVATE key in AWS SSM (read-only for CI — no write access needed):
#        aws ssm put-parameter \
#          --name /asheflow/staging/PRIVATE_REPO_DEPLOY_KEY \
#          --value "$(cat ~/.ssh/asheflow_private_deploy)" \
#          --type SecureString --region us-east-2 --overwrite
#        aws ssm put-parameter \
#          --name /asheflow/prod/PRIVATE_REPO_DEPLOY_KEY \
#          --value "$(cat ~/.ssh/asheflow_private_deploy)" \
#          --type SecureString --region us-east-2 --overwrite
#
#   5. Run init once:
#        bash scripts/setup_private_repo.sh --init
#
#   6. Install the pre-push hook so sync runs automatically on every push:
#        bash scripts/install_hooks.sh

set -euo pipefail

PRIVATE_REPO="git@github.com:adonisja/AsheFlow-private.git"
PUBLIC_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP_DIR="$(mktemp -d)"
INIT_MODE=false

if [ "${1:-}" = "--init" ]; then
  INIT_MODE=true
fi

# Determine which private branch to push to based on current public branch.
CURRENT_BRANCH=$(git -C "$PUBLIC_ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "staging")
if [ "$CURRENT_BRANCH" = "master" ]; then
  PRIVATE_BRANCH="main"
elif [ "$CURRENT_BRANCH" = "staging" ]; then
  PRIVATE_BRANCH="staging"
else
  # Feature branches sync to staging so they can be tested without touching main.
  PRIVATE_BRANCH="staging"
fi

echo "Public branch:  $CURRENT_BRANCH"
echo "Private branch: $PRIVATE_BRANCH"
echo "Cloning private repo to: $TMP_DIR"

if $INIT_MODE; then
  git clone "$PRIVATE_REPO" "$TMP_DIR/AsheFlow-private"
else
  git clone -b "$PRIVATE_BRANCH" "$PRIVATE_REPO" "$TMP_DIR/AsheFlow-private"
fi

cd "$TMP_DIR/AsheFlow-private"

if $INIT_MODE; then
  git checkout -B main
fi

# ── Directory structure ─────────────────────────────────────────────────────
mkdir -p backend/app/routers
mkdir -p backend/app/services
mkdir -p asheflow_private
mkdir -p docs/decisions
mkdir -p docs/journals
mkdir -p docs/templates

# ── Proprietary files ───────────────────────────────────────────────────────
ROUTERS=(
  dispatch.py
  training.py
  field_ops.py
  walker_routes.py
  rts.py
  building_profiles.py
  building_profile_library.py
)

SERVICES=(
  calculate_weights.py
  run_dispatch.py
  assign_drivers.py
  assign_trainers.py
  assign_trainees.py
  assign_walkers.py
  rebalance_crews.py
  resolve_conflict.py
  ban_override.py
  route_sort.py
  score_phase4.py
  seed_manifest.py
  derive_block_key.py
  sort_analysis.py
  run_sort.py
  persist_zones.py
  assign_totes.py
  wave_distribution.py
  stop_cutoff.py
)

echo ""
echo "Copying routers..."
for f in "${ROUTERS[@]}"; do
  src="$PUBLIC_ROOT/backend/app/routers/$f"
  if [ -f "$src" ]; then
    cp "$src" "backend/app/routers/$f"
    echo "  ✓ routers/$f"
  else
    echo "  ✗ MISSING: routers/$f (skipped)"
  fi
done

echo ""
echo "Copying services..."
for f in "${SERVICES[@]}"; do
  src="$PUBLIC_ROOT/backend/app/services/$f"
  if [ -f "$src" ]; then
    cp "$src" "backend/app/services/$f"
    echo "  ✓ services/$f"
  else
    echo "  ✗ MISSING: services/$f (skipped)"
  fi
done

# ── Proprietary tests ────────────────────────────────────────────────────────
# These import proprietary routers/services, so they're gitignored from the public
# repo and can't run in public CI. Sync them here so the CI test job (which pulls
# this repo) can run the FULL suite instead of silently skipping proprietary paths.
# Relative paths under backend/tests/ so services tests sync too, not just routers.
TESTS=(
  routers/test_arrival_confirm.py
  routers/test_back_at_truck.py
  routers/test_confirmation_gate.py
  routers/test_dispatch_move_pairing.py
  routers/test_finalize_gate.py
  routers/test_my_performance.py
  routers/test_pair_split.py
  routers/test_route_detail.py
  routers/test_route_reassign_unassign.py
  routers/test_peer_ratings.py
  routers/test_reassign_trainee.py
  services/test_stop_cutoff.py
)
echo ""
echo "Copying proprietary tests..."
for f in "${TESTS[@]}"; do
  src="$PUBLIC_ROOT/backend/tests/$f"
  if [ -f "$src" ]; then
    mkdir -p "backend/tests/$(dirname "$f")"
    cp "$src" "backend/tests/$f"
    echo "  ✓ tests/$f"
  else
    echo "  ✗ MISSING: tests/$f (skipped)"
  fi
done

# ── Docs (PII-scrubbed ADRs, journals, guides) ───────────────────────────────
echo ""
echo "Copying docs..."
cp -r "$PUBLIC_ROOT/docs/decisions/." "docs/decisions/"
cp -r "$PUBLIC_ROOT/docs/journals/." "docs/journals/"
cp -r "$PUBLIC_ROOT/docs/templates/." "docs/templates/"
# Top-level docs (LEARNING_GUIDE, ARCHITECTURE, etc.)
for f in "$PUBLIC_ROOT/docs/"*.md; do
  [ -f "$f" ] && cp "$f" "docs/$(basename "$f")"
done
echo "  ✓ docs/"

# ── Design memory + business docs (gitignored from public, preserved here) ──
echo ""
echo "Copying design memory and business docs..."
if [ -d "$PUBLIC_ROOT/memory" ]; then
  mkdir -p memory
  cp -r "$PUBLIC_ROOT/memory/." "memory/"
  echo "  ✓ memory/"
fi
mkdir -p docs/business
for f in "$PUBLIC_ROOT"/pricing_analysis_*.md; do
  if [ -f "$f" ]; then
    cp "$f" "docs/business/$(basename "$f")"
    echo "  ✓ docs/business/$(basename "$f")"
  fi
done

# ── Black-box registration module ───────────────────────────────────────────
# main.py does: from asheflow_private.register import register_proprietary_routers
cat > asheflow_private/__init__.py << 'PYEOF'
PYEOF

cat > asheflow_private/register.py << 'PYEOF'
from fastapi import APIRouter


def register_proprietary_routers(router: APIRouter, configured: list) -> None:
    from app.routers import dispatch, training, field_ops, walker_routes
    router.include_router(dispatch.router,      dependencies=configured)
    router.include_router(training.router,      dependencies=configured)
    router.include_router(field_ops.router,     dependencies=configured)
    router.include_router(walker_routes.router, dependencies=configured)
PYEOF

echo ""
echo "  ✓ asheflow_private/register.py"

# ── Sync CLAUDE.md ───────────────────────────────────────────────────────────
if [ -f "$PUBLIC_ROOT/CLAUDE.md" ]; then
  cp "$PUBLIC_ROOT/CLAUDE.md" "CLAUDE.md"
  echo "  ✓ CLAUDE.md"
fi

# ── Static files (init only) ─────────────────────────────────────────────────
if $INIT_MODE; then
  cat > README.md << 'EOF'
# AsheFlow — Private

Proprietary business logic for AsheFlow. This repo is pulled by CI during
staging and production deployments via a deploy key. Files are copied into
the corresponding paths in the main AsheFlow repo before `docker compose build`.

Do not share this repository. Do not add it as a dependency in package managers.

## Branch mapping

| AsheFlow-private branch | Deployed to |
|-------------------------|-------------|
| `staging`               | Staging EC2 |
| `main`                  | Prod EC2    |

CI clones the branch that matches the environment it is deploying to.
`setup_private_repo.sh` pushes to the matching branch automatically.

## Contents

### Registration module (black-box entry point)
- `asheflow_private/__init__.py`
- `asheflow_private/register.py` — `register_proprietary_routers(router, configured)`

### Routers
- `backend/app/routers/dispatch.py`
- `backend/app/routers/training.py`
- `backend/app/routers/field_ops.py`
- `backend/app/routers/walker_routes.py`

### Services
- `backend/app/services/calculate_weights.py`
- `backend/app/services/run_dispatch.py`
- `backend/app/services/assign_drivers.py`
- `backend/app/services/assign_trainers.py`
- `backend/app/services/assign_trainees.py`
- `backend/app/services/assign_walkers.py`
- `backend/app/services/rebalance_crews.py`
- `backend/app/services/resolve_conflict.py`
- `backend/app/services/ban_override.py`
- `backend/app/services/route_sort.py`
- `backend/app/services/score_phase4.py`
- `backend/app/services/tier1_verify.py`
- `backend/app/services/run_sort.py`
- `backend/app/services/persist_zones.py`
- `backend/app/services/stop_cutoff.py`
EOF

  cat > .gitignore << 'EOF'
__pycache__/
*.py[cod]
*.pyo
.DS_Store
*.env
EOF
fi

# ── Commit and push ──────────────────────────────────────────────────────────
git add .

if git diff --cached --quiet; then
  echo ""
  echo "No changes to sync — private repo already up to date."
else
  git commit -m "sync from AsheFlow $CURRENT_BRANCH"
  git push origin HEAD:"$PRIVATE_BRANCH"
  echo ""
  echo "Pushed to AsheFlow-private/$PRIVATE_BRANCH."
fi

if $INIT_MODE; then
  # Create the staging branch as a copy of main for init.
  git checkout -B staging
  git push origin staging
  echo "Created AsheFlow-private/staging branch."
fi

# ── Cleanup ──────────────────────────────────────────────────────────────────
cd /
rm -rf "$TMP_DIR"

echo ""
echo "Done."

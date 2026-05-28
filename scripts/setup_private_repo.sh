#!/usr/bin/env bash
# setup_private_repo.sh
#
# Run this ONCE after creating the AsheFlow-private GitHub repo and
# adding the deploy key. It initialises the private repo with the
# correct directory structure and pushes all proprietary files.
#
# Prerequisites:
#   1. Create AsheFlow-private on GitHub (private, empty — no README)
#
#   2. Generate a deploy key:
#        ssh-keygen -t ed25519 -C "asheflow-private-deploy" \
#          -f ~/.ssh/asheflow_private_deploy -N ""
#
#   3. Add the PUBLIC key to AsheFlow-private:
#        GitHub → AsheFlow-private → Settings → Deploy keys → Add deploy key
#        Title: "staging-ci-deploy", paste ~/.ssh/asheflow_private_deploy.pub
#        Do NOT check "Allow write access"
#
#   4. Store the PRIVATE key in AWS SSM Parameter Store (both envs):
#        aws ssm put-parameter \
#          --name /asheflow/staging/PRIVATE_REPO_DEPLOY_KEY \
#          --value "$(cat ~/.ssh/asheflow_private_deploy)" \
#          --type SecureString --region us-east-2 --overwrite
#        aws ssm put-parameter \
#          --name /asheflow/prod/PRIVATE_REPO_DEPLOY_KEY \
#          --value "$(cat ~/.ssh/asheflow_private_deploy)" \
#          --type SecureString --region us-east-2 --overwrite
#      (Same key works for both envs — it's a read-only key on the private repo)
#
#   5. Run this script from the root of the AsheFlow repo:
#        bash scripts/setup_private_repo.sh
#
# After this runs: push to staging → CI will clone AsheFlow-private and
# copy files into the correct paths before docker compose build.

set -euo pipefail

PRIVATE_REPO="git@github.com:adonisja/AsheFlow-private.git"
PUBLIC_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP_DIR="$(mktemp -d)"

echo "Public repo root: $PUBLIC_ROOT"
echo "Cloning private repo to: $TMP_DIR"

git clone "$PRIVATE_REPO" "$TMP_DIR/AsheFlow-private"
cd "$TMP_DIR/AsheFlow-private"

# Create directory structure mirroring the public repo layout
mkdir -p backend/app/routers
mkdir -p backend/app/services
mkdir -p asheflow_private

# Copy proprietary files
ROUTERS=(
  dispatch.py
  training.py
  field_ops.py
  walker_routes.py
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

# Write the black-box registration module
# main.py does: from asheflow_private.register import register_proprietary_routers
# This keeps all proprietary router names out of the public repo.
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

# Copy CLAUDE.md if present
if [ -f "$PUBLIC_ROOT/CLAUDE.md" ]; then
  cp "$PUBLIC_ROOT/CLAUDE.md" "CLAUDE.md"
  echo ""
  echo "  ✓ CLAUDE.md"
fi

# Add a README so the repo is navigable
cat > README.md << 'EOF'
# AsheFlow — Private

Proprietary business logic for AsheFlow. This repo is pulled by CI during
staging and production deployments via a deploy key. Files are copied into
the corresponding paths in the main AsheFlow repo before `docker compose build`.

Do not share this repository. Do not add it as a dependency in package managers.

## Contents

### Registration module (black-box entry point)
- `asheflow_private/__init__.py`
- `asheflow_private/register.py` — `register_proprietary_routers(router, configured)`

The public `main.py` imports only this function. No proprietary module names are visible
in the public repo.

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
EOF

# Add .gitignore so __pycache__ etc. don't leak in
cat > .gitignore << 'EOF'
__pycache__/
*.py[cod]
*.pyo
.DS_Store
*.env
EOF

git add .
git commit -m "initialise proprietary services from AsheFlow main repo"
git push origin main

echo ""
echo "Done. AsheFlow-private is ready."
echo "Next: push to the staging branch of AsheFlow — CI will pull this repo automatically."

# Cleanup
cd /
rm -rf "$TMP_DIR"

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
# The private branch MIRRORS the public branch 1:1 so a feature branch never
# clobbers staging's proprietary code (which would poison staging's CI — a
# feature branch and staging can have divergent proprietary/public APIs). CI
# reads the matching private branch by the same rule (see .github/workflows/ci.yml).
#   master  → main
#   staging → staging
#   <other> → <other>   (a private branch named exactly like the public one)
CURRENT_BRANCH=$(git -C "$PUBLIC_ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "staging")
if [ "$CURRENT_BRANCH" = "master" ]; then
  PRIVATE_BRANCH="main"
else
  PRIVATE_BRANCH="$CURRENT_BRANCH"
fi

echo "Public branch:  $CURRENT_BRANCH"
echo "Private branch: $PRIVATE_BRANCH"
echo "Cloning private repo to: $TMP_DIR"

if $INIT_MODE; then
  git clone "$PRIVATE_REPO" "$TMP_DIR/AsheFlow-private"
else
  # A feature branch may not have a private counterpart yet — branch it off staging
  # (the closest baseline) so the first sync of a new feature branch succeeds.
  if git clone -b "$PRIVATE_BRANCH" "$PRIVATE_REPO" "$TMP_DIR/AsheFlow-private" 2>/dev/null; then
    echo "Cloned existing private branch: $PRIVATE_BRANCH"
  else
    echo "Private branch '$PRIVATE_BRANCH' does not exist yet — creating it off staging."
    git clone -b staging "$PRIVATE_REPO" "$TMP_DIR/AsheFlow-private"
    git -C "$TMP_DIR/AsheFlow-private" checkout -B "$PRIVATE_BRANCH"
  fi
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
# Read from PROPRIETARY.txt — the single source of truth. Previously these were
# two hardcoded arrays that had to agree with .gitignore by hand, and they
# drifted in both directions: assign_captains.py was in NEITHER list (so nothing
# had it), while run_sort/persist_zones/sort_analysis were in SERVICES but not
# .gitignore (so they synced to private AND stayed public). One list removes the
# whole failure class.
MANIFEST="$PUBLIC_ROOT/PROPRIETARY.txt"
if [ ! -f "$MANIFEST" ]; then
  echo "ERROR: $MANIFEST not found — cannot determine what is proprietary."
  exit 1
fi

ROUTERS=()
SERVICES=()
while IFS= read -r _p; do
  case "$_p" in ''|\#*) continue ;; esac
  case "$_p" in
    backend/app/routers/*.py)  ROUTERS+=("$(basename "$_p")") ;;
    backend/app/services/*.py) SERVICES+=("$(basename "$_p")") ;;
  esac
done < "$MANIFEST"

echo "  manifest: ${#ROUTERS[@]} routers, ${#SERVICES[@]} services"

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

# ── Orphan guard: a service in NEITHER the manifest nor the public index ─────
# The manifest removed the two-list drift class, but one gap survives it: a NEW
# service file that nobody has classified yet. It is untracked publicly (so the
# public repo does not have it) and absent from the manifest (so this sync does
# not copy it) — exactly how assign_captains.py became invisible to everything
# at once. Fail the push rather than let it disappear.
echo ""
echo "Checking for unclassified services..."
_orphans=0
for src in "$PUBLIC_ROOT"/backend/app/services/*.py; do
  f="$(basename "$src")"
  printf '%s\n' "${SERVICES[@]}" | grep -qx "$f" && continue
  git -C "$PUBLIC_ROOT" ls-files --error-unmatch "backend/app/services/$f" >/dev/null 2>&1 && continue
  echo "  ✗ $f is neither tracked publicly nor listed in PROPRIETARY.txt."
  echo "    Decide which it is: add it to PROPRIETARY.txt (then run"
  echo "    scripts/sync_proprietary_lists.sh), or git add it."
  _orphans=1
done
if [ "$_orphans" -eq 1 ]; then
  echo ""
  echo "ERROR: unclassified proprietary file(s) would be lost. Push aborted."
  exit 1
fi
echo "  ✓ every service is classified"

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
  routers/test_clear_dispatch.py
  routers/test_finalize_gate.py
  routers/test_my_performance.py
  routers/test_pair_split.py
  routers/test_cover_remaining.py
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
# MIRROR, not append. `cp -r` into a persistent clone never removes a file that
# was deleted or renamed locally, so the private repo silently accumulated
# orphans: ADR-107-graduation-quiz.md and ADR-119-Sort-Pipeline-Web-Frontend.md
# both survived a local renumber and re-created duplicate ADR numbers in the
# backup. --delete makes the private copy a true mirror of local docs/.
#
# .obsidian/ is excluded: per-machine editor state, not documentation. The vault
# has its own git repo (docs/.git) for history; this sync is a backup mirror.
echo ""
echo "Copying docs..."
# docs/business/ is NOT excluded from the mirror by accident — it is populated
# further down from pricing_analysis_*.md at the repo root, which has no
# counterpart under local docs/. Without this exclude, --delete would remove it
# on every run and the block below would immediately re-create it.
rsync -a --delete \
  --exclude='.obsidian/' \
  --exclude='.git/' \
  --exclude='.githooks/' \
  --exclude='.gitignore' \
  --exclude='.DS_Store' \
  --exclude='business/' \
  "$PUBLIC_ROOT/docs/" "docs/"
echo "  ✓ docs/ (mirrored)"

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

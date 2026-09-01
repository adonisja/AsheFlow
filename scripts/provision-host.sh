#!/usr/bin/env bash
# Host dependencies for an AsheFlow EC2 box (ADR-347).
#
# Everything the box needs that is NOT installed by Docker or the app image.
# Idempotent: safe to re-run, installs only what is missing.
#
# The backup path (ADR-344) needs the AWS CLI to upload to S3. On staging it was
# absent -- and so was `unzip`, which the CLI installer needs -- so the first
# backup dumped 55MB, verified it, and then failed at the upload. Prod had the
# CLI from an undocumented manual step. Nothing in the repo put it there, so a
# rebuilt box would have repeated the failure.
#
# Usage:  sudo bash scripts/provision-host.sh
set -euo pipefail

log() { echo "$(date '+%F %T')  $*"; }
[ "$(id -u)" -eq 0 ] || { echo "must run as root (sudo)" >&2; exit 1; }

# ---- apt packages --------------------------------------------------------
# unzip:    required by the AWS CLI v2 installer
# curl:     fetches the installer
# gzip:     backup compression (usually present; asserted, not assumed)
# ca-certificates: TLS to S3 and Cognito
PACKAGES="unzip curl gzip ca-certificates"
MISSING=""
for p in $PACKAGES; do
  dpkg -s "$p" >/dev/null 2>&1 || MISSING="$MISSING $p"
done

if [ -n "$MISSING" ]; then
  log "installing:$MISSING"
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq $MISSING
else
  log "apt packages already present"
fi

# ---- AWS CLI v2 ----------------------------------------------------------
# Not from apt: Ubuntu ships v1 under a different name, and the backup script
# calls `aws s3 cp`, which must be the pinned v2 binary at a known path.
if command -v aws >/dev/null 2>&1; then
  log "aws cli already present: $(aws --version 2>&1)"
else
  log "installing aws cli v2"
  TMP=$(mktemp -d)
  trap 'rm -rf "$TMP"' EXIT
  curl -sS "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "$TMP/awscliv2.zip"
  unzip -oq "$TMP/awscliv2.zip" -d "$TMP"
  "$TMP/aws/install" --update
  log "installed: $(/usr/local/bin/aws --version 2>&1)"
fi

# ---- Verify the box can actually do its job ------------------------------
# Installing a binary is not the same as it working: the instance role must
# also resolve. A box that has the CLI but no credentials fails identically.
if ! aws sts get-caller-identity >/dev/null 2>&1; then
  echo "WARNING: aws cli installed but no instance credentials resolve --" >&2
  echo "         check the instance profile is attached (ADR-346)" >&2
  exit 1
fi
log "instance identity: $(aws sts get-caller-identity --query Arn --output text)"

log "provisioning complete"

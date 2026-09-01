#!/usr/bin/env bash
# Store the PRODUCTION Discord bot token in SSM, safely (ADR-351).
#
# Reads the token from a prompt with echo disabled, so it never reaches your
# shell history, the process list, or a file. Verifies it against Discord and
# refuses it if it is the staging bot.
#
# Usage:  bash scripts/set-prod-discord-token.sh
set -euo pipefail

REGION=us-east-2
PARAM=/asheflow/prod/DISCORD_BOT_TOKEN
STAGING_PARAM=/asheflow/staging/DISCORD_BOT_TOKEN

app_id_of() {
  # A bot token is <base64(app_id)>.<...>.<...>
  local head="${1%%.*}"
  while [ $(( ${#head} % 4 )) -ne 0 ]; do head="${head}="; done
  printf '%s' "$head" | tr '_-' '/+' | base64 -d 2>/dev/null || true
}

printf 'Paste the PRODUCTION bot token (input hidden): '
read -r -s TOKEN
printf '\n'
[ -n "$TOKEN" ] || { echo "no token entered" >&2; exit 1; }

# 1. Does it authenticate at all?
RESP=$(curl -sS -H "Authorization: Bot $TOKEN" https://discord.com/api/v10/users/@me)
NAME=$(printf '%s' "$RESP" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("username",""))' 2>/dev/null || true)
if [ -z "$NAME" ]; then
  echo "Discord rejected that token:" >&2
  printf '  %s\n' "$RESP" >&2
  exit 1
fi
NEW_APP=$(app_id_of "$TOKEN")
echo "  authenticates as: $NAME (application $NEW_APP)"

# 2. Refuse the staging bot. The whole point of ADR-351 is two applications; storing
#    staging's token here would silently recreate the shared-credential problem.
STAGING_TOKEN=$(aws ssm get-parameter --name "$STAGING_PARAM" --with-decryption \
                  --region "$REGION" --query Parameter.Value --output text 2>/dev/null || true)
if [ -n "$STAGING_TOKEN" ]; then
  STAGING_APP=$(app_id_of "$STAGING_TOKEN")
  if [ "$NEW_APP" = "$STAGING_APP" ]; then
    echo "REFUSED: that is the STAGING application ($STAGING_APP)." >&2
    echo "Create a separate Discord application for production (ADR-351 D1)." >&2
    exit 1
  fi
  echo "  distinct from staging application $STAGING_APP"
fi

# 3. Store it.
V=$(aws ssm put-parameter --name "$PARAM" --value "$TOKEN" --type SecureString \
      --overwrite --region "$REGION" --query Version --output text)
unset TOKEN
echo "  stored $PARAM (version $V)"

# 4. Read it back and re-verify -- proves what is stored is what works.
STORED=$(aws ssm get-parameter --name "$PARAM" --with-decryption --region "$REGION" \
           --query Parameter.Value --output text)
CHECK=$(curl -sS -H "Authorization: Bot $STORED" https://discord.com/api/v10/users/@me \
        | python3 -c 'import json,sys;print(json.load(sys.stdin).get("username",""))' 2>/dev/null || true)
unset STORED
[ -n "$CHECK" ] || { echo "stored token does not authenticate" >&2; exit 1; }
echo "  round-trip verified: $CHECK"
echo
echo "Prod's bot is NOT deployed (ci.yml omits it from the prod up -d list) and prod has"
echo "no company_configs.discord_guild_id set. Both are intentional (ADR-351 D3) -- the"
echo "token is provisioned so onboarding is a config change, not a credential scramble."

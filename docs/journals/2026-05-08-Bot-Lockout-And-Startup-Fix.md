# 2026-05-08 — Bot Cognito Lockout & Startup Resilience Fix

## What happened

The bot container was in a permanent crash loop with `NotAuthorizedException: Password attempts exceeded`. Each restart triggered another failed auth attempt, resetting Cognito's throttle cooldown — it could never recover on its own.

## Root cause

`BOT_PASSWORD` in `bot/.env` had drifted from the actual Cognito account password. The crash loop compounded the problem by continuously re-triggering the lockout.

## Fix sequence

1. `admin-set-user-password` — reset to a new known password
2. `admin-enable-user` + `admin-user-global-sign-out` — cleared the locked/throttled state
3. Updated `BOT_PASSWORD` in `bot/.env`
4. Recovered missing `DISCORD_ROLE_*` env vars (were never committed, only lived in `bot/.env`)
5. Made `AsheFlowClient.start()` catch `ClientError` on startup instead of raising — bot now starts regardless of auth state, retries lazily on first API call

## Lesson

A crash loop that triggers auth on every restart will perpetually reset a Cognito throttle cooldown. Always make startup auth non-fatal for service resilience.

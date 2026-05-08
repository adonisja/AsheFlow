# ADR-078 — Bot Startup Auth Resilience

**Date:** 2026-05-08  
**Status:** Accepted

## Context

The bot's Cognito account got locked out due to repeated failed `InitiateAuth` attempts from crash-looping. The crash loop itself was the problem — each restart triggered another auth attempt, resetting Cognito's throttle cooldown and making the lockout permanent. The bot would never recover on its own.

## Decision

`AsheFlowClient.start()` in `bot/services/api_client.py` now catches `ClientError` from the initial `_refresh_token()` call and logs a warning instead of raising. The bot starts successfully regardless of auth state — the internal webhook server (`:8001`) comes up, all cogs load, and the Discord gateway connection is established.

Token auth is retried lazily on the first actual API call via `_ensure_token()`, which calls `_refresh_token()` if the token is missing or expired.

```python
async def start(self) -> None:
    ...
    self._session = aiohttp.ClientSession(base_url=origin)
    try:
        await self._refresh_token()
    except ClientError as e:
        logger.warning("Startup Cognito auth failed (will retry on first API call): %s", e)
```

## Root cause of the lockout

The bot's `BOT_PASSWORD` in `bot/.env` had drifted from the Cognito account's actual password. Repeated failed attempts triggered Cognito's `Password attempts exceeded` throttle. Fixed by:

1. `admin-set-user-password` via AWS CLI to set a new known password
2. `admin-enable-user` + `admin-user-global-sign-out` to clear the locked state
3. Updating `BOT_PASSWORD` in `bot/.env` to match
4. Adding the resilient startup so a future throttle doesn't cause a permanent crash loop

## Consequences

- Bot is resilient to transient Cognito auth failures at startup (throttle, network blip, wrong password)
- Discord gateway and internal webhook server always come up — dispatch confirmations and invite endpoint remain available even if API calls fail
- First API call after a failed startup will surface the auth error at that point rather than at boot

# ADR-068: JWT Verification Fix — Pool Migration and PyJWT Access Token Bug

**Date:** 2026-05-07
**Status:** Implemented

## Context

Phase 1, Step 5 of the multi-tenant migration. After updating `.env` to point
at the new Cognito pool, `security.py` was still using the old pool's JWKS
endpoint. Two separate bugs had to be fixed.

## Bug 1: Shell environment variables override `.env`

`pydantic-settings` loads configuration in this priority order (highest first):
1. Environment variables set in the shell
2. `.env` file
3. Default values in the Settings class

The old pool ID had been exported in `~/.zshrc`:

```bash
export AWS_COGNITO_USER_POOL_ID="<old-pool-id>"
```

This silently overrode every `.env` update. The fix was to update `~/.zshrc`
to the new values, not just `.env`.

**Rule:** When a FastAPI app reads settings that appear wrong despite a correct
`.env`, always run `echo $VARIABLE_NAME` in the shell first. A live shell export
beats the file every time.

## Bug 2: PyJWT raises `MissingRequiredClaimError` for access tokens, not `InvalidAudienceError`

AWS Cognito issues two JWT types:
- **ID token** — contains an `aud` claim set to the app client ID
- **Access token** — contains no `aud` claim; client identity is in `client_id` payload field instead

The original `verify_cognito_token` fallback path only caught `InvalidAudienceError`:

```python
# Before — broken for access tokens
except jwt.InvalidAudienceError:
    # fall back to access token path
```

When PyJWT decodes a token with `audience=<client_id>` specified but the token
has no `aud` field at all, it raises `MissingRequiredClaimError("aud")`, not
`InvalidAudienceError`. The fix catches both:

```python
# After — correct
except (jwt.InvalidAudienceError, jwt.MissingRequiredClaimError):
    # fall back to access token path — MissingRequiredClaimError when token has no aud at all
```

## Verification

After both fixes, full round-trip authentication was verified for both accounts
on the new pool using both token types:

```
asheflow.bot  → sub: f18b2540-..., groups: ['dispatch']   ✓
test.user     → sub: d18b2510-..., groups: ['admin']       ✓
```

## Files changed

- `backend/app/core/security.py` — `MissingRequiredClaimError` added to except tuple
- `~/.zshrc` — `AWS_COGNITO_USER_POOL_ID` and `AWS_COGNITO_APP_CLIENT_ID` updated to new pool

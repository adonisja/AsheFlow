# ADR-075 — Session Security: Short TTL + Cognito Revocation

**Date:** 2026-05-08  
**Status:** Accepted

## Context

After deleting an employee record it was discovered that a previously authenticated user could still navigate the app freely — the JWT remained valid because JWTs are stateless. A DB check on every request was considered but rejected: it defeats the performance advantage of stateless auth and is incompatible with offline/cached features planned for later phases.

## Decision

### Cognito token TTL reduction

- Access token TTL reduced from the Cognito default (1 hour) to **15 minutes**
- Refresh token TTL reduced to **30 days**
- Silent refresh via Amplify means users are never asked to re-enter credentials during a normal session — the refresh token transparently mints a new access token before expiry

### Immediate revocation on deactivate/delete

`deactivate_employee` and `delete_employee` both call `_cognito_revoke_access(cognito_username)` before any DB mutation:

```python
def _cognito_revoke_access(cognito_username: str | None) -> None:
    for action in ("admin_disable_user", "admin_user_global_sign_out"):
        try:
            getattr(cognito, action)(UserPoolId=..., Username=cognito_username)
        except ClientError as e:
            logger.warning(...)
```

- `AdminUserGlobalSignOut` — invalidates all existing access/refresh tokens immediately
- `AdminDisableUser` — prevents new tokens from being issued even if the user tries to sign in again
- `reactivate_employee` calls `admin_enable_user` to re-enable the Cognito account

### Refresh token revocation requirement

`EnableTokenRevocation: true` must be set on the Cognito app client. Without this, refresh tokens are opaque and cannot be revoked server-side.

## Consequences

- Deleted/deactivated accounts lose access within 15 minutes at most (typically immediately via revocation)
- Normal users experience no visible change — Amplify handles silent refresh transparently
- Offline features can proceed without DB-per-request checks — the access token TTL is the security boundary
- Reactivated employees can sign in again immediately (Cognito account re-enabled)

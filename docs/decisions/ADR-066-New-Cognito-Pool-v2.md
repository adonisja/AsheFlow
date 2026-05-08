# ADR-066: New Cognito User Pool (AsheFlow-v2)

**Date:** 2026-05-07
**Status:** Implemented

## Context

Phase 1, Step 4 of the multi-tenant migration. The old pool used email as the
sign-in identifier — immutable after pool creation. The new
pool uses username (e.g. `danny.rivera`) as the identifier, with email and
phone as verifiable mutable attributes. This enables the registration flow,
forgot password by username, and clean per-company user management.

## New pool details

| Setting | Value |
|---|---|
| Pool ID | (see `backend/.env`) |
| Pool name | `AsheFlow-v2` |
| App client ID | (see `frontend/.env`) |
| Region | `us-east-2` |
| Sign-in identifier | `username` (case-insensitive) |
| Email sending | SES — `AsheFlow <noreply@asheflow.com>` |
| MFA | OPTIONAL (SMS via SNS) |
| SMS IAM role | `arn:aws:iam::<account-id>:role/AsheFlow-CognitoSMSRole` |
| Deletion protection | ACTIVE |

## Custom attributes

| Attribute | Mutable | Purpose |
|---|---|---|
| `custom:company_id` | No | UUID of the company — set at registration, immutable |
| `custom:role` | Yes | Mirrors DB role — informational only, backend trusts DB |

## Groups (with precedence)

| Group | Precedence |
|---|---|
| `super_admin` | 1 |
| `admin` | 10 |
| `management` | 20 |
| `dispatch` | 30 |
| `driver` | 40 |
| `trainer` | 50 |
| `walker` | 60 |
| `trainee` | 60 |
| `test_user` | 99 |

## Migrated accounts

| Username | Email | Role | DB record |
|---|---|---|---|
| `asheflow.bot` | (see `bot/.env`) | dispatch | Yes — cognito_sub stamped |
| `test.user` | (internal) | admin | Yes — cognito_sub stamped |
| `driver.test` | (internal) | driver | No — Cognito only |
| `walker.test` | (internal) | walker | No — Cognito only |
| `trainer.test` | (internal) | trainer | No — Cognito only |
| `trainee.test` | (internal) | trainee | No — Cognito only |
| `manager.test` | (internal) | management | No — Cognito only |
| `dispatch.test` | (internal) | dispatch | No — Cognito only |

## Federated providers

Both Discord and Google re-wired to new pool. Hosted UI domain created:
```
https://asheflow-auth.auth.us-east-2.amazoncognito.com
```
IdP callback URL registered in both Discord Developer Portal and Google Cloud Console:
```
https://asheflow-auth.auth.us-east-2.amazoncognito.com/oauth2/idpresponse
```

## Known limitations at time of creation

- **SNS sandbox mode** — SMS MFA can only send to verified phone numbers until
  SNS production access is requested (separate from SES production access)
- **Old pool not yet deleted** — kept active until all systems verified on new pool
- **End-to-end federated sign-in not yet tested** — marked in `docs/FEDERATED_IDENTITY_PROVIDERS.md`

## Files changed

- `backend/.env` — updated to new pool ID and client ID, old values commented
- `bot/.env` — updated pool ID, client ID, and BOT_USERNAME to `asheflow.bot`

# ADR-070: Federated Login Guard — Pre Sign-Up Lambda

**Date:** 2026-05-07
**Status:** Implemented

## Context

Discord and Google federated sign-in are enabled on the AsheFlow-v2 Cognito pool.
Without a guard, any person with a Discord or Google account could sign in and
Cognito would auto-create a new Cognito identity for them — bypassing the manager-
controlled account creation flow entirely. This would leave the new Cognito user
with no `Employee` DB row, no `company_id`, and no role.

## Decision

A **Pre Sign-Up Lambda trigger** (`AsheFlow-CognitoPreSignup`) is attached to the
pool. It fires before any new Cognito user is persisted, for both native and
federated paths.

### Rules enforced

| Trigger source | Rule |
|---|---|
| `PreSignUp_SignUp` | Always rejected — no self-signup |
| `PreSignUp_ExternalProvider` | Allowed only if a native Cognito user with the same email already exists |
| `PreSignUp_AdminCreateUser` | Always allowed — manager-created accounts pass through |

### Account linking

When a federated user's email matches a pre-existing native account, the Lambda
sets `autoConfirmUser = True` and `autoVerifyEmail = True`. Cognito then
automatically links the federated identity to the existing native user, so the
employee can sign in with either Discord/Google or their username/password from
that point on — no separate linking UI needed for the initial case.

A dedicated account-linking settings page (for employees who want to add a
provider post-registration) is deferred to Phase 2.

### Error surface

When the Lambda rejects a federated signup, Cognito fires a `signIn_failure`
event on Amplify's Hub. `AuthContext` listens for this event and stores the
error message in `federatedError` state. `Login.tsx` reads `federatedError`
via `useEffect` and surfaces it as the page-level error banner, then clears it.

## Infrastructure

| Resource | Value |
|---|---|
| Lambda function | `AsheFlow-CognitoPreSignup` |
| Runtime | Python 3.12 |
| IAM role | `AsheFlow-CognitoPreSignup` |
| Policies | `AWSLambdaBasicExecutionRole` + `AmazonCognitoReadOnly` |
| Region | us-east-2 |
| Env var | `USER_POOL_ID` — set in Lambda console, matches `backend/.env` |

## Files changed

- `infra/lambda/cognito-pre-signup/handler.py` — Lambda source
- `infra/lambda/cognito-pre-signup/function.zip` — deployment artifact (gitignored)
- `frontend/src/contexts/AuthContext.tsx` — `federatedError` state + Hub `signIn_failure` handler
- `frontend/src/components/auth/Login.tsx` — displays `federatedError` via `useEffect`

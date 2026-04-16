# Journal: Identity Provider (IdP) Cloud Setup Step-by-Step
**Date:** 2026-04-07
**Event Start:** 2026-04-07 05:53:39

## Objective
Walk the user through the cloud console configuration (Path B) to generate their real AWS Cognito and Discord Developer IDs without committing them to version control.

## Decisions & Context
We are implementing the Identity Federation strategy outlined in `ADR-005`. The user needs to manually create the remote infrastructure in AWS and Discord to isolate the environment variables. To adhere to the `Soul.md` directives (12-Factor App), we will instruct the user to configure these in their global `~/.zshrc`.

## Procedure
1. Create a Discord Developer Application.
2. Create an AWS Cognito User Pool with Discord as an OIDC (Federated) Provider.
3. Extract the `User Pool ID`, `App Client ID`, and `AWS Region` from the console.
4. Export these as system environment variables in the user's `~/.zshrc`.

**Status:** In Progress
*(08:43:00) Redirected user to create a secure IAM Administrative User to avoid using AWS Root Account for development.*
*(10:21:23) Successfully extracted AWS_REGION, AWS_COGNITO_USER_POOL_ID, and AWS_COGNITO_APP_CLIENT_ID from the new AWS Application-Centric wizard.*
*(17:07:47) Guided user to the "Social and external providers" section to add Discord OIDC mapping.*
*(17:14:45) User successfully added Discord. Now proceeding to add Google as a native federated provider to demonstrate multi-IdP broker capabilities.*
*(18:02:46) User generated Google OAuth credentials and mapped the Cognito Redirect URL successfully. Proceeding to add Google natively into Cognito.*
*(18:04:40) Acknowledged AWS UI updates; committed to exclusively using the new Application-Centric wizard flow for all Cognito instructions moving forward.*
*(18:06:59) User successfully added Google as a social provider.*

## Outcome
The Cloud setup (Path B) is formally complete. AWS Cognito has been configured as a central Identity Broker with Discord and Google acting as Federated Identity Providers. The backend environment variables have been securely mapped.

**Status:** Completed
**Event End:** 2026-04-07 18:06:59

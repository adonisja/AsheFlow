# Journal: API Authentication Middleware
**Date:** 2026-04-07
**Event Start:** 2026-04-07 18:07:00

## Objective
Walk the user through writing the cryptographic JWT validation engine and FastAPI dependency injection layer (Path A) to enforce the Identity Federation strategy outlined in `ADR-005`.

## Procedure
1. Created `app/core/security.py` to handle asymmetric cryptography (`pyjwt`, `cryptography`).
2. Implemented an in-memory JSON Web Key Set (`JWKS`) cache to eliminate N+1 network requests to AWS Cognito.
3. Designed `app/api/deps.py` with `OAuth2PasswordBearer` to perform header extraction and trigger the mathematical verification process.
4. Placed the `get_current_user` dependency inside the `POST /dispatch/` router to securely lock down MVP Gap #3.

**Status:** Completed
**Event End:** 2026-04-07 19:57:36
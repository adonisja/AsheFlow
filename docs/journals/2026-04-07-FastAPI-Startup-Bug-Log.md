# Journal: FastAPI Startup & Configuration Bug Log
**Date:** 2026-04-07

## Overview
During the integration of the AWS Cognito Security Middleware, we encountered two cascading startup crashes when booting the FastAPI server via `uvicorn`. This document logs the bugs, our troubleshooting steps, and the architectural lessons learned regarding `pydantic-settings` and the 12-Factor App methodology.

---

## Bug 1: Pydantic Strictness (AttributeError)

**The Error:**
`AttributeError: 'Settings' object has no attribute 'database_url'`

**The Context:**
We transitioned our environment configurations to use `pydantic-settings` to securely manage our AWS parameters (`AWS_REGION`, `AWS_COGNITO_USER_POOL_ID`, etc.). The existing `app/database.py` file was updated to pull the database URL from this new centralized `settings` object.

**Attempted Solution & Why it Failed:**
We attempted to bypass the error by injecting the `DATABASE_URL` directly into the ZSH terminal memory using `export DATABASE_URL="..."`. 
*Why it failed:* Pydantic enforces strict type-checking and schema validation. Even if an environment variable exists in the host OS, if that variable is not explicitly declared as an attribute inside the `Settings` python class, Pydantic acts as a firewall and refuses to load it. It blindly ignores "undeclared" environment variables to prevent memory leaks and configuration bugs.

**Final Solution & Why it Worked:**
We added exactly one explicitly typed line to `app/core/config.py`:
`database_url: str = "postgresql://postgres:postgres@localhost:5432/asheflow"`
*Why it worked:* By declaring the attribute, we satisfied Pydantic's strict schema definition. The application was then able to successfully read the default value and boot the connection sequence.

---

## Bug 2: Database Authentication Rejection (OperationalError)

**The Error:**
`sqlalchemy.exc.OperationalError: (psycopg2.OperationalError) FATAL: password authentication failed for user "postgres"`

**The Context:**
After solving the Pydantic error, SQLAlchemy attempted to actually connect to the PostgreSQL database using the default connection string provided in the `Settings` class (`postgres:postgres`).

**Attempted Solution & Why it Failed:**
We initially assumed the local Docker instance was using standard, unconfigured Postgres defaults. We tried passing the default URI to the app.
*Why it failed:* The `docker-compose.yml` file is properly configured for enterprise-grade isolated credentials (`POSTGRES_USER: asheflow`, `POSTGRES_PASSWORD: asheflow_dev_password`). Docker actively rejected the connection because the "postgres" root user account was likely disabled or had a securely randomized password. 

**Final Solution & Why it Worked:**
We ran a `grep` search against `docker-compose.yml` to extract the true database credentials. 
1. We updated the fallback string in `config.py` to: `postgresql://asheflow:asheflow_dev_password@localhost:5432/asheflow_db`.
2. We instructed the user to run `unset DATABASE_URL` in their terminal to wipe the bad variable out of memory.
*Why it worked:* This perfectly simulated the 12-Factor App environment variable hierarchy. By clearing the bad ZSH environment variable, Pydantic fell back to the exact default string we placed in `config.py`, passed the correct credentials to SQLAlchemy, and the application booted cleanly with `Application startup complete.`
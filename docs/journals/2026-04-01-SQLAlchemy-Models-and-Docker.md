# Engineering Journal: April 1, 2026

**Session Start Time**: April 1, 2026, 05:22 AM EST (GMT-5, NYC)
**Session End Time**: April 2, 2026, 12:05 AM EST (GMT-5, NYC)

## Goal for the Session
Translate the SQL schema designed in the previous session into SQLAlchemy models, wire up the FastAPI entry point, and get the full stack running in Docker with all 6 tables created in PostgreSQL.

## Problems Encountered

### 1. `docker-compose up` failed — missing `frontend/` directory
**Error:** `unable to prepare context: path ".../frontend" not found`
**Cause:** `docker-compose.yml` referenced a `frontend` service and `celery_worker` service that don't exist yet.
**Fix:** Commented out `frontend` and `celery_worker` services — they'll be re-enabled in their respective development phases.

### 2. `version` attribute warning in docker-compose
**Error:** `the attribute 'version' is obsolete`
**Fix:** Removed `version: '3.8'` line — no longer needed in modern Docker Compose.

### 3. PostgreSQL FATAL healthcheck errors on first boot
**Error:** `FATAL: database "asheflow" does not exist` (repeating)
**Cause:** Timing issue — healthcheck polled before PostgreSQL finished initializing on first volume creation. Not a real error.
**Resolution:** Backend reported `Application startup complete` confirming successful connection. FATAL messages stopped once init completed.

## Solutions & Procedures

### Project Structure Created
```
backend/
├── Dockerfile
├── requirements.txt
└── app/
    ├── main.py
    ├── database.py
    └── models/
        ├── __init__.py       # registers all models with Base
        ├── base.py           # shared DeclarativeBase
        ├── employee.py
        ├── truck.py
        ├── truck_assignment.py
        ├── assignment_member.py
        ├── employee_off_day.py
        └── employee_relationship.py
```

### Key Files

**`database.py`** — reads `DATABASE_URL` from environment, creates SQLAlchemy engine and session factory. Exposes `get_db()` dependency for FastAPI endpoints.

**`models/base.py`** — defines shared `Base = DeclarativeBase()` that all models inherit from.

**`models/__init__.py`** — imports all 6 models so they register with Base on a single import.

**`main.py`** — creates FastAPI app, runs `Base.metadata.create_all()` on startup, exposes `/health` endpoint.

### Dependencies (`requirements.txt`)
```
fastapi          # web framework
sqlalchemy       # ORM
uvicorn          # ASGI web server
psycopg2-binary  # PostgreSQL driver
```

### Verified Working
- `docker-compose up --build` → all 3 services healthy
- `GET http://localhost:8000/health` → `{"status": "ok"}`
- `\dt` in psql → all 6 tables present in `asheflow_db`

## Key Architectural Decisions

1. **Environment variables for credentials**: `DATABASE_URL` read via `os.getenv()` — never hardcoded. Credentials injected by Docker at runtime. Rationale: non-technical personnel manage deployments; eliminates credential exposure in source code.
2. **`gen_random_uuid()` confirmed**: Used `default=uuid.uuid4` in SQLAlchemy (Python-side generation) — consistent with prior decision to avoid `uuid-ossp` extension dependency.
3. **Frontend/Celery disabled**: Commented out in `docker-compose.yml` — not needed until their respective phases. Re-enable when frontend and background job phases begin.

## Key Takeaways
* An ORM maps Python classes to database tables — you work with objects, SQLAlchemy generates SQL under the hood.
* `Base.metadata.create_all()` only creates tables for models that have been imported — `__init__.py` ensures all models register on a single import.
* `requirements.txt` lists only third-party packages — Python built-ins (`uuid`, `os`) are excluded. FastAPI needs both `fastapi` AND `uvicorn` (the server that runs it).
* `psycopg2-binary` is the PostgreSQL driver — SQLAlchemy builds queries, psycopg2 executes them against the actual database.
* Never hardcode credentials — use environment variables. Docker injects them at container startup.
* `docker-compose up --build` starts the full stack. `--build` forces image rebuilds to pick up code changes.
* FastAPI auto-generates interactive API docs at `/docs` — no Postman needed for testing.

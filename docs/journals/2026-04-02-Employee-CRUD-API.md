# Engineering Journal: April 2, 2026

**Session Start Time**: April 2, 2026, 12:05 AM EST (GMT-5, NYC)
**Session End Time**: April 2, 2026, 10:12 AM EST (GMT-5, NYC)

## Goal for the Session
Build the complete Employee CRUD API — Pydantic schemas, router, all endpoints — and verify each one works end to end via Postman.

## Problems Encountered

### 1. `EmployeeCreate` written as a function instead of a Pydantic class
**Cause:** Unfamiliarity with Pydantic syntax — used `def` and `return dict(...)` instead of a class inheriting from `BaseModel`.
**Fix:** Pydantic schemas are classes, not functions. Fields are declared as class attributes with type hints.

### 2. `employee_id: int` on endpoints that use UUID primary keys
**Cause:** Default assumption that IDs are integers.
**Fix:** UUID IDs require `UUID` type from Python's built-in `uuid` module. FastAPI automatically parses UUID path parameters.

### 3. `async def` on endpoints using synchronous SQLAlchemy session
**Cause:** Assumed async was always better.
**Fix:** Standard SQLAlchemy sessions are synchronous — use `def`. `async def` is for async drivers like `asyncpg`.

### 4. `status_code.HTTP_404_NOT_FOUND` syntax error
**Cause:** Confusion between `status` (the FastAPI import) and `status_code` (the parameter name).
**Fix:** `status.HTTP_404_NOT_FOUND` — `status` is the imported object.

## Solutions & Procedures

### Files Created
```
backend/app/
├── schemas/
│   └── employee.py       # EmployeeCreate, EmployeeUpdate, EmployeeResponse
└── routers/
    ├── __init__.py
    └── employees.py      # Full CRUD endpoints
```

### Pydantic Schemas (`schemas/employee.py`)

```python
class EmployeeCreate(BaseModel):
    name: str
    discord_id: str
    role: str

class EmployeeUpdate(BaseModel):
    name:       Optional[str] = None
    discord_id: Optional[str] = None
    role:       Optional[str] = None

class EmployeeResponse(BaseModel):
    id: UUID
    name: str
    discord_id: str
    role: str
    is_active: bool
    model_config = {"from_attributes": True}
```

### Complete Endpoint Surface

| Method | Path | Status | Description |
|---|---|---|---|
| POST | `/employees` | 201 | Create employee |
| GET | `/employees` | 200 | List active employees |
| GET | `/employees/{id}` | 200/404 | Fetch one by ID |
| PUT | `/employees/{id}` | 200/404 | Partial update |
| PUT | `/employees/{id}/deactivate` | 200/404 | Soft deactivate |
| DELETE | `/employees/{id}` | 204/404 | Soft delete |

### Key Patterns Applied
- `model_dump(exclude_unset=True)` on updates — only modifies fields the caller explicitly sent
- `db.refresh()` after commit — pulls DB-generated values (id, is_active) back into Python object
- `204 No Content` on DELETE — no response body, resource is gone from caller's perspective
- `HTTPException(404)` on all single-record lookups — fail fast with clear error message

## Key Architectural Decisions

1. **`PUT /deactivate` kept alongside `DELETE`**: Deactivation (employee goes on leave) is semantically different from deletion (remove from system). Both are soft deletes internally but signal different intent to the caller.
2. **`Optional` fields on `EmployeeUpdate`**: Allows partial updates — caller only sends what they want to change. Required fields would force callers to resend all data on every update.

## Key Takeaways
* Pydantic schemas are classes inheriting from `BaseModel`, not functions. Fields are type-annotated class attributes.
* Two schema types per resource minimum: `Create` (input) and `Response` (output). Add `Update` for partial updates.
* `model_config = {"from_attributes": True}` required on response schemas — lets Pydantic read SQLAlchemy object attributes.
* `Optional[str] = None` makes a field optional. `exclude_unset=True` on `model_dump()` prevents unset fields from overwriting existing data.
* HTTP status codes matter: `201` for create, `200` for read/update, `204` for delete, `404` for not found.
* `DELETE` in REST convention returns `204 No Content` — no body, no `db.refresh()`, no `return`.
* Postman collection variables (`{{base_url}}`) prevent repetition and make endpoint switching instant.

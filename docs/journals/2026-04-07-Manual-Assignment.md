# Journal: Manual Assignment API (MVP Gap #5)
**Date:** 2026-04-07
**Event Start:** 2026-04-07 21:37:24

## Objective
Implement `POST /dispatch/assign` (MVP Gap #5). This is an operational necessity fallback that allows a dispatcher to manually bind a specific employee to a specific truck when algorithmic auto-dispatch fails (e.g., driver shortages raising a `400 Bad Request`).

## Context
Currently, if `num_drivers < num_trucks`, the system stops completely. Without manual overrides, a dispatcher cannot utilize the remaining vehicles. This endpoint bypasses the algorithmic calculations entirely and directly interfaces with the database.

## Plan
1. Create a Pydantic schema for the request payload (`ManualAssignmentRequest`).
2. Build the router endpoint inside `app/routers/dispatch.py`.
3. Implement the business logic to assert the assignment into the database while maintaining database integrity.

**Status:** Resumed (2026-04-07 22:06 EDT)
**Event End:** 2026-04-07 22:46 EDT

## Implementation Details
### 1. Manual Assignment (Gap #5)
*   **Schema**: Created `ManualAssignmentCreate` in `app/schemas/dispatch.py` using `pydantic.Field` and `typing.Literal` to constrain inputs to `employee_id`, `truck_id`, `date`, and strict roles (driver, trainer, walker).
*   **Endpoint**: Built `POST /dispatch/assign`. Handled multiple guards:
    *   404 if Truck or Employee do not exist.
    *   409 if the Employee is already assigned to any truck on that date.
    *   Upserts `TruckAssignment` for that date/truck if it doesn't already exist in the db.

### 2. Role-Based Access Control (Gap #4)
*   **The Problem:** Anyone obtaining an authenticated AWS Cognito JWT could run the dispatch endpoints, bypassing the Discord role framework.
*   **The Solution:** Built a custom FastAPI Dependency class `RoleChecker` inside `app/api/deps.py`.
*   **How it works:** The class takes a list of allowed roles on initialization. Using Python's `__call__` magic method, it intercepts the `get_current_user` dict, extracts the `cognito_groups` array provided by AWS, and asserts intersection.
*   **Application:** Applied `allow_dispatch_mgmt = RoleChecker(["dispatch", "management"])` as a `Depends()` injection to both `POST /dispatch/` and `POST /dispatch/assign`.

## Key Takeaways Logging
Added "FastAPI Callable Class Dependencies for RBAC" to the Learning Guide.

---
*Audit Trail: Completed. IP Protected.*
# Engineering Journal: April 3, 2026

**Session Start Time**: April 2, 2026, 11:12 PM EST (GMT-5, NYC)
**Session End Time**: April 3, 2026, 10:37 AM EST (GMT-5, NYC)

## Goal for the Session
Complete the remaining routers — employee_off_days and employee_relationships — finishing the full dispatch API surface.

## Problems Encountered

### 1. Duplicate schema file
**Cause:** `employee_off_days.py` (plural) created alongside `employee_off_day.py` (singular).
**Fix:** Removed duplicate, consolidated into singular file matching the model naming convention.

### 2. DELETE endpoint using query param instead of path param
**Cause:** ID placed as function parameter without path declaration.
**Fix:** `@router.delete("/{relationship_id}")` — ID belongs in the URL path, not the query string.

### 3. GET endpoint had extra request body parameter
**Cause:** `employee_relationship: EmployeeRelationshipResponse` added incorrectly to GET handler.
**Fix:** GET endpoints never take a request body — only path params, query params, and the DB session.

## Solutions & Procedures

### employee_off_days Router
- POST: verifies employee exists, inserts off day (hard insert — corrections not history)
- GET `/{employee_id}`: returns all off days for an employee
- DELETE `/{off_day_id}`: hard delete — removing an off day is a correction

### employee_relationships Router
Five validation checks before insert:
1. `employee_id` exists → 404
2. `target_employee_id` exists → 404
3. Self-relationship check → 400 (employee cannot add themselves)
4. Max-2 count check per relationship_type → 409
5. Duplicate relationship check → 409

**Self-ban check** — added proactively without prompting. Correct use of `400 Bad Request` (input is semantically invalid).

## Complete API Surface

| Router | Endpoints |
|---|---|
| employees | POST, GET /, GET /{id}, PUT /{id}, PUT /{id}/deactivate, DELETE /{id} |
| trucks | POST, GET /, GET /{id}, PUT /{id}, PUT /{id}/deactivate, DELETE /{id} |
| truck_assignments | POST, GET /, GET /{id}, PUT /{id} |
| assignment_members | POST (with business rules), GET /{assignment_id}, DELETE /{id} |
| employee_off_days | POST, GET /{employee_id}, DELETE /{id} |
| employee_relationships | POST (with 5 validation checks), GET /{employee_id}, DELETE /{id} |

## Key Takeaways
* GET endpoints never take a request body — IDs come from path params, filters from query params.
* Resource IDs belong in the URL path (`/{id}`), not the query string (`?id=...`).
* Proactive edge case thinking (self-ban check) is the mark of good engineering — consider what the data means, not just what was asked for.
* N+1 is sequential queries in a loop, not just multiple queries. Two sequential queries for different purposes is acceptable.

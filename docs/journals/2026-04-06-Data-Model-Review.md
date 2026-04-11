# Engineering Journal: April 6, 2026

**Session Start Time**: April 6, 2026, 10:50 AM
**Session End Time**: [In Progress]

## Goal for the Session
Permanently remove ghost files and conduct a comprehensive review of the SQLAlchemy Data Models (`app/models/`) to ensure database constraints, indexing, and cascade delete rules are sound before moving onto Alembic migrations or Auth.

## Problems Encountered
1. **Bad Deletion Command Pipeline**: The terminal command I previously sent to delete the ghost files (`reassign_walker.py` and `dispatch.py`) targeted the wrong relative path (`backend/app/...` instead of just `app/...` because we were already in the backend directory). 
2. **Missing Database Integrity Constraints & Relationships**: Reviewing the models revealed several critical, missing architectural implementations:
   * **Missing `unique` constraints on relationships**: The `EmployeeRelationship` model allows an employee to "ban" another employee a thousand times because there is no `UniqueConstraint(employee_id, target_employee_id)`.
   * **Missing indexing on frequent queries**: The `TruckAssignment` table is queried by `date` constantly in the algorithm, but the `date` column is not indexed, which will result in sequential table scans (O(n) lookups) as the data grows.
   * **Missing `relationship` cascades**: When a `Truck` is deleted, its matching `TruckAssignment` rows (and subsequently `AssignmentMember` rows) will either orphan or crash database integrity checks because `ON DELETE CASCADE` is missing from the relationships.

## Solutions & Procedures
1. **Cleanup fixed**: Re-ran the file deletion from the correct Current Working Directory. Both ghost service files are fully deleted.
2. **Scheduled Model Upgrades**: Listed the required SQLAlchemy refactors into the journal to prepare for updates, including adding `UniqueConstraint` to junction tables, adding `index=True` for high-volume lookup columns, and declaring proper two-way `relationship()` bindings on the ORM models.

## Key Takeaways
* **CWD Awareness**: Always double-check the `pwd` in the active terminal environment when writing shell scripts to avoid failing silent operations.
* **The "Two-Tier" Database Protection**: Application-level logic (e.g., throwing a FastAPI error if a ban already exists) is completely insufficient. The database itself MUST have absolute data constraints (Unique Constraints, Enums, FK Cascades). By relying on the app layer, a developer seeding data or writing an override script can corrupt the database directly. True architecture locks safety at the lowest level (the DB Engine).

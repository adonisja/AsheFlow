# Engineering Journal: April 5, 2026

**Session Start Time**: April 5, 2026, 09:15 AM
**Session End Time**: [In Progress]

## Goal for the Session
Refactor and optimize the `get_available_pool` database queries to efficiently retrieve available dispatch employees for the target date.

## Problems Encountered
1. **Logical Bug (Join vs. Exists):** Using a standard `INNER JOIN` for finding staff *without* scheduled off-days inadvertently filtered out employees who had no off-days recorded at all (e.g., someone willing to work 7 days a week).
2. **Performance Inefficiency:** Making three nearly identical database calls differentiated only by role (`driver`, `trainer`, `walker`) incurred unnecessary network latency and database I/O.

## Solutions & Procedures
1. **Correlated Subqueries over Joins:** Replaced the `INNER JOIN` approach with an SQL `NOT EXISTS` (`~exists()`) correlating subquery in SQLAlchemy. This correctly filters out people with off-days today while retaining employees who don't have *any* off-days.
2. **Query Consolidation:** Refactored the three distinct role queries into a single query using an `IN` clause (`Employee.role.in_(["driver", "trainer", "walker"])`). Grouping by role was moved from the SQL execution layer to Python's in-memory processing loop.

## Key Takeaways
* **Network I/O vs. Python CPU Trade-off:** In web applications, network trips to the database are comparatively slow and expensive. For small-to-medium datasets (like a daily dispatch pool of 50-200 people), it is far more scalable to fetch everything in one round-trip and use Python to sort the lists in memory rather than forcing the server to make three separate network calls. Minimize your database round-trips!
* **The "Anti-Join" Concept:** When looking for "things that do not exist or match," standard inner joins fail. `NOT EXISTS` subqueries are conceptually safer, inherently cleaner to read in SQLAlchemy, and often optimized better by the database engine than trying to hack together a `LEFT OUTER JOIN` with an `IS NULL` check.

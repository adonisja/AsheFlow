# Engineering Journal: April 6, 2026

**Session Start Time**: April 6, 2026, 10:40 AM
**Session End Time**: [In Progress]

## Goal for the Session
Review the `app/routers/` and `app/services/` codebase for architectural redundancies or code duplication introduced during the monolith-to-microservices refactoring and the fix of the `assignment_members` router.

## Problems Encountered
1. **Orphaned Files (Dead Code)**: The refactor left behind two empty/defunct files in the `services` directory that were no longer being used by the application, cluttering the workspace and potentially confusing future developers:
   - `backend/app/services/dispatch.py` (The hollowed-out monolithic file).
   - `backend/app/services/reassign_walker.py` (The file we made defunct by inlining its logic into `ban_override.py` to fix the circular import).
2. **Apparent Logic Duplication (Bulk vs Single Queries)**: The `assignment_members.py` router manually checks ban relationships using `check_ban_relationship()` inside a loop, while the dispatch algorithms (`assign_trainers.py` and `assign_walkers.py`) completely ignore this function and write their own custom SQL queries to check bans.

## Solutions & Procedures
1. **Dead Code Elimination**: I executed `rm -f backend/app/services/reassign_walker.py backend/app/services/dispatch.py` to permanently clean these out of the codebase. They no longer serve a purpose.
2. **Architectural Justification (Why the "duplication" is correct)**: 
   - **The REST Router (`assignment_members.py`)**: Only assigns ONE employee at a time. It uses the `check_ban_relationship` microservice to run a strict, readable `obj.exists()` check. 
   - **The Dispatch Engine (`assign_trainers/walkers`)**: Needs to calculate the schedule for 5-7 trucks (25+ people) simultaneously. If it used the `check_ban_relationship` function inside its loops, it would cause an **N+1 Query Problem** (bombarding the database with 50+ individual queries in less than a second). Instead, the algorithms write a custom "Bulk Query" using `.in_()` clauses to fetch *all* constraints in a single network round-trip.

## Key Takeaways
* **Dead Code is Technical Debt**: Whenever a refactor occurs or a function is inlined elsewhere, delete the original file immediately. Ghost files confuse new engineers and clutter static analysis tools.
* **Context-Driven Optimization vs DRY (Don't Repeat Yourself)**: DRY is a good rule of thumb, but as a Solutions Architect, you must break the rule when scale demands it. We *could* force the automated dispatch engine to use the single `check_ban_relationship` utility to save a few lines of code, but the performance cost to the database would be severe. Two different contexts (Single Insert vs Bulk Computation) often require two distinct implementations of similar business logic.

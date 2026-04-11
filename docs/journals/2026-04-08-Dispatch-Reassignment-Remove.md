# Engineering Journal

**Date:** 2026-04-08
**Topic:** dispatch-reassignment-remove
**Session Start:** 2026-04-08 05:52 EDT
**Session End:** 2026-04-08 08:44 EDT

## Overview
Completed work on Gap #6 (Dispatch override/edit after run). Implemented the "Remove" (`DELETE`) and "Swap" (`PATCH`) endpoints which allow dispatchers to handle call-outs and reassignments gracefully while preserving database integrity.

## Problems Addressed
1. **Sick Call-outs:** Need an atomic way to drop a worker from an active day's assigned truck without deleting past records or the overall route layout.
2. **Rebalancing the Board:** Dispatchers need to swap an existing worker to a different truck, potentially creating a new `TruckAssignment` on the fly, without breaking existing rows.

## Solutions Applied
1. **Call-out Engine (`DELETE /dispatch/assign/{date}/{employee_id}`)**:
    * Implemented SQLAlchemy `.join()` logic to query an `AssignmentMember` based on context from the `TruckAssignment` table.
    * Performs a pure removal transaction for sick call-outs.
2. **Swap Engine (`PATCH /dispatch/assign`)**:
    * Handled "upsert" operations for destination truck relationships (create a `TruckAssignment` if missing, use if exists via `.flush()`).
    * Implemented explicit Edge Case/Error warnings if the user attempts to move an assignment to the truck they are already scheduled for, rather than failing silently.

## Key Takeaways
Added "Silent Failures vs Explicit Errors (REST APIs)" to the Learning Guide highlighting the UX/Architecture benefits of returning a `400 Bad Request` instead of letting logical no-ops vanish quietly.
# ADR-052: Frontend Utility Extraction and Backend Deduplication

**Date**: 2026-05-01  
**Status**: Accepted

---

## Context

Two categories of duplication had accumulated:

**Frontend**: `getLocalYMD()` (today as a local YYYY-MM-DD string) appeared as an inline function in at least 6 different files. `fileToDataUrl()` (FileReader Promise wrapper) appeared in 2 files. `isoWeekStart()` and `nWeeksAgo()` were defined inline in `OperationsAnalytics.tsx`. When timezone handling or the date formatting logic needs to change, all copies must be found and updated together — or drift.

**Backend**: Two patterns were repeated across multiple routers:
1. The four-step employee lookup chain (cognito_sub → discord_id → email → UUID fallback) was copy-pasted verbatim between `get_caller_employee` and `get_caller_employee_optional` in `deps.py`.
2. The three-role ownership check (`if caller.role not in {"dispatch","management","admin"} and caller.id != target_id`) appeared ~9 times across `field_ops.py` and `schedule.py` with minor wording variations.

An additional copy-paste bug was discovered: `schemas/employee_off_day.py` contained two identical `EmployeeOffDayUpdate` class definitions. Python silently uses the second one; the first is dead code.

---

## Decision

### Frontend: `utils/date.ts` and `utils/file.ts`

All date helpers live in `frontend/src/utils/date.ts`:

- `getLocalYMD()` — local YYYY-MM-DD (replaces 6 inline copies)
- `today` — alias for `getLocalYMD`, used where an alias reads more clearly
- `fmtDate(d: Date)` — format a Date object as YYYY-MM-DD
- `isoWeekStart(offset?)` — ISO week start, with optional offset in weeks
- `nWeeksAgo(n)` — n weeks ago as YYYY-MM-DD

File helpers live in `frontend/src/utils/file.ts`:

- `fileToDataUrl(file: File): Promise<string>` — FileReader wrapper

All inline copies in pages and components were removed and replaced with imports from these modules.

### Backend: `_resolve_employee_from_cognito`

The shared lookup chain in `deps.py` is extracted into a private function:

```python
def _resolve_employee_from_cognito(current_user: dict, db: Session) -> tuple:
    # returns (employee_or_None, sub_str)
```

`get_caller_employee` and `get_caller_employee_optional` both call it and handle only their own post-lookup logic (activation/invite vs. simple sub-stamp). The lookup logic itself has one implementation.

### Backend: `assert_owns_or_privileged`

The ownership check is a single function in `deps.py`:

```python
_PRIVILEGED_ROLES = frozenset({"dispatch", "management", "admin"})

def assert_owns_or_privileged(caller, target_id: str, resource: str = "resource") -> None:
    if str(caller.id) != str(target_id) and caller.role not in _PRIVILEGED_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"You do not have permission to access this {resource}.",
        )
```

All inline checks in `field_ops.py` (8 occurrences) and `schedule.py` (1 occurrence) replaced with `assert_owns_or_privileged(caller, target_id, "resource name")`. This also ensures the role set stays consistent — adding a new privileged role is a one-line change in `deps.py`.

### Backend: `EmployeeOffDayUpdate` duplicate removed

The second (identical) `EmployeeOffDayUpdate` class definition in `schemas/employee_off_day.py` was deleted.

---

## Consequences

- Any future change to date formatting, timezone handling, or the FileReader pattern is made in one place.
- New routers must import and call `assert_owns_or_privileged` rather than duplicating the pattern. The role set lives only in `_PRIVILEGED_ROLES`.
- Adding a new privileged role (e.g., `"supervisor"`) requires updating `_PRIVILEGED_ROLES` in `deps.py` only — not hunting through every router.
- The `EmployeeOffDayUpdate` bug would have caused silent schema drift if the two definitions had ever diverged. Now there is one definition.
- After delegating the ownership check to the helper, `schedule.py` no longer imported `HTTPException` or `status` from fastapi. Both imports were removed to keep the import list honest.

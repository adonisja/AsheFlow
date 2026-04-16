# ADR-035: Fix — `get_available_pool` Missing PTO Filter

**Date:** 2026-04-16  
**Status:** Accepted  
**Deciders:** adonisja

---

## Context

`get_available_pool` in `backend/app/services/available_pool.py` is the single function that produces the eligible employee set for every dispatch run. It excluded employees with an approved recurring off-day (`EmployeeOffDay`) but did not exclude employees with an approved `TimeOffRequest` for the target date.

`get_unavailable_staff` — the inverse function in the same file — was written correctly and excluded both. The inconsistency meant that an employee with approved PTO for a given date could still appear in the dispatch pool and be assigned to a truck on the very day they had been granted time off.

---

## Considered Options

**Option 1: Add a second `EXISTS` subquery for `TimeOffRequest` and combine with `~or_(...)`**  
Mirror the `has_off_day_today` subquery pattern with a `has_pto_today` subquery and combine both in the `.filter()` call using `~or_(has_off_day_today, has_pto_today)`. Both exclusion checks compile into the same SQL query — still a single round-trip.

**Option 2: Pull the exclusion set from `get_unavailable_staff` and subtract**  
Call `get_unavailable_staff`, build a set of excluded IDs, then filter `available_employees` against that set in Python.

**Option 3: Replace the subquery with a join-based exclusion**  
Left-join to both tables and filter on NULL — semantically equivalent but harder to read.

---

## Trade-offs

| | Option 1 | Option 2 | Option 3 |
|---|---|---|---|
| SQL round-trips | 1 | 2 | 1 |
| Consistency with existing pattern | ✅ direct match | ❌ indirect | ✅ alternative |
| Readability | ✅ clear intent | ⚠ indirect | ⚠ join syntax |
| Risk of drift | None — single location | Depends on `get_unavailable_staff` staying correct | None |

---

## Decision

Option 1. The `has_pto_today` subquery mirrors `has_off_day_today` exactly, uses the already-imported `TimeOffRequest` model, and combines via `or_` which was already imported. No new abstractions, no new round-trips, no dependency on a sibling function.

---

## Consequences

**Positive:**
- Employees with approved PTO are now correctly excluded from dispatch on the day of their approved request.
- `get_available_pool` and `get_unavailable_staff` now apply identical exclusion logic — the two functions are consistent.

**Negative / Trade-offs:**
- None. The SQL cost is identical (single query, two EXISTS subqueries).

---

## Learnings & Growth

A correctness invariant existed between `get_available_pool` (include who is available) and `get_unavailable_staff` (explain who is not). They shared the same conceptual contract but were implemented independently, allowing them to diverge. When two functions are inverses of each other, any gap in one is a bug by definition — review both when either is modified.

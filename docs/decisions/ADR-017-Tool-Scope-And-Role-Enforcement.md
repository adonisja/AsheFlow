# ADR-017: Tool Scope and Role Enforcement

**Date:** 2026-04-11
**Status:** Accepted
**Deciders:** adonisja

---

## Context

After completing the role architecture restructure (ADR-016), a second evaluation revealed that the role separation applied to the dashboard and navbar had not been fully carried through to the individual tools, backend endpoints, or page-level guards. Specific problems:

1. The fav/ban tool was accessible to trainees, who had just joined and had no basis for influencing dispatch pairings.
2. Schedule Change Requests only supported requesting a single day off (off-day request), not the full range of schedule restructuring an employee might need (add back days, drop days, or completely rework their week).
3. Field Ops was opened to all field staff during ADR-016 based on a wrong assumption — walkers and trainers do not check in at the yard and should not see this page.
4. Truck Reassignment had no today-only guard (workers could request reassignment for future dates, which is not a same-day operational concept), no active assignment check (workers with no assignment today have nothing to reassign), and no ownership check (any walker/trainer could submit a request for another employee).
5. Backend submission endpoints in `field_ops.py` had no role guard despite having an `allow_driver` constant defined. Any field staff JWT could call them.
6. The `employee_relationships.py` backend allowed trainees to create fav/ban entries despite trainees being excluded from the UI.

---

## Decisions

### 1. Fav/Ban restricted to driver, walker, trainer

**Trainees are excluded.** Rationale: Trainees have not yet established working relationships with the broader team. Fav/ban relationships influence dispatch pairing through weighted scoring. A trainee placing premature bans could interfere with their own training assignment. The feature unlocks post-graduation when the employee has been reassigned to their permanent role.

Enforcement locations:
- `employee_relationships.py`: `allow_field_staff = RoleChecker(["driver", "walker", "trainer"])` (trainee removed)
- `Preferences.tsx`: `canFavBan = groups.some(r => ['driver', 'walker', 'trainer'].includes(r))` — trainees see a placeholder message instead

### 2. Schedule Change Requests: 3-mode system replacing single off-day flow

**Considered options:**

**Option A — Keep single off-day flow, add a separate "add days back" endpoint**
Simpler backend, but splits the schedule change concept across two UI locations. Employee has to know which page to use for which action.

**Option B — Extend the existing `EmployeeOffDay` POST/DELETE to cover add/drop as-needed**
Requires off-day records to carry an approval workflow, which the current table doesn't support. Would need schema changes and would conflate "recurring off day" with "approved schedule change."

**Option C — Purpose-built `ScheduleChangeRequest` table with 3 modes (chosen)**
Separates the approval-pending concept from the live off-day record. Keeps `employee_off_days` as the authoritative schedule state. Schedule change requests are a separate workflow that mutates off-days only on approval. All three modes (add_day, drop_day, full_rework) map to deterministic mutations.

Auto-apply on approval is correct for all three modes because the mutation is fully deterministic from the request data — no additional input is needed from the reviewer. This is different from truck reassignment, where the destination truck is unknown.

**One-pending-at-a-time** is enforced at the backend and also surface-level in the UI. Since full_rework replaces the entire schedule, allowing multiple pending requests creates an undefined ordering problem.

### 3. Field Ops restricted to drivers (and admin for oversight)

**Route:** `/field-ops` → `['driver', 'admin']`
**Navbar:** `groups.includes('driver') || groups.includes('admin')`

Walkers and trainers meet at the Anchor Point, not the yard. They do not:
- Drive the vehicle (no pre-trip inspection needed)
- Check in at the yard (no check-in/departure record needed)
- Submit fuel logs (not drivers)

The walker rating submission (driver rates their walker's attendance) already uses a `driver_id` field — only drivers can submit this.

The `allow_driver` backend role guard was already defined in `field_ops.py` but was not applied to the POST endpoints. All 6 submission endpoints now include `_: dict = Depends(allow_driver)` in addition to `caller: Employee = Depends(get_caller_employee)`. Read endpoints do not require the driver role (management/admin may read inspection history).

### 4. Truck Reassignment: today-only, active assignment required, ownership enforced

**Today-only:** `requested_date` must equal `date.today()`. Truck reassignment is a same-day operational request. Future-date reassignments would sit in a dispatch queue without context (crew hasn't been finalized for that day yet). If a worker needs a recurring schedule change, they use the Schedule Changes page.

**Active assignment required:** The worker must have a `TruckAssignment` for today (via `AssignmentMember` join). If they are not assigned, there is no truck to reassign from. This prevents empty requests from cluttering the dispatch queue.

**Ownership enforced:** `payload.employee_id != caller.id` → 403. A walker cannot submit a reassignment request on behalf of another walker. This was entirely missing in the original implementation.

**Form UX change:** The date picker is removed from Preferences.tsx. The form always submits today's date. This makes the constraint visible to the user — there is no date field to try to change.

### 5. Tools separated onto their own pages with dedicated nav links

Each tool that was previously embedded inside another page now has a dedicated route and navbar entry:

| Tool | Old location | New location | Nav visibility |
|---|---|---|---|
| Schedule Change Request | Preferences.tsx (off-day form) | `/schedule-changes` | field staff + dispatch + admin |
| Truck Reassignment | Preferences.tsx | Preferences.tsx (streamlined) | walker + trainer (admin can view) |
| Field Ops | `/field-ops` (all field staff) | `/field-ops` (driver + admin only) | driver + admin |

Giving schedule changes a dedicated page allows for richer UI (current schedule display, mode selector, selectable day filtering, reviewer panel) that would be too heavy to embed inside Preferences.

---

## Consequences

- Trainees will see a placeholder in Preferences explaining fav/ban unlocks after graduation. This is user-friendly and avoids a confusing empty state.
- The Preferences page is significantly lighter — it now only contains truck reassignment and fav/ban. This is appropriate for a "quick preferences" page.
- All backend POST endpoints in `field_ops.py` will now return 403 for non-drivers, eliminating a silent authorization gap.
- The assignment_change_requests backend now enforces three constraints that were entirely missing: role check (via RoleChecker), date constraint (today-only), and active assignment constraint. This closes a submission abuse vector.
- Schedule changes are now a first-class feature with their own page, nav entry, and three operational modes. The old single off-day flow in Preferences is removed entirely.
- Future role additions must be evaluated against the `allow_field_staff` list in `employee_relationships.py` — new roles are excluded by default unless explicitly added.

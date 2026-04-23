# ADR-042: Persistent Dispatch Confirmations and Audit Log

**Date:** 2026-04-18  
**Status:** Accepted  
**Deciders:** adonisja

---

## Context

Two gaps were identified against the original spec:

1. **Dispatch confirmations were Redis-only.** The `dispatch:confirmations:{date}` hash had a 48-hour TTL. There was no historical record of who confirmed or declined, when, or across what dates. This blocked any confirmation analytics or audit trail.

2. **No audit log existed.** Approval actions (PTO approve/reject, schedule change approve/reject, assignment change approve/reject, incident resolve) were applied directly to the DB with no record of who performed them or what the state was before. Management had no way to see who approved what and when.

---

## Decisions

### `DispatchConfirmation` table alongside Redis (not replacing it)

Redis remains the read path for live dashboard queries — it is fast and the 48h TTL handles cleanup automatically. The new `dispatch_confirmations` table is the write path for durability:

- On `publish`: every assigned employee gets a `pending` row inserted (idempotent — skips existing rows).
- On `POST /dispatch/{date}/confirmations`: the row is upserted with the new status and `confirmed_at` timestamp.

Both writes happen in the same request. The table adds `source` (`discord_bot` / `manual`) and `created_at` for analytics context.

A `GET /dispatch/confirmations/history?start_date=&end_date=` endpoint was added for date-range analytics queries.

### `AuditLog` table with JSONB snapshots

A single `audit_logs` table covers all approval actions:

```
actor_id | action_type | target_table | target_id | before_snapshot | after_snapshot | created_at
```

`action_type` uses dot-namespaced verbs (`pto.approved`, `schedule_change.rejected`, `incident.resolved`) so they are filterable by prefix. `before_snapshot` and `after_snapshot` are JSONB — just the fields that changed, not the full row. This keeps rows small and diffs readable.

### `write_audit()` helper — one line per endpoint, same transaction

```python
write_audit(db, actor_id=..., action_type=..., target_table=..., target_id=..., before={...}, after={...})
db.commit()
```

`write_audit` appends to the session but does not commit. The caller commits. This means the audit row and the state change are atomic — either both land or neither does. No partial audit trails.

### Wired into 7 endpoints

| Endpoint | Action type |
|---|---|
| `PATCH /time-off-requests/{id}/approve` | `pto.approved` |
| `PATCH /time-off-requests/{id}/reject` | `pto.rejected` |
| `PATCH /schedule-change-requests/{id}/approve` | `schedule_change.approved` |
| `PATCH /schedule-change-requests/{id}/reject` | `schedule_change.rejected` |
| `PATCH /assignment-change-requests/{id}/approve` | `assignment_change.approved` |
| `PATCH /assignment-change-requests/{id}/reject` | `assignment_change.rejected` |
| `PATCH /incidents/{id}/resolve` | `incident.resolved` |

### `GET /audit/` — filterable, management and admin only

Accepts `action_type` (prefix match), `actor_id`, `target_table`, `start_date`, `end_date`. Joins `employees` to return `actor_name` alongside the UUID.

---

## Consequences

**Positive:**
- Confirmation history is now queryable across any date range.
- Every approval action is traceable — who did it, when, and what changed.
- `write_audit` is a one-liner — adding audit coverage to a new endpoint takes under 10 seconds.
- The audit row is in the same transaction as the state change — no orphaned audit entries.

**Negative / Trade-offs:**
- Every approval endpoint now has two writes per request (state change + audit row). Negligible at this scale.
- `before_snapshot` and `after_snapshot` are manually constructed — they reflect what the developer chose to capture, not a guaranteed full-row diff. If a field is omitted from the snapshot it won't appear in the audit trail.
- Actor resolution uses `current_user.get("id")` (Cognito sub), which may not match `employee.id` (DB UUID). `write_audit` attempts a UUID parse and silently skips if the actor cannot be resolved — acceptable since the action is still recorded, just without an actor link.

---

## Files Created / Modified

| File | Type |
|---|---|
| `backend/app/models/dispatch_confirmation.py` | New |
| `backend/app/models/audit_log.py` | New |
| `backend/app/services/audit.py` | New — `write_audit()` helper |
| `backend/app/routers/audit.py` | New — `GET /audit/` endpoint |
| `backend/app/routers/dispatch.py` | Modified — DB seeding on publish, upsert on confirmation |
| `backend/app/routers/time_off_requests.py` | Modified — `write_audit` on approve/reject |
| `backend/app/routers/schedule_change_requests.py` | Modified — `write_audit` on approve/reject |
| `backend/app/routers/assignment_change_requests.py` | Modified — `write_audit` on approve/reject |
| `backend/app/routers/incidents.py` | Modified — `write_audit` on resolve |
| `backend/app/main.py` | Modified — registered `audit` router |
| `backend/app/models/__init__.py` | Modified — registered new models |
| `backend/alembic/versions/d3f2a1b4c5e6_...` | New — `dispatch_confirmations` migration |
| `backend/alembic/versions/e1a2b3c4d5f6_...` | New — `audit_logs` migration |

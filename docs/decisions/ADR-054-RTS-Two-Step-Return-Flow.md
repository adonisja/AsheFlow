# ADR-054 — RTS Two-Step Return Flow

**Date:** 2026-05-02
**Status:** Accepted

---

## Context

The initial implementation used a single `RTSClearance` model for the return leg of the shift. After discussion, it became clear this conflated two physically distinct events with different actors, different locations, and different purposes.

---

## The Two Events

### Event 1 — Field: Driver submits before leaving the AP area

- **Where:** Still in the field (AP or nearby)
- **What:** Driver confirms all crew are back on the truck, lists every undelivered package grouped by reason and count
- **Who acts next:** Dispatch reviews and approves or rejects
- **Gate:** Driver **cannot leave the field** until dispatch approves
- **Purpose:** Ensures dispatch has visibility into what's coming back before it arrives, and can hold a driver if something doesn't add up

### Event 2 — Station: Driver confirms physical handoff after arriving back

- **Where:** At the station dock
- **What:** Driver confirms how many totes were returned and how many RTS packages were physically scanned/handed back
- **Who acts next:** No approval needed — this is a confirmation, not a request
- **Gate:** Requires Event 1 to be `approved` (can't do a handoff if you were never cleared to leave)
- **Purpose:** Closes the loop — reconciles the field report against what was actually returned

---

## Decision

Split into two models: `RTSReport` (Event 1) and `StationHandoff` (Event 2).

**Rejected alternative:** A single model with a `phase` field (`"field_report"` | `"station_handoff"`). This was simpler but wrong — the two events have different fields (`crew_confirmed` + `rts_packages` vs `totes_returned` + `rts_count`), different access controls (driver submits both, but dispatch only reviews Event 1), and different semantic meanings. Forcing them into one table would require nullable columns for each phase's fields, making the schema misleading.

**Rejected alternative:** Extending `StationArrival (return)` to carry tote/RTS data. The arrival record timestamps when the driver shows up at the station — it shouldn't also carry inventory data. Separation of concerns.

---

## Enforcement

`StationHandoff` enforces the gate at the application layer:

```python
rts_report = db.query(RTSReport).filter(
    RTSReport.driver_id == payload.driver_id,
    RTSReport.date == payload.date,
).first()
if not rts_report or rts_report.status != "approved":
    raise HTTPException(400, "Your RTS report has not been approved by dispatch yet.")
```

This is intentionally application-level (not a DB constraint) because the gate is business logic, not a referential integrity rule.

---

## Fields

**`RTSReport`**
| Field | Purpose |
|---|---|
| `crew_confirmed` | How many crew members are accounted for on the truck |
| `rts_packages` | JSONB list of `{reason, count}` |
| `total_rts` | Denormalized sum for fast queries |
| `status` | `pending | approved | rejected` |
| `dispatch_notes` | Optional notes from dispatch on review |
| `reviewed_by` | UUID of the dispatch employee who reviewed |
| `reviewed_at` | Timestamp of review |

**`StationHandoff`**
| Field | Purpose |
|---|---|
| `totes_returned` | Physical tote count handed back at the dock |
| `rts_count` | Physical RTS package count scanned/handed back |
| `notes` | Optional driver notes (damaged totes, discrepancies, etc.) |

---

## Reconciliation

The `rts_count` in `StationHandoff` should match `RTSReport.total_rts`. Discrepancies (e.g. a package found in the truck after arrival) are surfaced in the `station-handoffs/summary` endpoint which includes both values. No automated rejection — management reviews discrepancies manually.

# ADR-055 — Dashboard Audit: Fleet Status Source and Shift Ops Panels

**Date:** 2026-05-02
**Status:** Accepted

## Context

After the shift lifecycle backend was built, a dashboard audit revealed three categories of defects across WorkerView, DispatchView, DispatchHome, and ManagementView:

1. **Fleet Today KPI was always 0/0** — both DispatchView and ManagementView read fleet status from `Departure` rows, which don't exist until drivers actually depart. Early morning the metric was permanently empty, making it useless for dispatch planning.

2. **No shift ops visibility for management or dispatch** — RTS Return Requests (requiring dispatch approval), driver check-ins, and station handoffs were all backend-complete but had no frontend surface.

3. **Inspection type invisible** — Now that both pre-trip and EOD inspections coexist in the same table, the management inspection view couldn't distinguish between them.

## Decision

### Fleet Status Source
Use `TruckAssignment.status` (planned / active / completed) as the canonical source for fleet location state. The response from `GET /dispatch/{date}` already includes `truck_assignments: [{truck_id, status}]` added in the previous session.

**Rejected alternative:** Keep using `Departure` rows but offset the metric to only appear after a threshold time. This would still fail before any departures and adds unnecessary complexity.

### Inspection Type Column
Add a Type badge column to the inspections table using `inspection_type` from the summary response. Use distinct colors (primary for pre-trip, info for EOD) so management can scan the table type at a glance.

**Rejected alternative:** Split into two separate tables. Unnecessary; both types are part of the same daily inspection workflow and managers benefit from seeing them in sequence.

### Shift Ops Panels (ManagementView)
Add a 3-panel row (Driver Check-Ins, RTS Return Requests, Station Handoffs) using existing shift-ops summary endpoints. This is read-only for management; approve/reject actions live in the Dispatch view where the operational workflow belongs.

### RTS in DispatchHome and DispatchView
Add RTS pending count as a KPI card and a full approve/reject panel in both DispatchHome and DispatchView. Dispatch is the right owner for the approval gate.

## Consequences

- Management Fleet Today KPI now shows correctly from dispatch time onward (all trucks start as `planned`, reflecting the actual fleet size even before departures).
- The `planned` count gives dispatch a pre-departure baseline that `Departure` rows can never provide.
- Dispatch and management both have RTS visibility with appropriate action scopes (dispatch can approve, management read-only).
- Pre-trip and EOD inspections are visually distinguishable in the management table.

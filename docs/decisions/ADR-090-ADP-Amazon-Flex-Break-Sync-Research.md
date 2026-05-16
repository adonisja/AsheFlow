# ADR-090: ADP + Amazon Flex Break Time Sync — Research & Roadblocks

**Date:** 2026-05-16
**Status:** Parked — pending Amazon Business Coach consultation

## Problem

Field crews must sign out for breaks in both Amazon Flex and ADP independently. Manual dual-entry causes compliance risk due to time misalignment and human error (delays switching between apps, forgetting to log).

## Goal

Build AsheFlow as a single break entry point that eliminates dual manual entry and enforces a consistent break time across both systems.

## Research Findings

### ADP
- Full read/write API exists via `POST /events/time/v1/clock.punch`
- Supports break-type punch events (meal break, rest break)
- Crew-level variant: `POST /events/time/v1/crew-clock.punch`
- Authentication: OAuth 2.0 + mutual TLS (X.509 client certificate required)
- Access gated via ADP Marketplace partner program OR API Central add-on on existing account
- Deputy (third-party scheduling app) already uses this in production — confirms the write path works
- **First step:** Contact ADP account rep and ask specifically about API Central for internal integrations (may bypass full Marketplace partner track)

### Amazon Flex (DSP Employee Version)
- The app DOES capture break times via its "Breaks" menu — confirmed by in-app screenshot
- Amazon almost certainly logs these server-side
- **No public API, portal export, or data feed exists** for DSP owners to retrieve employee break records from Amazon's systems
- No reverse-engineering documentation of the DSP employee app's break endpoints exists publicly
- All research dead-ends at the same wall: Amazon captures the data but does not expose it to the employer

### GroundCloud (noted for reference only)
- Leading DSP workforce tool — does NOT integrate with Amazon Flex to read break data
- Operates its own parallel break tracking independent of Flex
- FedEx-oriented competitor — not relevant to Amazon DSP ecosystem

## Proposed Approaches

### Option A — AsheFlow as single ADP entry point (immediately actionable)
Workers tap Start/End Break in AsheFlow. AsheFlow pushes to ADP via `clock.punch` API. Workers still tap breaks in Amazon Flex separately for Amazon's records. Eliminates the payroll compliance risk — ADP is accurate and automatic. Amazon Flex side remains manual but is no longer the source of truth for payroll.

**Verdict:** Feasible as soon as ADP API access is obtained. Solves the primary compliance problem.

### Option B — True single tap (one entry point for both systems)
AsheFlow pushes to ADP via API. Amazon Flex break is automated on company-issued Android devices via Android Accessibility API or similar device scripting. Legally grey but not clearly prohibited on employer-controlled hardware. Achieves true zero-duplicate-entry for the worker.

**Verdict:** Technically possible. Requires legal/compliance review before pursuing. Not a priority until Option A is live.

## Open Questions / Blockers

1. **ADP API access** — Call ADP account rep: *"Can we get API Central access for an internal integration without going through the full Marketplace partner track?"* This is the gating question for all of this.
2. **Amazon Business Coach** — Ask directly: *"Is there a data feed or portal export for employee break records?"* Closes the loop definitively on the read-from-Flex question.
3. **Amazon Flex ToS review** — If pursuing Option B, legal review of whether automating the Flex app on company hardware violates the DSP agreement.

## What to Build (AsheFlow Side — ready to design)

Regardless of which option is chosen, the AsheFlow data model and UI are the same:
- `BreakRecord` model: `employee_id`, `shift_date`, `break_start`, `break_end`, `break_type` (meal/rest), `adp_synced`, `company_id`
- Start Break / End Break buttons in the driver FieldOps view
- Backend service that queues and pushes `clock.punch` to ADP on break events
- Sync status visible to dispatch/management

Design and implementation of the AsheFlow side can proceed independently of ADP API access — the push service can be built with a feature flag and activated once credentials are obtained.

# ADR-012 — Trainer Continuation Requests

**Date:** 2026-04-10  
**Status:** Accepted  
**Author:** adonisja

---

## Context

Trainees often develop productive working relationships with specific trainers.
A mechanism was needed for trainees to express a preference for continuation
without creating social pressure or revealing acceptance/rejection outcomes.

---

## Decision Drivers

1. **Silent process.** Trainees must not know whether a trainer accepted or
   rejected their request. This protects the trainer-trainee relationship and
   removes performance anxiety from the trainee.

2. **Non-binding.** An accepted request is honoured only if the trainer is
   actually dispatched on the trainee's next day. Unavailability nullifies the
   request without error — the trainee is simply paired normally.

3. **Auto-expiry.** If a trainer neither accepts nor rejects before the trainee's
   next dispatch day, the request expires automatically. No stale state persists.

4. **One active request at a time.** Submitting a new request while one is
   pending/accepted replaces the old one to prevent conflicting state.

---

## Key Design Decisions

### Why `"nullified"` for both reject and expiry

Using a single terminal state `"nullified"` (rather than separate `"rejected"`
and `"expired"` statuses) prevents the trainee from inferring the outcome by
reading their own request status. If `"rejected"` were a visible status, a
trainee could poll the endpoint to see if their request was explicitly rejected
vs. still pending. `"nullified"` is opaque — it covers rejection, expiry, and
post-honour cleanup alike.

### Why availability is checked via `assigned_crews` not the available pool

The request is honoured only if the trainer was actually dispatched to a truck
today — not merely available in the pool. A trainer in the pool but not assigned
to any truck is not physically present in the field, so pairing would be
meaningless. `assigned_crews` is already in memory during injection, so no
additional DB query is needed.

### Why the trainee receives no submission confirmation

The `POST /continuation-requests/` returns an empty `{}` body with 201. Showing
a "request submitted" confirmation in the UI would be the only acceptable
exception — but even that should not reveal trainer identity or request status
after the fact. The UI should use the 201 status code only to confirm the
network call succeeded, not to display request details.

### Why notification goes to trainer only

The trainer needs to act. The trainee does not. Sending a notification to the
trainee on submit would encourage them to check status, which conflicts with
the silent design.

---

## Consequences

**Positive:**
- Fully silent from the trainee's perspective — no outcome is revealed
- Auto-expiry prevents stale accepted requests from being honoured weeks later
- One-request-at-a-time constraint avoids conflicting pairings
- No changes to the dispatch algorithm — continuation is resolved inside
  training_injection, after dispatch has already run

**Negative:**
- A trainer who forgets to respond has their silence treated as a rejection
  (expiry). This is the correct behaviour but may occasionally be surprising.
- Trainee cannot cancel a pending request — submitting a new request is the
  only mechanism (which nullifies the old one). This could be a future enhancement.
- Trainer availability check is strict (must be assigned to a truck). A trainer
  who was available but not dispatched today cannot fulfil an accepted request.

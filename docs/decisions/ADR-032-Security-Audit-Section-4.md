# ADR-032: Security Audit — Section 4 Feature Gaps and Polish

**Date:** 2026-04-15  
**Status:** Accepted  
**Deciders:** adonisja

---

## Context

The fourth and final section of the audit addressed feature gaps and input validation holes that were not security vulnerabilities but represented real operational and reliability risks. Four items were fixed.

---

## Decisions

---

### 4.1 — Notification Bell: Polling vs. WebSockets

**Decision:** Implement a 30-second polling loop in a `useNotifications` hook inside the Navbar, rather than WebSockets or SSE.

**Why polling?** The AsheFlow notification types are operational alerts — schedule approvals, incident acknowledgements, training updates. These are not latency-sensitive (a 30-second delay is acceptable). Polling requires no additional infrastructure, no persistent connection, no backend changes, and degrades gracefully if the network is flaky. WebSockets would require a separate connection management layer (authentication on the WS handshake, reconnect logic, heartbeats) for a marginal improvement in delivery latency.

**Why 30 seconds?** Long enough to avoid unnecessary server load from many concurrent users; short enough to feel reasonably live in an operational context. Adjustable without architectural changes.

**Why a hook inside Navbar rather than a context?** Adding notification state to `AuthContext` would conflate auth state with operational data. A separate `NotificationContext` would be the right long-term home — but the Navbar is the only consumer right now, so the hook lives there. If a second consumer appears, extracting to a context is a straightforward refactor.

**Why `GET /employees/me` rather than reading from AuthContext?** AuthContext stores Cognito user data (username, groups) — not the employee DB UUID. The notification endpoint takes the DB UUID. Storing the DB UUID in AuthContext would widen its scope beyond its purpose. The `GET /employees/me` call is made once per session and cached in hook state.

---

### 4.2 — NotificationBanner: Pattern Matching vs. Exhaustive Type List

**Decision:** Replace the `Record<union, style>` approach with a `styleForType(type: string)` function using suffix/substring pattern matching.

**Why not an exhaustive union?** The backend notification type set will grow as new workflows are added. An exhaustive union in the frontend requires a coordinated code change every time a new backend notification type is introduced — otherwise new types silently fall through to an incorrect default style. A pattern-matching function is forward-compatible: any type ending in `_approved` gets green, `_rejected` gets red, etc.

**Trade-off accepted:** The pattern approach is less explicit than an exhaustive union. If a future type is named in a way that doesn't match the pattern (e.g. `crew_reassigned`), it will fall through to the info style (blue) — a safe, neutral fallback rather than a green checkmark.

---

### 4.3 — Input Length Caps: Schema Layer vs. DB Column vs. Middleware

**Decision:** Enforce all length caps in Pydantic `Field(max_length=...)`, not in SQLAlchemy column definitions or application-level middleware.

**Why Pydantic?** Consistent with the established pattern (photo size caps in Section 1 used Pydantic validators). Pydantic runs before the DB is touched, returns structured 422s with field-level error messages, requires no DB migration, and is easy to locate and adjust. A `String(max_length=N)` column in SQLAlchemy raises a DB-level error on some drivers, silently truncates on others, and produces no useful error message either way.

**Why not middleware?** A body size limit in middleware (e.g. `max_body_size=10KB`) is too coarse — it would reject a legitimate request that has a large photo alongside short text fields. Field-level caps are surgical.

**Cap sizes chosen by use case:**
- 2 000 chars: narrative fields where a paragraph is appropriate (incident descriptions, training comments, feedback messages).
- 500 chars: operational context fields (reasons, notes) where a sentence or two is sufficient.
- 200–300 chars: structured fields that are names or locations — not prose.

---

### 4.4 — Data Refresh: Manual Button vs. Automatic Interval

**Decision:** Add a manual refresh button to ManagementView and DispatchDashboard. Do not add automatic background polling.

**Why manual rather than automatic?** Both pages are used by a small number of management/dispatch users (not field staff). An automatic poll on every management session adds server load for modest benefit. A manual button gives the user control — they refresh when they need current data, such as before a meeting or after an incident is reported.

**Why not shared infrastructure (e.g. a global `useRefreshable` hook)?** Only two components needed this. Extracting a shared hook for two callsites is premature — it introduces abstraction with one real consumer and one likely future consumer. If a third page needs the same pattern, the abstraction should happen then.

**ManagementView: `Promise.allSettled` vs. sequential awaits**

**Decision:** Use `Promise.allSettled` for all seven parallel fetches.

**Why `allSettled` over `Promise.all`?** `Promise.all` fails fast — if `GET /field-ops/no-shows` returns 503, none of the other panels load. `Promise.allSettled` allows the five successful panels to populate while the one failed panel shows its existing `null`/empty state. In an operational dashboard, partial data is preferable to a blank page.

---

## Consequences

**Positive:**
- Every authenticated user now sees unread notifications regardless of which page they are on.
- All future backend notification types automatically get an appropriate style without frontend changes.
- Unbounded string payloads are now rejected at the API boundary with clear error messages.
- Management and dispatch users can get current data without navigating away.
- `Promise.allSettled` in ManagementView makes the dashboard resilient to individual endpoint failures.

**Negative / Trade-offs:**
- 30-second polling adds one `GET /notifications/{id}` request per user per 30 seconds while the app is open. At small user counts this is negligible; at scale, a WebSocket or SSE approach should replace it.
- Pattern-based notification styling is less explicit than an exhaustive union. New types that don't match patterns fall back to the info style (acceptable, not incorrect).
- The 2 000-char cap on incident descriptions could be restrictive for very detailed incident narratives. The cap is intentionally generous and can be raised in the schema without a migration if needed.

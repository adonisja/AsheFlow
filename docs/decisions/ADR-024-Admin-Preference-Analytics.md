# ADR-024: Admin Preference Analytics View

**Date:** 2026-04-15  
**Status:** Accepted  
**Deciders:** adonisja

---

## Context

The `/preferences` route serves two completely different purposes depending on the caller's role:

- **Field staff (driver / walker / trainer):** Manage their own fav/ban lists and submit truck reassignment requests.
- **Admin:** No personal preferences to manage. Needs system-wide visibility into how the workforce has expressed preferences so they can spot dispatch tension before it becomes a problem.

The previous implementation gave admin an employee selector that, when used, showed a single employee's preferences. This was both awkward (admin had to click through records one at a time) and structurally wrong (admin's value is in the aggregate, not the individual).

---

## Decision

Implement a dedicated `PreferenceAnalytics` component and branch the `Preferences` page at the top:

```typescript
if (isAdmin) return <PreferenceAnalytics />;
```

The analytics component provides:

1. **KPI row** — total favs, total bans, field-staff coverage %, mutual conflict count
2. **Role Interaction Matrix** — 3×3 heatmap (driver/walker/trainer) showing how roles target each other, togglable between favs and bans
3. **Most Favoured / Most Banned leaderboards** — top-10 targets, expandable to show who favours/bans them, with mutual-ban badges
4. **Mutual Conflicts section** — explicit list of pairs who mutually ban each other (hard dispatch constraints)

---

## Alternatives Considered

### A — Embed analytics inline below the existing selector

Admin would still see the selector, and analytics would appear beneath it. Rejected because the selector is now meaningless when aggregate analytics are present, and mixing individual + aggregate views in one scroll is confusing.

### B — Separate route (`/admin/preferences`)

Would require updating the navbar and adding a new protected route. Rejected because the user mental model is "preferences → analytics for admin, editor for everyone else." One route, branched rendering keeps the URL space clean.

### C — Move analytics to AdminDashboard

Dashboard already has KPIs. Adding preference analytics there would make it too wide. Preference analytics is a dedicated tool, not a dashboard widget.

---

## Consequences

**Positive:**
- Admin sees a purpose-built view immediately on page load — no selector click required.
- Field staff are unaffected; their editor is unchanged.
- No backend changes required — existing endpoints already return full data for admin callers.
- Mutual conflicts surface explicitly, giving admin a pre-dispatch warning before running dispatch.

**Negative / Trade-offs:**
- Admin cannot view or edit an individual employee's preferences from this page. If that becomes necessary, a separate admin tool should be built rather than re-adding the selector to this page.

---

## Implementation Notes

- `empMap` (id → employee) is built once via `useMemo` and reused by all derived computations.
- Matrix color intensity is relative (`value / matrixMax`), not absolute, so the heatmap remains readable at any data volume.
- Coverage % counts only field staff (driver/walker/trainer). Admin/management/dispatch/trainee preference counts are excluded as they have no dispatch relevance.
- Mutual ban detection uses a set membership check (`banSet.has(reverse)`) rather than a nested loop — O(n) not O(n²).

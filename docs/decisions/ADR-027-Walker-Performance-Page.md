# ADR-027: Walker Performance Page with Letter Grades

**Date:** 2026-04-15  
**Status:** Accepted  
**Deciders:** adonisja

---

## Context

Walker performance data was collected (presence, stars, comments) but only surfaced as a week-scoped summary card with no drill-down, no historical context, and no normalised signal management could act on. A manager seeing "84% presence, 3.7 ★" had to interpret that in isolation without knowing whether this was an improvement, a decline, or just noise.

---

## Decision

Build a dedicated `/walker-performance` page providing:

1. **All-time letter grade (A–F)** per walker, computed from a weighted formula: 50% presence rate + 50% avg star rating.
2. **Fleet-level KPIs**: total walkers, fleet avg rating, fleet avg presence, at-risk count.
3. **Grade distribution bar chart**: instant fleet health snapshot.
4. **At-risk callout section**: walkers with D/F grade or ≥3 all-time no-shows.
5. **Sortable/filterable leaderboard** with all KPIs per walker.
6. **Per-walker profile panel** (slide-in): full rating history with driver names, comments, and a trend indicator.

---

## Grade Formula

```
combined = (presence_rate / 100) * 0.5 + (avg_stars / 5.0) * 0.5
A ≥ 0.90 | B ≥ 0.75 | C ≥ 0.60 | D ≥ 0.45 | F < 0.45
```

Equal weighting reflects that presence and quality of service are both essential. A walker who never shows up cannot be graded on stars alone; a walker who always shows but receives consistent 1-star ratings is a quality failure regardless of attendance.

---

## Alternatives Considered

### A — Expand the dashboard card with an inline history toggle

Each walker row on the dashboard card would expand in place to show their history. Rejected because the dashboard card is already space-constrained, history tables need horizontal space to show driver name + date + stars + comment, and the dashboard should remain a summary surface.

### B — Stars-only ranking

Rank walkers purely by avg_stars, ignore presence. Rejected because presence is operationally more critical — a no-show walker blocks dispatch regardless of their star history. Both dimensions must contribute.

### C — Percentile ranking instead of letter grades

Rank each walker as a percentile of the fleet (top 20%, etc.). Rejected because percentile rankings are relative — if the whole fleet performs poorly, top 20% still gets an "A." Letter grades with fixed thresholds give an absolute signal: a C-grade is a C-grade regardless of fleet composition.

---

## Consequences

**Positive:**
- Management has a single actionable signal (grade) per walker for performance conversations.
- At-risk walkers are surfaced explicitly rather than requiring manual scanning.
- Driver comments are finally visible to management (they were collected but never surfaced).
- Trend indicator distinguishes one-off bad weeks from sustained decline.

**Negative / Trade-offs:**
- Grade thresholds (A ≥ 90%, etc.) are fixed and may need adjustment as the team scales or seasonal patterns emerge. They should be revisited if the grade distribution consistently skews one direction.
- The 50/50 weighting is an assumption — if management decides presence matters more than star quality (or vice versa), the formula should be updated in one place (the backend endpoint) and grades will recompute automatically on next load.
- Walkers with very few shifts (1–3) will have noisy grades. A minimum shift threshold before grading could be added in the future.

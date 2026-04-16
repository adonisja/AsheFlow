# ADR-028: Walker Performance Improvements (Threshold, Date Filter, CSV, Consistency)

**Date:** 2026-04-15  
**Status:** Accepted  
**Deciders:** adonisja

---

## Context

The initial Walker Performance page (ADR-027) was complete but four known gaps remained:

1. Walkers with very few shifts could receive misleading grades.
2. Management had no way to view a walker's recent performance in isolation.
3. There was no way to extract walker data for HR review cycles.
4. Driver rating bias was undetectable — one low-rating driver could drag down a walker's grade unfairly.

---

## Decisions

### 1. Minimum Shift Threshold Before Grading

Added a `min_shifts` query parameter to `GET /field-ops/walker-leaderboard` (default 1 for API consumers; UI defaults to 5). Walkers below the threshold receive `grade: null` and `grade_eligible: false` in the response.

**Why not hardcode the threshold in the backend?**  
Management may want to see all walkers regardless of shift count (e.g., for a new hire review). Making the threshold a UI-selectable parameter gives flexibility without adding an admin settings table. The backend accepts the value; the UI controls the default.

**Why 5 as the UI default?**  
5 shifts represents roughly one week of full deployment. Fewer than 5 data points produce a grade whose confidence interval spans multiple grade bands.

### 2. Date Range Filter in the Profile Panel

Date filtering applies to the `ratings` list only — all-time KPIs (total shifts, grade, avg stars) are always computed from the full history. This is intentional: filtering the KPIs would change the grade displayed in the panel header, creating an inconsistency with the leaderboard grade. The panel header always reflects the canonical, all-time grade.

**Why not a preset selector (Last 30d / Last Quarter)?**  
Presets require date arithmetic on the frontend and drift as time passes. A plain date range input is more precise and requires no maintenance.

### 3. CSV Export (Client-Side)

The export function operates on the already-fetched `visible` array, requiring no new backend endpoint. The file reflects the currently active name search and grade filter, so management can export a subset (e.g., all D/F walkers only).

**Why not a server-side export endpoint?**  
The leaderboard dataset is small (tens to low hundreds of walkers). Client-side CSV construction from already-loaded data is simpler, faster, and avoids adding an authenticated file-download endpoint. If the dataset ever grows large enough that lazy-loading or pagination is needed, a server-side endpoint would be the right call at that point.

### 4. Driver Consistency Score

**Flag threshold: ≥1.0 star deviation from walker mean.**  
On a 1–5 scale, 1.0 star is a 20% swing. Any driver whose average for a walker deviates by this much is an outlier worth investigating. A lower threshold (0.5 stars) would flag too many drivers in a small shift sample.

**Why not show consistency on the leaderboard?**  
Consistency is a second-order metric — it tells you something about the reliability of a grade, not the grade itself. Surfacing it in the per-walker profile panel keeps the leaderboard uncluttered and puts the signal where management can act on it (during a specific performance conversation).

**Why only show the section when ≥2 drivers have rated the walker?**  
With only one driver, there is no comparison to make. Showing a "consistency" section with a single driver would be misleading.

**Limitations:**
- A driver with a single shift and a low rating will appear flagged regardless of whether it's bias or a genuinely bad shift. This is unavoidable without a minimum-shift-per-driver filter, which could be added later.
- The consistency endpoint excludes no-shows (no stars to compare). This is correct — driver bias only manifests in rated, present shifts.

---

## Consequences

**Positive:**
- Grades now have statistical defensibility via the threshold gate.
- Management can quickly assess recent performance trends without losing the all-time grade.
- HR has a one-click export path for review cycles.
- Driver bias — previously undetectable — is now surfaced as a first-class signal.

**Negative / Trade-offs:**
- The minimum shift threshold adds a concept that needs explaining (the info banner handles this).
- The consistency score can produce false positives for drivers with very few shifts — acknowledged in the UI note.
- CSV export always reflects the in-memory state; if the page hasn't been freshly loaded, exported data may not reflect the latest DB state. This is acceptable for HR review cycles which are not real-time.

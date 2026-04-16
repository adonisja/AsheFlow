# Journal: Walker Performance — Four Improvements
**Date:** 2026-04-15

---

## Context

After the initial Walker Performance page shipped, four improvements were identified and implemented in the same session:

1. Minimum shift threshold before grading
2. Date range filter in the profile panel
3. CSV export for HR review cycles
4. Driver consistency score with bias flagging

---

## 1. Minimum Shift Threshold

**Problem:** A walker with 1–2 shifts could receive an A or F grade based on almost no data, making the grade meaningless and potentially unfair.

**Backend change — `GET /field-ops/walker-leaderboard`:**
- Added `min_shifts: int = 1` query param (default 1 to match old behaviour, UI defaults to 5).
- Each walker in the response now includes `grade_eligible: bool`.
- Walkers with `total_shifts < min_shifts` receive `grade: null` and `grade_eligible: false`.
- Grade formula extracted to module-level `_walker_grade()` helper so both leaderboard and profile endpoints share the same implementation.

**Frontend changes — `WalkerPerformance.tsx`:**
- Threshold selector in the page header (All / ≥3 / ≥5 / ≥10 shifts).
- Changing the threshold re-fetches the leaderboard with the new `min_shifts` param.
- `GradeBadge` now renders "Ungraded" (italic) instead of "No data" when grade is null.
- Ungraded walkers in the table show their shift count in italics next to their name.
- Info banner shown when ungraded walkers exist, explaining the threshold and how to change it.
- Grade distribution chart and at-risk callout only count grade-eligible walkers.
- Grade filter dropdown gains an "Ungraded" option when ungraded walkers are present.

---

## 2. Date Range Filter in Profile Panel

**Problem:** The profile panel always showed all-time history. For a long-tenured walker, management couldn't quickly see how they've been performing recently (e.g., last quarter).

**Backend change — `GET /field-ops/walker-profile/{walker_id}`:**
- Added `start_date: Optional[date]` and `end_date: Optional[date]` query params.
- All-time KPIs (total_shifts, present_shifts, no_show_count, avg_stars, presence_rate, grade) always reflect the full history — filtering only affects the `ratings` list.
- The `ratings` entries now also include `driver_id` (useful for the consistency section to correlate).

**Frontend changes — `WalkerProfilePanel`:**
- Date range bar added below the panel header with two `<input type="date" />` fields and a "Clear" button.
- `fetchProfile` is a `useCallback` that rebuilds the query string from `startDate`/`endDate` and re-fetches whenever either changes.
- When a filter is active: the history count label says "N in range" and shows "filtered" in primary colour; the empty state message changes to "No ratings in this date range."
- When `walkerId` changes, start/end dates reset to empty.
- KPI strip retains all-time numbers regardless of the date filter, so the grade panel header remains accurate.

---

## 3. CSV Export

**Problem:** HR review cycles require pulling walker performance data out of the app. Previously this meant manual copy-paste.

**Implementation — client-side only:**
- `exportToCSV(walkers, minShifts)` function constructs a CSV string from the `visible` (filtered + sorted) leaderboard array.
- Columns: Name, Grade, Grade Eligible, Avg Stars, Presence %, Total Shifts, Present, No-Shows.
- For ungraded walkers, the Grade column shows "< N shifts" so the reason is self-documenting.
- Values are double-quote escaped. File name includes today's ISO date: `walker-performance-2026-04-15.csv`.
- Download triggered via `URL.createObjectURL` + programmatic `<a>` click; URL revoked immediately after.
- "Export CSV" button appears in the page header next to the threshold selector, only when data is loaded. It exports whatever is currently visible (respecting name search and grade filter), so management can export a subset if needed.

No backend change required — all data is already in the client after the leaderboard fetch.

---

## 4. Driver Consistency Score

**Problem:** A walker might receive wildly different ratings from different drivers — one driver consistently gives 2 stars while others give 4–5. This could indicate driver bias rather than walker quality variation, but there was no way to surface it.

**Backend — new `GET /field-ops/walker-consistency/{walker_id}`:**
- Returns only rated + present shifts (no-shows have no stars to compare).
- Groups ratings by driver, computes each driver's avg stars for this walker.
- Returns:
  - `walker_avg_stars`: overall mean across all drivers
  - `flag_threshold`: 1.0 (hardcoded, returned so the frontend can display it)
  - `drivers[]`: each driver's `shift_count`, `avg_stars`, `deviation` (their avg minus walker avg), and `flagged` (abs deviation ≥ 1.0)
- Sorted by absolute deviation descending (most extreme first).

**Frontend — `DriverConsistencySection` component:**
- Fetches consistency data on mount inside the profile panel.
- Hidden entirely if fewer than 2 drivers have rated the walker (no comparison possible).
- Shows a warning badge in the section header when any drivers are flagged.
- Explanatory note: "Flagged drivers deviate ≥1.0 star from this walker's overall average. This may indicate driver rating bias rather than actual performance variation."
- Each driver row shows: name, flag icon (if flagged), shift count, avg stars, deviation (+/- colour-coded), and a proportional bar. Flagged rows get a warning-coloured border and bar.

**Flag threshold rationale:** 1.0 star on a 1–5 scale represents a 20-point swing. A driver consistently rating a walker 3.0 when others give 4.5 is a statistically meaningful signal worth investigating. Smaller thresholds produce too many false positives given the low shift counts typical in early operation.

---

## Files Changed

| File | Change |
|---|---|
| `backend/app/routers/field_ops.py` | Extracted `_walker_grade()` helper; added `min_shifts` param to leaderboard; added `start_date`/`end_date` params to profile; added new `GET /walker-consistency/{walker_id}` endpoint |
| `frontend/src/pages/WalkerPerformance.tsx` | Full rewrite: threshold selector, CSV export, ungraded handling, date range filter in profile panel, `DriverConsistencySection` component |

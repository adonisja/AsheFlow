# Journal: Walker Performance Page
**Date:** 2026-04-15

---

## Problem

The "Walker Performance (This Week)" card on the management dashboard showed each walker's presence rate, no-show count, and avg stars for the current Mon–Sun window. This was useful for week-by-week operational awareness but had several gaps:

- **No all-time view** — a walker could have a great week and terrible overall history, or vice versa. No way to see the aggregate picture.
- **No individual rating history** — the `comment` field on `WalkerRating` was collected from drivers but surfaced nowhere.
- **No grade/tier system** — managers had to interpret raw numbers (84% presence, 3.7 stars) themselves with no normalised signal.
- **No identification of at-risk walkers** — no way to quickly see who needs a performance conversation.
- **No drill-down** — clicking a walker in the dashboard did nothing.

---

## What Was Built

### Backend

**`GET /field-ops/walker-leaderboard`** — All-time performance summary for every active walker. Queries all `WalkerRating` rows for active walkers, aggregates total/present/no-show counts and avg stars, then computes a letter grade (A–F) for each walker using the formula:

```
presence_score = presence_rate / 100           (weight 0.5)
star_score     = avg_stars / 5.0               (weight 0.5)
combined       = presence_score * 0.5 + star_score * 0.5

A ≥ 0.90, B ≥ 0.75, C ≥ 0.60, D ≥ 0.45, F < 0.45
```

Walkers with zero shifts are returned with `grade: null` (ungraded). Results sorted A-first, then by avg stars descending.

**`GET /field-ops/walker-profile/{walker_id}`** — All-time stats + full chronological rating history for one walker. Each rating entry includes the date, driver name, present/absent status, stars (1–5), and the driver's comment. Returns the same grade as the leaderboard for consistency.

### Frontend — `/walker-performance`

**Fleet KPI row** (4 cards):
- Total Walkers / walkers with history
- Fleet Avg Rating (across all rated shifts)
- Fleet Presence % (avg across all walkers)
- At-Risk count (D/F grade or ≥3 no-shows)

**Grade Distribution bar chart** — proportional bars for A/B/C/D/F with counts. Gives management an instant fleet-health picture.

**At-Risk Callout** — only shown when at-risk walkers exist. Each at-risk walker is a clickable pill that opens their profile panel immediately.

**Leaderboard table** — sortable by grade, avg stars, presence %, total shifts, absences, or name. Filterable by name search and grade. Each row is clickable.

**Walker Profile Panel** — slide-in right drawer. Shows:
- Header: grade badge (large), grade label, trend indicator (Improving/Stable/Declining based on first-half vs second-half of all ratings)
- KPI strip: total shifts / present / no-shows / presence %
- All-time avg star rating with star display
- Full chronological rating history: date, driver name, stars, comment — no-show entries shown in red

### Dashboard update

Added "View all-time grades & history →" link below the Walker Performance card on the management dashboard.

---

## Grade Formula Rationale

Equal weighting between presence (50%) and star rating (50%) reflects that both dimensions matter equally to dispatch operations:
- Presence: a walker who doesn't show up is operationally blocking regardless of their star rating
- Stars: a walker who always shows up but consistently receives 1-star ratings is a quality problem

The combined score is bounded [0, 1], making letter-grade thresholds stable and predictable as the fleet scales.

---

## Trend Calculation

The trend indicator splits the walker's rated history in half chronologically (most recent = first half). If the recent half avg is ≥0.2 stars higher than the older half: "Improving". If ≥0.2 stars lower: "Declining". Otherwise: "Stable". Requires ≥4 rated shifts to avoid noise.

---

## Files Changed

| File | Change |
|---|---|
| `backend/app/routers/field_ops.py` | Added `GET /field-ops/walker-leaderboard` and `GET /field-ops/walker-profile/{walker_id}` |
| `frontend/src/pages/WalkerPerformance.tsx` | New page |
| `frontend/src/App.tsx` | Added import + `/walker-performance` route |
| `frontend/src/components/layout/Navbar.tsx` | Added `Star` import + Walkers nav link for admin/management |
| `frontend/src/components/dashboard/ManagementView.tsx` | Added "View all-time grades & history →" link |

# Journal: Admin Preference Analytics View
**Date:** 2026-04-15

---

## Problem

The `/preferences` route was designed for field staff to manage their own fav/ban lists. Admin users visiting this route saw a bare employee selector that, when a record was picked, showed that individual's preferences — offering no system-wide visibility.

Admin's actual need is analytical: understand how the workforce has expressed preferences, spot tension pairs before dispatch, and see coverage gaps (staff who haven't set any preferences).

---

## What Was Built

### Frontend — `PreferenceAnalytics` component (`Preferences.tsx`)

Admin visits `/preferences` → component early-returns `<PreferenceAnalytics />` before any field-staff state or effects execute.

`PreferenceAnalytics` fetches two endpoints in parallel on mount:

| Endpoint | Data |
|---|---|
| `GET /employee-relationships/` | All fav/ban records in the system |
| `GET /employees/?limit=500` | Full employee list for name/role resolution |

**KPI row** (4 cards):

| Metric | Description |
|---|---|
| Total Favs | Count of all fav relationships system-wide |
| Total Bans | Count of all ban relationships system-wide |
| Staff Coverage | % of field staff (driver/walker/trainer) who have set at least one preference |
| Mutual Conflicts | Count of pairs where A bans B and B bans A |

**Role Interaction Matrix**

3×3 grid: rows = who set the preference, columns = who they targeted. Cells display the raw count with heat-map intensity (green for favs, red for bans) proportional to the maximum cell value. Tab toggle switches between the fav view and ban view.

**Most Favoured / Most Banned leaderboards**

Top-10 targets sorted by count descending. Each row is expandable (chevron) to reveal the names of everyone who favoured/banned that person. Mutual-ban entries in the Most Banned list carry a red `mutual` badge.

**Mutual Conflicts section**

Full list of mutual-ban pairs. Each row shows both names and a `↔ mutual ban` badge. When empty, shows a success-state "No mutual conflicts" placeholder.

---

## Branching Logic

```
Preferences()
  ├── isAdmin → <PreferenceAnalytics />   (early return, no employee state)
  └── else    → field-staff preference editor
                 ├── Truck Reassignment section  (walker/trainer only)
                 ├── Favorites section           (driver/walker/trainer only)
                 └── Blocked section             (driver/walker/trainer only)
```

---

## Stale Code Removed

- `getAllEmployeeRelationships` import — no longer used (admin was previously calling it to populate a shadow state)
- `allRelationships` state variable — removed
- Admin useEffect branch inside `loadPreferences` — removed
- Admin employee selector JSX block in the return — removed
- `isAdmin` guards on `canReassign`, `canFavBan`, `isTrainee` section conditions — removed (admin early-returns so they are unreachable)

---

## Files Changed

| File | Change |
|---|---|
| `frontend/src/pages/Preferences.tsx` | Added `PreferenceAnalytics` component; added admin early-return; removed stale admin selector and all related state/effects |

---

## Design Notes

- **No backend changes required.** `GET /employee-relationships/` already returns all records for management/admin callers (enforced server-side). `GET /employees/` already supports `?limit=500`.
- **`useMemo` for all derived data** — `empMap`, `favs`, `bans`, `mutualBans`, `matrix`, `matrixMax`, `favCounts`, `banCounts` — avoids recomputing on every render.
- **Color intensity** is relative (`value / matrixMax`), not absolute, so the matrix remains readable whether there are 5 or 500 relationships.
- **Coverage %** is calculated against field-staff only (driver/walker/trainer), not the full employee list. Admin/management/dispatch/trainee preferences are not meaningful for dispatch purposes.

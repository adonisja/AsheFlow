# Journal: Frontend Design System Migration
**Date:** 2026-04-17

---

## Context

The frontend was functional but had no consistent visual language. A prototype (`launchpad-express`) had been built separately to explore a polished direction. The goal was to migrate the design system, shared components, and UX patterns from that prototype into AsheFlow without breaking existing functionality.

---

## Changes Applied

### Phase 1 — Dependencies

Added `framer-motion` and `cmdk` to `frontend/package.json`. Ran `npm install`. The initial Vite dev server error (`Failed to resolve import "framer-motion"`) was caused by importing from `ThemeToggle.tsx` before `npm install` had been run — not a config issue.

### Phase 2 — Design System (`index.css` + `tailwind.config.js`)

Replaced both files entirely with Design System v3:

- `index.css`: HSL CSS custom properties for all colors under `:root` (light) and `.dark`. Semantic tokens: `--background`, `--foreground`, `--card`, `--primary`, `--muted`, `--border`, `--accent`, `--success`, `--danger`, `--warning`, `--info`, `--gold`, `--teal`. Utility classes: `.glass`, `.glass-strong`, `.gradient-primary`, `.gradient-text-brand`, `.btn-primary`, `.btn-ghost`, `.card`, `.card-elevated`, `.badge`, `.badge-*`, `.kbd`, `.skeleton`.
- `tailwind.config.js`: `darkMode: 'class'`, extended colors mapped to CSS vars, Sora `font-display`, glow shadows, spring easings, slide-up/skeleton keyframes.

### Phase 3 — New Shared Components

| Component | Key detail |
|---|---|
| `ThemeContext.tsx` | Reads `localStorage`, falls back to `prefers-color-scheme`, syncs `.dark` to `document.documentElement` |
| `ThemeToggle.tsx` | `AnimatePresence` swap between `<Sun>` and `<Moon>` — no layout shift |
| `StatCard.tsx` | 8 color tones, `delay` prop for stagger, `hint` subtext |
| `MotionCard.tsx` | Spring-animated wrapper, `variant="glass"`, `hoverable` prop |
| `SectionHeader.tsx` | Eyebrow + title (accepts `ReactNode`) + description + `actions` slot |
| `Skeleton.tsx` | `Skeleton`, `SkeletonText`, `SkeletonCard` — CSS shimmer via `@keyframes skeleton` |
| `CommandPalette.tsx` | `cmdk` Command, ⌘K toggle, role-gated actions, spring-animated glassmorphism panel |

### Phase 4 — `main.tsx`

Wrapped `<App />` in `<ThemeProvider>`.

### Phase 5 — Layout

- Added ambient radial gradient backdrop (indigo top-left, gold right-center) behind all content.
- Wrapped `<Outlet />` in `<AnimatePresence mode="wait">` keyed on `location.pathname`.
- Added `<CommandPalette />` (already renders `<FeedbackModal />`).

### Phase 6 — Navbar

- Background: `glass` instead of `bg-card/80 backdrop-blur-xl`.
- Brand: `font-display gradient-text-brand` + `gradient-primary` icon background with `shadow-glow-primary`.
- ⌘K trigger button: dispatches a synthetic `KeyboardEvent` to trigger the palette's own handler.
- Added `<ThemeToggle />` to the right cluster.
- Notification bell: `bg-surface border-border` button, `shadow-glow-danger` badge.
- Active nav link: `bg-accent text-accent-foreground` (removed gradient, which was visually noisy).

### Phase 7 — Admin Dashboard

Redesigned using new components:
- `SectionHeader` with eyebrow "System", shield icon in title
- 4 `StatCard`s: Active Employees (info), Active Trucks (primary), Open Incidents (danger/success), Training Today (teal) — stagger delays 0 / 0.07 / 0.14 / 0.21
- 3-column `MotionCard` row: Workforce Breakdown, Open Incidents, Training Today
- Removed Employee Roster, Feedback Inbox, Truck Fleet — each has a dedicated page

---

## Bugs Fixed Along the Way

### `Preferences.tsx` — TDZ ReferenceError

`useEffect` at line 373 called `loadPreferences` and `loadChangeRequests`, both defined as `const` functions *after* the hook. JavaScript `const` bindings are not hoisted — accessing them before their declaration throws `ReferenceError: Cannot access 'X' before initialization`.

Fix: moved the `useEffect` to after both function definitions, and moved the `if (isAdmin) return <PreferenceAnalytics />` early return to after all hooks (a hook cannot appear after a conditional return — Rules of Hooks violation).

### Navbar 403 on `/employees/me`

`useNotifications` called `GET /employees/me` for every authenticated user, including admins who have no employee row. The `get_caller_employee` dependency raises 403 when no record is found. Fixed by checking `groups` in the hook before making the request — only field staff and dispatch roles (who have employee records) trigger the call.

---

## Files Changed

| File | Change |
|---|---|
| `frontend/package.json` | Added `framer-motion`, `cmdk` |
| `frontend/src/index.css` | Full Design System v3 replacement |
| `frontend/tailwind.config.js` | Full replacement |
| `frontend/src/contexts/ThemeContext.tsx` | New |
| `frontend/src/components/ui/ThemeToggle.tsx` | New |
| `frontend/src/components/ui/StatCard.tsx` | New |
| `frontend/src/components/ui/MotionCard.tsx` | New |
| `frontend/src/components/ui/SectionHeader.tsx` | New |
| `frontend/src/components/ui/Skeleton.tsx` | New |
| `frontend/src/components/CommandPalette.tsx` | New |
| `frontend/src/components/layout/Layout.tsx` | Ambient backdrop, page transitions, palette |
| `frontend/src/components/layout/Navbar.tsx` | Glass, brand, ⌘K, ThemeToggle, notifications guard |
| `frontend/src/main.tsx` | `ThemeProvider` wrapper |
| `frontend/src/pages/AdminDashboard.tsx` | Full redesign, trimmed to overview |
| `frontend/src/pages/Preferences.tsx` | TDZ bug fix |

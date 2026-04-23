# ADR-040: Frontend Design System Migration (Design System v3)

**Date:** 2026-04-17  
**Status:** Accepted  
**Deciders:** adonisja

---

## Context

The frontend had functional pages but no coherent visual language. Components used ad-hoc Tailwind classes, there was no dark mode, no consistent spacing rhythm, no animation system, and no shared component library. A prototype redesign (`launchpad-express`) had been created separately to explore a polished UI/UX direction. This ADR covers the decision to migrate that design system into AsheFlow.

---

## Decisions

### Design tokens via CSS custom properties (HSL)

All colors are defined as HSL values in `index.css` under `:root` and `.dark`. Components reference tokens (`text-foreground`, `bg-card`, `border-border`) rather than hard-coded Tailwind palette values. This means dark mode is a single class toggle on `<html>`, not conditional rendering.

### Dark mode via `.dark` class on `<html>`, not `prefers-color-scheme`

Tailwind's `darkMode: 'class'` was chosen over `'media'` so the user's in-app preference overrides their system setting. `ThemeContext` reads `localStorage` on mount, falls back to `prefers-color-scheme`, and syncs the `.dark` class to `document.documentElement`.

### Glassmorphism via `.glass` and `.glass-strong` utilities

Defined in `index.css` as `@layer components`. Used on the Navbar and Command Palette. The Navbar uses `glass` (lighter) so content beneath is subtly visible; the palette uses `glass-strong` for higher contrast against the backdrop.

### Framer Motion for page transitions and card animations

`AnimatePresence` in `Layout.tsx` wraps `<Outlet />` — keyed on `location.pathname` so each route change triggers the exit/enter cycle. `MotionCard` and `StatCard` use staggered `delay` props so dashboard cards animate in sequence rather than all at once.

### `cmdk` for the Command Palette

`cmdk` provides keyboard-first search with built-in filtering, group headers, and `data-[selected]` attributes for styling. The palette is role-aware — each action checks the user's `groups` before being added to `visibleActions`. This keeps it from showing links the user cannot access.

### New shared components

| Component | Purpose |
|---|---|
| `StatCard` | KPI tile with 8 color tones and staggered entry animation |
| `MotionCard` | Spring-animated card wrapper, `glass` variant, `hoverable` prop |
| `SectionHeader` | Page header: eyebrow + title + description + actions slot |
| `Skeleton` / `SkeletonCard` / `SkeletonText` | Shimmer loading states |
| `ThemeToggle` | Animated Sun/Moon icon swap via Framer Motion `AnimatePresence` |
| `CommandPalette` | ⌘K palette, role-gated actions, glassmorphism panel |

---

## Consequences

**Positive:**
- Consistent visual language across all pages via shared tokens and components.
- Dark mode works without any per-component logic — just toggle `.dark` on `<html>`.
- Staggered animations make dashboards feel responsive rather than static.
- ⌘K palette gives power users fast keyboard navigation without crowding the navbar.

**Negative / Trade-offs:**
- `framer-motion` adds ~50KB to the bundle. Acceptable for an internal ops tool.
- `cmdk` requires keeping action visibility logic in sync with route guards. If a new protected route is added, the palette action must also be added manually.
- Glassmorphism only looks correct on non-white backgrounds — the ambient gradient backdrop in `Layout.tsx` is load-bearing for this effect.

---

## Files Created / Modified

| File | Type |
|---|---|
| `frontend/src/index.css` | Modified — full Design System v3 token system |
| `frontend/tailwind.config.js` | Modified — `darkMode: 'class'`, custom tokens, keyframes |
| `frontend/src/contexts/ThemeContext.tsx` | New — dark/light mode context |
| `frontend/src/components/ui/ThemeToggle.tsx` | New |
| `frontend/src/components/ui/StatCard.tsx` | New |
| `frontend/src/components/ui/MotionCard.tsx` | New |
| `frontend/src/components/ui/SectionHeader.tsx` | New |
| `frontend/src/components/ui/Skeleton.tsx` | New |
| `frontend/src/components/CommandPalette.tsx` | New |
| `frontend/src/components/layout/Layout.tsx` | Modified — ambient backdrop, page transitions, palette |
| `frontend/src/components/layout/Navbar.tsx` | Modified — glass style, brand gradient, ⌘K trigger, ThemeToggle |
| `frontend/src/main.tsx` | Modified — `ThemeProvider` wrapper |
| `frontend/package.json` | Modified — added `framer-motion`, `cmdk` |

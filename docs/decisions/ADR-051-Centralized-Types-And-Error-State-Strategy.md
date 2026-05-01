# ADR-051: Centralized Frontend Types and Error State Strategy

**Date**: 2026-05-01  
**Status**: Accepted

---

## Context

The frontend codebase had grown to ~15 pages, each declaring their own TypeScript interfaces for API response shapes. The same shapes (`CrewMember`, `UnavailableStaff`, `WalkerSummary`, etc.) appeared as independent inline definitions in 3–5 different files. When an API shape changed, every copy had to be updated independently — and in practice they had already diverged, with some copies missing nullable fields.

Separately, most pages had no error handling at all. Network failures and non-2xx responses were either silently swallowed by bare `catch(console.error)` or not caught at all. Users saw loading spinners that never resolved with no indication of what went wrong.

---

## Decision

### 1. Centralize shared API types in `frontend/src/api/types.ts`

All interfaces that describe shapes returned by the backend API live in one file. Pages import from it rather than declaring their own. When the API shape changes, there is one place to update.

Before adding a new inline interface to a page, check whether a matching (or close-enough) definition already exists in `types.ts`. If the shape differs materially (e.g., a local join adds fields not in the canonical response), keep it local and document why.

### 2. Shared `ErrorBanner` component

`frontend/src/components/ui/ErrorBanner.tsx` — a dismissable red banner that accepts a `message: string | null` prop and renders nothing when message is null. All pages use this rather than inline error markup, ensuring consistent appearance.

### 3. Error state strategy

**Primary page data** (data the page cannot function without): Add an `error` state string, set it in the catch block, and render `<ErrorBanner message={error} />` near the top of the return. Clear it at the start of each fetch.

**Multiple independent panels**: Each panel owns its own error state. The main page error state covers the primary fetch; sub-component error states cover their own fetches. This avoids a single banner falsely declaring the whole page broken when only one panel failed.

**Widget-level and fire-and-forget fetches**: Use silent `catch(() => {})`. These are supplementary — the UI already handles empty/default state, and surfacing a banner for non-critical background data would be confusing.

**`Promise.allSettled` for parallel fetches**: When a page fires multiple fetches in parallel, use `Promise.allSettled` and check whether any result has `status === 'rejected'`. Set the error banner once rather than per-fetch.

---

## Consequences

- Type drift between pages is eliminated. One accurate definition catches mistakes at compile time rather than at runtime.
- Users now see a visible error message when a page fails to load, rather than a perpetual spinner.
- Inline interfaces in individual pages that duplicate shared types are treated as dead code during review and should be removed.
- The `types.ts` file must be kept accurate. Two inaccuracies were found and corrected during the initial consolidation (`WalkerSummary.presence_rate: number | null`, `WalkerSummary.grade` as a literal union). Always verify nullability against the actual SQL query before accepting a `number` or `string` type.

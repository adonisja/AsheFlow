# ADR-062 — Mobile Dispatch Confirmation + useAuth Hooks Fix

**Date:** 2026-05-05  
**Status:** Accepted

## Context

### Dispatch Confirmation

When dispatch assigns a crew member to a truck, an in-app notification is created. Previously there was no way for crew to respond to that notification from mobile — they had to contact dispatch separately. The `dispatch_confirmations` table and `POST /dispatch/{date}/confirmations` endpoint already existed (built for the dispatch dashboard in Phase 7), but no mobile UI wired up to it.

### useAuth Hooks Violation

After adding inline Confirm/Decline buttons to `NotificationsScreen`, a "Should have a queue. You are likely calling Hooks conditionally" Render Error appeared. The root cause was `useAuth()` throwing `new Error('useAuth must be used inside AuthProvider')` synchronously during render — after `useColorScheme()` had already registered one hook. When a throw interrupts the hooks sequence mid-component, React counts a mismatch on the next render and misreports it as a hooks-order violation rather than a missing provider error.

## Decision

### Dispatch Confirmation

Added `dispatch_date: string | null` field to the `Notification` type on mobile (mirroring the backend field). In `NotificationsScreen.renderItem`, notifications with `type === 'dispatch_assignment'` and a non-null `dispatch_date` render inline Confirm/Decline action buttons instead of auto-marking read on tap.

`respondToDispatch(notif, status)` POSTs to `/dispatch/${notif.dispatch_date}/confirmations` with `{employee_id, status, source: 'app'}`, then PATCHes the notification as read. Per-button loading state (`responding` map keyed by notification ID) disables both buttons while a request is in flight and dims the non-active button at 0.4 opacity. After success, the unread state flips and a green dot + "Response recorded" text replaces the buttons.

### useAuth Safe Fallback

Changed `useAuth()` from a throw-on-null to a safe fallback: if `useContext(AuthContext)` returns null, return `AUTH_FALLBACK` — an object with `user: null`, `isLoading: true`, `isAuthenticated: false`, and no-op `signOut`/`hasRole`. The `signIn` method still throws (it is not a render-path call). Every consumer already handles `user === null` with an early return or loading guard, so no callers broke.

## Alternatives Considered

- **Move `useAuth` call above `useColorScheme`** — would change the throw order but not prevent the throw; React still misreports it on hot-reload boundary.
- **Wrap NotificationsScreen in a null-guard HOC** — extra indirection; the fallback object is simpler.
- **Add `useAuthSafe` variant** — would leave the original broken `useAuth` in place alongside a new variant; diverging APIs cause confusion.

## Consequences

- All screens that call `useAuth()` outside `AuthProvider` now see a safe loading state instead of crashing. This is the correct behavior for any accidentally-unmounted screen.
- Crew can confirm or decline dispatch assignments directly from the mobile notification, keeping confirmation data in sync with the dispatch dashboard without any separate communication.
- The `dispatch_confirmations` table now has two sources: the dispatch dashboard (web) and the mobile notification (`source: 'app'`).

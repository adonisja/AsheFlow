# 2026-05-05 — Mobile Dispatch Confirmation + useAuth Hooks Fix

## What we built

### Mobile: Dispatch confirmation from notifications

`NotificationsScreen` now renders inline Confirm / Decline action buttons for any unread `dispatch_assignment` notification that carries a non-null `dispatch_date`. Tapping either button:

1. POSTs `{employee_id, status}` to `POST /dispatch/{dispatch_date}/confirmations`.
2. PATCHes the notification as read (`/notifications/{id}/read`).
3. Replaces the action buttons with a green dot + "Response recorded" label.

Per-button loading uses a `responding: Record<string, 'confirming' | 'declining' | null>` state map so each notification tracks its own in-flight status independently.

### Fix: "Should have a queue" Render Error in NotificationsScreen

**Root cause:** `useAuth()` was calling `throw new Error(...)` when `AuthContext` was null. Because `useColorScheme()` had already run before the throw, React counted a hooks mismatch on the next render and reported "You are likely calling Hooks conditionally."

**Fix:** Changed `useAuth()` to return `AUTH_FALLBACK` (an `AuthContextType` object with `user: null`, `isLoading: true`, no-op methods) instead of throwing. The throw-during-render path is eliminated without changing the public API shape. No callers required changes — every screen already guards on `user === null`.

## Files changed

### Modified
- `mobile/src/screens/Notifications/NotificationsScreen.tsx` — dispatch confirmation buttons, `responding` state, `respondToDispatch` handler
- `mobile/src/contexts/AuthContext.tsx` — `useAuth` now returns `AUTH_FALLBACK` instead of throwing when context is null

### New
- `docs/decisions/ADR-062-Mobile-Dispatch-Confirmation-And-Hooks-Fix.md`
- `docs/journals/2026-05-05-Dispatch-Confirmation-Mobile-And-Hooks-Fix.md`

## Key decision

Chose AUTH_FALLBACK object over `useAuthSafe` variant to avoid diverging APIs. All screens already treat `user === null` as "not authenticated" — the fallback is behaviorally equivalent to a brief pre-mount loading state.

## Debugging note

The "Should have a queue" error is React's generic "hook count changed between renders" panic. It does not always mean a conditional hook call — any throw that interrupts the hooks sequence mid-component produces the same message. When this error appears, look for synchronous throws inside called hooks before assuming a `useEffect`/`useState` ordering problem.

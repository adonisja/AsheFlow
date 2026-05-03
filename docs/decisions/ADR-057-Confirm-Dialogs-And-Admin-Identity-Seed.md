# ADR-057 — Confirm Dialogs, Discord AP Embeds, and Admin Identity Seed

**Date:** 2026-05-02
**Status:** Accepted

## Context

Three separate issues addressed in this session:

### 1. Missing confirm dialogs on destructive actions

A large number of buttons across the app sent requests immediately on click with no confirmation step — approve/reject assignment changes, resolve incidents, update feedback status, deactivate employees/trucks, prune notifications, PTO approval, RTS approval. One misclick was unrecoverable.

### 2. Discord AP notifications were plain text

The `_post_to_discord` helper sent unformatted strings to the truck channel. The bot already had a `/internal/post-to-channel` endpoint but no embed equivalent.

### 3. Confirm All Pending dev tool was broken, then over-fixed

The AdminDashboard "Confirm All Pending" button was silently failing because `res.data` was being iterated instead of `res.data.confirmations`. After fixing the destructuring, the button still 403'd because the logged-in account (`test@example.com`) had no `Employee` row — `get_caller_employee` raised 403 before the body ran. An interim fix introduced a `confirm-all` bulk endpoint that bypassed employee resolution entirely, which was a security regression (no audit trail, any Cognito dispatch-group token could bulk-confirm). That endpoint was reverted.

## Decisions

### Confirm dialogs

New shared primitives:
- `frontend/src/components/ui/ConfirmDialog.tsx` — modal with backdrop, `AlertTriangle` icon, variant prop (`danger | warning | default`), accessible close on backdrop click
- `frontend/src/hooks/useConfirm.ts` — Promise-based hook; `confirm(opts)` returns `Promise<boolean>`; callers `await confirm({...})` and early-return on false

Wired into: Schedule.tsx, ScheduleChanges.tsx, DispatchView.tsx, Incidents.tsx, FeedbackAdmin.tsx, Assets.tsx (three separate hook instances for PeopleTab, FleetTab, SystemTab), Preferences.tsx.

Files with multiple independent sub-components each get their own `useConfirm` instance — one `ConfirmDialog` per sub-component's return tree.

### Discord AP embeds

New bot endpoint `POST /internal/post-embed` accepts a structured payload (`title`, `description`, `color`, `fields[]`, `footer`) and sends a `discord.Embed`. The AP router's `_post_to_discord` helper replaced by `_post_embed_to_discord`, and all three AP events (preliminary, arrived, relocated) now send color-coded embeds with inline driver/location/ETA/notes fields.

### Admin identity seed — no bulk endpoint

**Decision: seed an `Employee` row rather than add a weaker endpoint.**

The `record_confirmation` privileged-role bypass (`caller.role in {"dispatch", "management", "admin"}`) already does exactly what the dev tool needs — it allows dispatch/admin to confirm on behalf of any employee. The problem was purely that `get_caller_employee` couldn't resolve the admin account.

Fix: inserted one `Employee` row for the admin Cognito account:
- `id` / `cognito_sub`: `b1fbc5d0-e011-7025-5615-2e4eba0b3772`
- `email`: `test@example.com`
- `role`: `admin`
- `discord_id`: `test@example.com`

The `confirm-all` bulk endpoint that bypassed employee resolution was reverted because it:
1. Left no `confirmed_by` attribution in the audit trail
2. Accepted any Cognito token in the dispatch group (including the bot service account) with no further check
3. Was unnecessary once the identity gap was filled

### Confirm All Pending visibility

The card is hidden when `pendingConfirmCount === 0` (checked on page load via a silent `GET /dispatch/today/confirmations`). It appears only when there are actual pending confirmations. After a successful confirm-all run, `pendingConfirmCount` resets to 0 so the card disappears on the next render.

## Consequences

- Every destructive action in the app now has a confirmation gate. Misclicks are recoverable.
- Discord truck channels receive rich embeds for all three AP events, visually distinct by color.
- Admin account resolves through the normal `get_caller_employee` chain — no auth bypass exists.
- The confirm-all button is visible only when it is actionable, eliminating confusion on days with no pending confirmations.

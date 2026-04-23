# ADR-041: Navbar Role Scope and Dashboard Routing

**Date:** 2026-04-18  
**Status:** Accepted  
**Deciders:** adonisja

---

## Context

After the design system migration the navbar became visibly overcrowded for admin users — management-only tools (Assets, Trainees, Compliance, Walkers) were rendered inline alongside operational links, pushing everything off-screen. Additionally, the `dispatch` role had no dedicated home — their `homeRoute` sent them to `/dispatch`, which is the crew assignment tool, not a situational dashboard. This ADR covers the decisions made to fix both problems.

---

## Decisions

### Management tools removed from the navbar for admin users; retained for management

Assets, Trainees, Compliance, and Walkers were removed from the admin navbar on the grounds that admins reach those pages via the command palette (⌘K) or directly through their Admin dashboard. Management users still see these links because they are their primary tools and they have no command palette shortcut equivalent.

### Dispatch role gets a dedicated home dashboard at `/dispatch-home`

The existing `/dispatch` page is an operational tool (run dispatch, drag-drop crew, publish to Discord). It is not a home. A new `DispatchHome` page was created at `/dispatch-home` serving as the dispatcher's situational awareness surface:

- Today's dispatch status (run? published? draft?)
- Confirmation breakdown (confirmed / pending / declined bars)
- Staff off today (time-off + recurring off-days)
- Pending schedule change requests with a link to review them

`RoleRedirect` now sends dispatch users to `/dispatch-home`. The operational tool is accessible via a new **Assignments** navbar link visible to dispatch and admin.

### "Assignments" replaces the old "Dispatch" navbar label

The link to `/dispatch` is now labeled **Assignments** — this better describes what the page does (assign crew to trucks) versus what role you need (dispatch). Admin users also see this link since they need access to the crew tool.

### `useNotifications` skips `/employees/me` for non-field-staff roles

Admin and management accounts have no employee row, so the previous unconditional `GET /employees/me` call produced a 403 on every page load. The hook now checks `groups` before making the request — field staff and dispatch roles (who have employee records) still get notifications; admins do not.

---

## Consequences

**Positive:**
- Navbar fits comfortably for all roles — no horizontal overflow.
- Dispatchers have a proper home with situational context before opening the assignment tool.
- The 403 console noise on admin page load is eliminated.

**Negative / Trade-offs:**
- Management tools are now one extra click away for admins (⌘K → search). Acceptable since admins primarily live on the Admin dashboard.
- Dispatcher `homeRoute` change means any hardcoded `/dispatch` links in external tools or bookmarks will land on the assignment tool, not the dashboard.

---

## Files Created / Modified

| File | Type |
|---|---|
| `frontend/src/pages/DispatchHome.tsx` | New — dispatcher home dashboard |
| `frontend/src/App.tsx` | Modified — `/dispatch-home` route, `RoleRedirect` updated |
| `frontend/src/components/layout/Navbar.tsx` | Modified — role visibility, Assignments link, notifications guard |
| `frontend/src/components/CommandPalette.tsx` | Modified — dispatch homeRoute updated |

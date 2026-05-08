# ADR-077 — Registration & Invite Modal UX Polish

**Date:** 2026-05-08  
**Status:** Accepted

## Context

The registration page and Invite Employee modal were functional but visually rough. Several UX gaps were identified during end-to-end testing.

## Decisions

### Register.tsx

**Field containers** — Discord ID and phone fields were visually indistinct. Both now use a consistent bordered container treatment:
```
rounded-xl border border-border bg-input overflow-hidden
focus-within:ring-2 focus-within:ring-primary/30 focus-within:border-primary/50
```
The icon (Hash / Phone+1) sits in a shaded left panel separated by an inner border.

**Discord ID help tooltip** — A `?` (`HelpCircle` icon) next to the label opens a popover explaining how to enable Developer Mode and copy the numeric User ID, with a link to Discord's official guide. Dismisses on click-outside.

**Two-step flow** — "Review & Confirm" replaces the direct submit button. Step 1 is the form; step 2 shows a summary card (Discord ID + phone) with a note that credentials will go to the employee's email. Two buttons: Edit (back to form, preserves values) and Confirm & Submit. API errors on submit drop back to the form with the error shown.

**Done screen** — Removed the username display and sign-in button (employee doesn't know their password yet). Now shows a message directing the employee to check their email for credentials.

**Header** — Welcome message split into heading (`Welcome, {name}.`) and subtitle (`Confirm your details below to complete setup.`).

**Footer** — "managed by your dispatcher" corrected to "managed by your admin".

### Invite Employee modal (Assets.tsx — EmployeeModal)

**Header** — Reduced padding (`py-5 → py-4`), added subtitle line that changes between form and review steps.

**Field containers** — All fields (name, email, role, phone, Discord ID on edit) use the same bordered container treatment as Register.tsx for visual consistency.

**Role select** — ChevronDown pulled out of the input flow so it sits flush inside the container's right edge. Options properly capitalized.

**Two-step flow (create only)** — "Review Invite" advances to a summary card showing name, email, role, and phone (if provided) with a note that a registration link goes to the email. Edit / Send Invite buttons. Edit preserves form values. API errors drop back to form.

**Labels** — Changed from `text-xs uppercase tracking-wider` to `text-sm font-medium text-foreground` for better readability.

### People table (Assets.tsx — PeopleTab)

**Status filter default** — Changed from `active` to `all` so pending/registered employees are visible without changing the filter. All five lifecycle states are available as filter options.

## Consequences

- The registration form is significantly easier to use on mobile — the bordered containers provide clear tap targets
- The review step prevents accidental submissions and makes the Discord ID/phone clearly visible before committing
- The invite modal now matches the design language of the rest of the app
- Admins/management can see the full employee pipeline without hunting for pending records

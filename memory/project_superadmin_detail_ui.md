---
name: Super admin detail page UI polish
description: The company detail drill-down page (/superadmin/companies/:id) needs UI fixes — flagged during live testing on 2026-05-08
type: project
---

The super admin company detail page is functional but needs UI polish and additional features.

**Why:** Noticed during the end-to-end provisioning test on 2026-05-09 — deferred to keep momentum on the company2 isolation test.

**Known issues to fix:**
- General layout/spacing polish still needed

**Missing features to add:**
- Bootstrap admin status not obvious from the list — consider showing a "No admin yet" badge on unconfigured companies in the list view.

**How to apply:** Come back to this after the employee list isolation bug fix (ADR-084) has been validated in production.

# ADR-045: Bulk Employee Import

**Date:** 2026-04-18  
**Status:** Accepted

---

## Context

Adding employees one at a time through the Assets UI is impractical when onboarding a company of 50–200 employees. HR teams need to import from their existing records, which may be in CSV (Excel export, Google Sheets), Excel (.xlsx/.xls), or JSON format. The import flow must follow the same account creation logic as the single-employee flow (Cognito invite, pending status, 7-day expiry) and must be restricted to management and admin.

---

## Decision

### Backend — `POST /employees/bulk`

Accepts a JSON array of up to 200 rows. Each row is processed independently through the same logic as `POST /employees/`:
- Duplicate email → `skipped`
- Duplicate Discord ID → `skipped`
- Cognito `AdminCreateUser` failure → `failed` (with reason)
- DB commit failure → `failed`
- Success → `created`, `account_status=pending_verification`, invite email sent

Returns a 200 with a per-row result array regardless of individual failures — one bad row never aborts the rest. The 200-row cap prevents runaway Cognito API usage in a single request.

Gated to `management` and `admin` via `RoleChecker`.

### Frontend — `BulkImportModal`

Three-step modal rendered inside `PeopleTab`. The Import button is only rendered when `groups.includes('management') || groups.includes('admin')`.

**Step 1 — Upload**: drag-and-drop or file picker. Accepts `.csv`, `.xlsx`, `.xls`, `.json`. Parsing is entirely client-side (no file upload to the server):
- CSV: `papaparse`
- Excel / Google Sheets export: `xlsx` (SheetJS)  
- JSON: `JSON.parse` — expects array of objects, or `{ employees: [...] }` / `{ data: [...] }` wrappers

**Step 2 — Preview & Edit**: all parsed rows shown in an editable table before anything is sent. Inline validation highlights missing required fields and malformed emails. HR can edit any cell or remove rows. Submit is disabled while any row has errors.

**Step 3 — Results**: per-row created / skipped / failed table with color coding. Summary counts at the top. "Export results" downloads a CSV record of the outcome for HR's records.

### Column normalization

Column headers are case-insensitive and common aliases are recognized (`phone` → `phone_number`, `discord` → `discord_id`, `position` → `role`, `full_name` → `name`, etc.). This avoids requiring HR to reformat their existing spreadsheets.

---

## Consequences

- HR can onboard 70 employees in one operation instead of 70 form submissions.
- Every imported employee follows the same verified onboarding path as single-invite employees.
- Failed/skipped rows are clearly reported and exportable — HR has a paper trail.
- No new backend infrastructure — `papaparse` and `xlsx` are frontend-only dependencies.

---

## Alternatives Considered

- **Script-only (Option A)** — rejected for multi-company scale; requires terminal access, not suitable for HR self-service.
- **Server-side file parsing** — rejected; adds multipart upload complexity and a new backend dependency for no benefit. The browser can parse CSV/Excel natively before the payload is ever sent.

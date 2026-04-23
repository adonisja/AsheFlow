# Journal: Bulk Employee Import
**Date:** 2026-04-18

---

## Context

Single-employee invite via the Assets page is impractical for onboarding a full company. This session added a file-based bulk import flow supporting CSV, Excel, and JSON, gated to management and admin.

---

## Changes Applied

### `backend/app/schemas/employee.py`

Added `BulkImportRow` (same fields as `EmployeeCreate`) and `BulkImportResult` (per-row outcome: `row`, `status`, `name`, `email`, `reason`).

### `backend/app/routers/employees.py`

New endpoint `POST /employees/bulk`. Accepts `List[BulkImportRow]`, capped at 200 rows. Processes each row through the same Cognito + DB logic as `POST /employees/`. Returns `List[BulkImportResult]` — always 200, never aborts on individual row failures. Gated to `management` and `admin`.

### `frontend/package.json`

Added `papaparse@^5.4.1`, `@types/papaparse@^5.3.14`, `xlsx@^0.18.5`.

### `frontend/src/components/BulkImportModal.tsx` (new)

Three-step modal:

**Step 1 — Upload**: drag-and-drop or file picker for `.csv`, `.xlsx`, `.xls`, `.json`. Client-side parsing via `papaparse` (CSV) and `xlsx` (Excel/Google Sheets). JSON accepts bare arrays or `{ employees: [...] }` / `{ data: [...] }` wrappers. Column names normalized via alias map (`phone` → `phone_number`, `discord` → `discord_id`, etc.).

**Step 2 — Preview**: editable table with inline validation. Required field + email format checks. Submit blocked while any row has errors. Rows can be removed individually.

**Step 3 — Results**: per-row status table (created / skipped / failed), summary counts, "Export results" CSV download, "Import another file" shortcut.

`onComplete` callback fires after a successful POST so `PeopleTab` reloads the employee list.

### `frontend/src/pages/Assets.tsx`

- Added `FileUp` icon import, `useAuth` import, `BulkImportModal` import.
- `PeopleTab`: added `canImport` boolean (`management || admin`), `showImport` state, Import button (rendered only when `canImport`), `BulkImportModal` render.

---

## Files Changed

| File | Change |
|---|---|
| `backend/app/schemas/employee.py` | `BulkImportRow`, `BulkImportResult` |
| `backend/app/routers/employees.py` | `POST /employees/bulk` |
| `frontend/package.json` | `papaparse`, `@types/papaparse`, `xlsx` |
| `frontend/src/components/BulkImportModal.tsx` | New |
| `frontend/src/pages/Assets.tsx` | Import button + modal wiring |

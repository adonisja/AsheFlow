/**
 * Formatters for nullable dashboard metrics.
 *
 * The backend returns null when a metric cannot be computed — no data in the
 * period, or a prerequisite is unconfigured (e.g. on-time needs
 * CompanyConfig.shift_end). null and 0 are DIFFERENT FACTS and must never
 * render the same way: "0% on-time" reads as a crisis, "—" reads as unknown.
 *
 * Always route nullable metrics through these helpers rather than `?? 0`.
 */

const DASH = '—';

/** Number with fixed decimals, or "—" when unknown. */
export function metric(v: number | null | undefined, digits = 1): string {
  return v === null || v === undefined ? DASH : v.toFixed(digits);
}

/** Percentage with a trailing %, or "—" when unknown. */
export function pct(v: number | null | undefined, digits = 0): string {
  return v === null || v === undefined ? DASH : `${v.toFixed(digits)}%`;
}

/** Integer count. 0 is a real measurement here, so only null/undefined dash. */
export function count(v: number | null | undefined): string {
  return v === null || v === undefined ? DASH : String(v);
}

/** Star rating, or "—" when never rated. */
export function stars(v: number | null | undefined): string {
  return v === null || v === undefined ? DASH : `${v.toFixed(1)} ★`;
}

/** Hours, or "—" when unknown. */
export function hours(v: number | null | undefined, digits = 1): string {
  return v === null || v === undefined ? DASH : `${v.toFixed(digits)}h`;
}

/** Minutes, or "—" when unknown. */
export function minutes(v: number | null | undefined, digits = 0): string {
  return v === null || v === undefined ? DASH : `${v.toFixed(digits)}m`;
}

/** Age in minutes → compact human string ("45m", "3h 20m", "2d"). */
export function age(mins: number | null | undefined): string {
  if (mins === null || mins === undefined) return DASH;
  if (mins < 60) return `${Math.round(mins)}m`;
  if (mins < 60 * 24) {
    const h = Math.floor(mins / 60);
    const m = Math.round(mins % 60);
    return m ? `${h}h ${m}m` : `${h}h`;
  }
  return `${Math.floor(mins / 1440)}d`;
}

/** ISO timestamp → locale date, or "—". */
export function shortDate(iso: string | null | undefined): string {
  if (!iso) return DASH;
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? DASH
    : d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

/** Trend direction → arrow + label. null trend means "not enough data". */
export function trendLabel(t: string | null | undefined): { arrow: string; label: string } {
  if (t === 'up') return { arrow: '↑', label: 'Improving' };
  if (t === 'down') return { arrow: '↓', label: 'Declining' };
  if (t === 'flat') return { arrow: '→', label: 'Stable' };
  return { arrow: '', label: 'No prior data' };
}

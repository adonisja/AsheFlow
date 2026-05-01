/** Returns today as YYYY-MM-DD in local time. */
export const getLocalYMD = (): string => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};

/** Alias kept for call sites that use the name `today`. */
export const today = getLocalYMD;

/** Format any Date object as YYYY-MM-DD in local time. */
export const fmtDate = (d: Date): string =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

/** Returns the Monday of the week that is `offset` weeks from today, as YYYY-MM-DD. */
export const isoWeekStart = (offset = 0): string => {
  const d = new Date();
  d.setDate(d.getDate() - d.getDay() + 1 + offset * 7);
  return d.toISOString().split('T')[0];
};

/** Returns the date `n` weeks ago as YYYY-MM-DD. */
export const nWeeksAgo = (n: number): string => {
  const d = new Date();
  d.setDate(d.getDate() - n * 7);
  return d.toISOString().split('T')[0];
};

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
  return fmtDate(d);
};

/** Returns the date `n` weeks ago as YYYY-MM-DD. */
export const nWeeksAgo = (n: number): string => {
  const d = new Date();
  d.setDate(d.getDate() - n * 7);
  return fmtDate(d);
};

// ---------------------------------------------------------------------------
// Timezone display (ADR-451 follow-up)
// ---------------------------------------------------------------------------

/** Current abbreviation and UTC offset for an IANA zone, e.g. "EDT · UTC-4".
 *
 *  COMPUTED, never written down. Half of the US zones shift twice a year and
 *  they do not shift together: today Denver is MDT and Phoenix is MST — both
 *  UTC-7 — and in January they diverge, because Arizona does not observe DST.
 *  A hardcoded table is wrong for roughly half the year, silently, about the
 *  one thing a timezone label exists to state.
 *
 *  "GMT-4" is rewritten to "UTC-4": GMT invites the question of whether it
 *  means London, which in summer it does not.
 */
export function zoneOffset(tz: string): string {
  try {
    const now = new Date();
    const abbr = new Intl.DateTimeFormat('en-US', { timeZone: tz, timeZoneName: 'short' })
      .formatToParts(now).find(p => p.type === 'timeZoneName')?.value ?? '';
    const gmt = new Intl.DateTimeFormat('en-US', { timeZone: tz, timeZoneName: 'shortOffset' })
      .formatToParts(now).find(p => p.type === 'timeZoneName')?.value ?? '';
    return [abbr, gmt.replace('GMT', 'UTC')].filter(Boolean).join(' · ');
  } catch {
    // An unrecognised zone string must not blank the header it sits in.
    return '';
  }
}

/** The city half of an IANA zone: "America/New_York" -> "New York".
 *
 *  The region prefix carries no information to someone who already knows which
 *  company they are looking at, and the underscore is a path artefact.
 */
export function zoneCity(tz: string): string {
  return (tz.split('/').pop() ?? tz).replace(/_/g, ' ');
}

/** A zone rendered for display: "New York · EDT · UTC-4".
 *
 *  Used wherever a company's timezone is SHOWN rather than chosen, so the four
 *  places that show one cannot drift into four different formats.
 */
export function formatZone(tz: string): string {
  const off = zoneOffset(tz);
  return off ? `${zoneCity(tz)} · ${off}` : zoneCity(tz);
}

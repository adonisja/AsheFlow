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

// ---------------------------------------------------------------------------
// Date display
// ---------------------------------------------------------------------------

/** Accepts what the API actually returns: an ISO string, an epoch, or a Date. */
type Dateish = string | number | Date | null | undefined;

function toDate(d: Dateish): Date | null {
  // NULL MUST BE CHECKED BEFORE `new Date()`, which coerces null to epoch 0 --
  // a perfectly valid Date that NaN-checks clean and renders "Dec. 31, 1969".
  // Nullable timestamps are everywhere in this API (returned_at,
  // ore_completed_at, left_early_at), so the epoch date is the failure a
  // caller would actually hit, and it looks like data rather than a bug.
  // Empty string is here for the same reason -- it is what a blank form field
  // sends, and `new Date('')` is Invalid Date only by luck of the spec.
  if (d === null || d === undefined || d === '') return null;
  if (d instanceof Date) return Number.isNaN(d.getTime()) ? null : d;

  // A DATE-ONLY string is parsed by JS as UTC midnight, then rendered in local
  // time -- so "2026-09-26" displays as Sept 25 anywhere west of Greenwich.
  // These come from the API as calendar dates (a dispatch date, a created_at
  // day), not instants, so they are constructed in LOCAL time instead.
  if (typeof d === 'string') {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(d.trim());
    if (m) {
      const [y, mo, day] = [Number(m[1]), Number(m[2]) - 1, Number(m[3])];
      const v = new Date(y, mo, day);
      // JS ROLLS OVER instead of rejecting: `new Date(2026, 12, 45)` is
      // Feb 14 2027, not an error. A malformed API date would then render as a
      // confident wrong day rather than "—", so the components are read back.
      if (v.getFullYear() !== y || v.getMonth() !== mo || v.getDate() !== day) {
        return null;
      }
      return v;
    }
  }
  const v = new Date(d);
  return Number.isNaN(v.getTime()) ? null : v;
}

/** AP month abbreviation: "Sept." not "Sep", and May/June/July never shorten.
 *
 *  Intl's en-US short month gives Jan…Dec, which abbreviates September to
 *  "Sep" and shortens June and July to "Jun"/"Jul" -- neither is AP style, and
 *  the product's copy follows AP elsewhere.
 */
const AP_MONTH: Record<string, string> = {
  Jan: 'Jan.', Feb: 'Feb.', Mar: 'March', Apr: 'April', May: 'May',
  Jun: 'June', Jul: 'July', Aug: 'Aug.', Sep: 'Sept.', Oct: 'Oct.',
  Nov: 'Nov.', Dec: 'Dec.',
};

function apMonth(v: Date): string {
  const short = v.toLocaleDateString('en-US', { month: 'short' });
  return AP_MONTH[short] ?? short;
}

/** "Sept. 26, 2026" — the default for any date shown to a user.
 *
 *  Replaces bare `toLocaleDateString()`, which rendered "9/26/2026": ambiguous
 *  to anyone outside the US (is 9/26 a day or a month?) and visually
 *  indistinguishable from an ID. An abbreviated month cannot be misread.
 *
 *  `Sept` rather than `Sep` because Intl's en-US short month gives "Sep"; the
 *  four-letter form is the AP style this product's copy follows elsewhere.
 */
export function formatDate(d: Dateish): string {
  const v = toDate(d);
  if (!v) return '—';
  return `${apMonth(v)} ${v.getDate()}, ${v.getFullYear()}`;
}

/** "Sept. 26, 2026 at 2:04 PM" — when the time of day matters. */
export function formatDateTime(d: Dateish): string {
  const v = toDate(d);
  if (!v) return '—';
  const time = v.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
  return `${formatDate(v)} at ${time}`;
}

/** "Saturday, September 26" — a page header naming the day being worked.
 *
 *  The weekday is the point here: a dispatcher reads "Saturday" to know which
 *  shift they are looking at, and the year is noise on a page about today.
 */
export function formatDayHeader(d: Dateish): string {
  const v = toDate(d);
  if (!v) return '—';
  return v.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' });
}

/** "Sat, Sept. 26" — compact, for chips and dense table cells. */
export function formatDateShort(d: Dateish): string {
  const v = toDate(d);
  if (!v) return '—';
  const wd = v.toLocaleDateString('en-US', { weekday: 'short' });
  return `${wd}, ${apMonth(v)} ${v.getDate()}`;
}

/** "Saturday, September 26, 2026" — a printed sheet's date line.
 *
 *  `formatDayHeader` drops the year deliberately (a screen about today does not
 *  need it). Paper outlives the day it was printed on, so a load sheet or a
 *  returns manifest found in a bin next month has to say which one it is.
 */
export function formatDayHeaderFull(d: Dateish): string {
  const v = toDate(d);
  if (!v) return '—';
  return v.toLocaleDateString('en-US', {
    weekday: 'long', month: 'long', day: 'numeric', year: 'numeric',
  });
}

/** "Sept. 26, 2:04 PM" — compact date and time for a dense inbox row.
 *
 *  No year and no weekday: these rows are recent by construction, and the
 *  reader is scanning the times against each other.
 */
export function formatDateTimeShort(d: Dateish): string {
  const v = toDate(d);
  if (!v) return '—';
  const time = v.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
  return `${apMonth(v)} ${v.getDate()}, ${time}`;
}

/** "Sept. 26" — an axis tick or a trailing "last seen" note.
 *
 *  For chart axes and inline references where the surrounding context already
 *  establishes the year, and a weekday would crowd the label.
 */
export function formatMonthDay(d: Dateish): string {
  const v = toDate(d);
  if (!v) return '—';
  return `${apMonth(v)} ${v.getDate()}`;
}

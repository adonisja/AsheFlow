/** Today as YYYY-MM-DD in the DEVICE's local timezone.
 *
 * NOT `new Date().toISOString().slice(0, 10)`. That formats in UTC, so from
 * 8 PM Eastern onward it returns TOMORROW — and a walker on an evening shift
 * asks the API for a date their route does not exist on, then sees "No route
 * yet" while physically holding the totes.
 *
 * Found in the simulator at 9:20 PM local: the screen requested 2026-08-26 for
 * a route that exists on 2026-08-25.
 *
 * The web app has had `getLocalYMD` in `utils/date.ts` for exactly this reason;
 * mobile had no equivalent, so every screen open-coded the UTC version.
 *
 * The DEVICE's timezone, not the company's: this picks the date a crew member
 * would name if you asked them, and the server is authoritative about what
 * belongs to that date (`company_today`, ADR-289).
 */
export function localYMD(d: Date = new Date()): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

/** The local calendar day of a server timestamp (ADR-521).
 *
 * NOT `iso.split('T')[0]`: that is the UTC day, so a report filed at 10:40 PM
 * Eastern on the 15th lists as the 16th. Prefer a record's own `date` field
 * when it has one; this is for records that only carry a timestamp.
 */
export function localDayOf(iso: string): string {
  return localYMD(new Date(iso));
}

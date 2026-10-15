/**
 * "3m ago", "2h ago", "Yesterday": one formatter for every notification surface.
 *
 * Moved out of NotificationsScreen (2026-10-15, ADR-516) when the owner noticed
 * the URGENT alerts, the ones that most need a "how long has this been going
 * on", were the only notifications without one. `now` is injectable for tests.
 */
export function formatRelative(iso: string, now: number = Date.now()): string {
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return '';
  const mins = Math.floor((now - t) / 60000);
  if (mins < 1) return 'Just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return days === 1 ? 'Yesterday' : `${days}d ago`;
}

// ADR-519: one place that turns a notification into the URL it opens, so the
// banner, the inbox and the history page cannot disagree about where it goes.
import type { Notification } from '../contexts/NotificationContext';

/** `route?id=…&date=…`, or the notifications page for a row with no link. */
export function notificationHref(n: Pick<Notification, 'link'>): string {
  const link = n.link;
  if (!link) return '/notifications';
  const params = new URLSearchParams();
  // A templated route (/help-requests/<id>) already carries the id.
  if (link.id && !link.route.includes(link.id)) params.set('id', link.id);
  if (link.date) params.set('date', link.date);
  const q = params.toString();
  return q ? `${link.route}?${q}` : link.route;
}

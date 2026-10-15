/**
 * Where each unread notification goes in the notification area, and what an
 * arrival does (ADR-516 D1-D3). Pure, so the rules are tested rather than
 * eyeballed in a screenshot.
 */
import { isTicker, isUrgent, type NotificationSeverity } from './tone';

export interface AreaNotification {
  id: string;
  severity?: NotificationSeverity;
  channels?: string[];
}

/** URGENT pinned at the top; ACTION as the "need you" row; ticker types in
 *  the dock. Anything else (INFO about the reader) lives in the inbox only:
 *  the arrival banner is its moment in the area. */
export function partitionArea<T extends AreaNotification>(unread: T[]) {
  const urgent: T[] = [], needsYou: T[] = [], ticker: T[] = [];
  for (const n of unread) {
    if (isUrgent(n.severity)) urgent.push(n);
    else if (n.severity === 'action') needsYou.push(n);
    else if (isTicker(n.channels)) ticker.push(n);
  }
  return { urgent, needsYou, ticker };
}

/** D2: URGENT -> strong haptic (it is already pinned); ticker -> nothing;
 *  everything else -> the newest one gets the banner. `arrivals` is newest first. */
export function arrivalOutcome<T extends AreaNotification>(arrivals: T[]) {
  return {
    urgentHaptic: arrivals.some(n => isUrgent(n.severity)),
    banner: arrivals.find(n => !isUrgent(n.severity) && !isTicker(n.channels)) ?? null,
  };
}

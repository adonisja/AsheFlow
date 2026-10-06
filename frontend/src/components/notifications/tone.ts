import type { NotificationSeverity, NotificationTone } from '../../contexts/NotificationContext';

/**
 * Server tone -> this surface's Tailwind tokens (ADR-487 D4).
 *
 * WHAT THIS REPLACES
 * ==================
 *
 * `styleForType` in NotificationBanner.tsx guessed from the type STRING:
 *
 *     if (type.includes('critical') || type.includes('warning')) -> warning
 *     if (type.endsWith('_rejected'))                            -> danger
 *     if (type.startsWith('anchor_point'))                       -> info
 *
 * Three problems with guessing, all of which the registry removes:
 *
 *   1. `incident_critical` is URGENT and `manifest_enrichment` is INFO, but
 *      `type.includes('critical')` put the first in the same bucket as
 *      `timecard_adjustment`. The gap ADR-487 opens with.
 *   2. A new type gets whatever the chain happens to match. `quiz_submitted`
 *      matched nothing and fell to the `info` default by accident, not decision.
 *   3. The rule lived in two places, worded differently, on two surfaces.
 *
 * WHY THE SERVER SENDS A ROLE AND NOT A COLOUR
 * ============================================
 *
 * This file is the reason. Mobile has the same map with React Native theme
 * values on the right-hand side; a hex from a Python file could not serve both,
 * and would land in one of the two themes unreadable.
 */
export const TONE_CARD: Record<NotificationTone, string> = {
  neutral: 'bg-accent/20 border-border',
  good: 'bg-success/10 border-success/30',
  warn: 'bg-warning/10 border-warning/30',
  bad: 'bg-danger/10 border-danger/30',
  // "active" means something is in progress and expects the reader to come
  // back to it — info's palette, which already reads as "ongoing" here.
  active: 'bg-info/10 border-info/30',
};

/** Tone -> the text colour for the icon and title row. */
export const TONE_TEXT: Record<NotificationTone, string> = {
  neutral: 'text-muted-foreground',
  good: 'text-success',
  warn: 'text-warning',
  bad: 'text-danger',
  active: 'text-info',
};

/**
 * URGENT overrides its tone's card styling.
 *
 * All four URGENT types are already `bad` or `warn`, so the tone map would give
 * them a tinted card indistinguishable from a `_rejected` INFO row. The region
 * (D4a) is what carries "this is different" structurally; this gives it the
 * weight to match, with a left bar rather than only a tint — ADR-487 rejected
 * "the registry tone alone" precisely because colour alone fails for a
 * dispatcher whose eyes are on a truck list, and fails outright for anyone with
 * a colour-vision deficiency.
 */
export const URGENT_CARD =
  'bg-danger/15 border-danger/50 border-l-4 border-l-danger shadow-sm';

/** Does this severity belong in the region above the scroll cap? */
export function isUrgent(severity: NotificationSeverity): boolean {
  return severity === 'urgent';
}

/**
 * Does this severity render in the ticker rather than as a card?
 *
 * NOT the same question as "is it INFO". 52 types are INFO and only 20 carry
 * TICKER — the operative rule is about the SUBJECT, not the tier:
 *
 *   > INFO about the reader goes to the banner. INFO about a third party or
 *   > about the system goes to the ticker.
 *
 * Which is why this reads the server's channel list rather than deriving it
 * from severity. `pto_approved` is INFO and must not scroll past: it is a
 * decision about the reader's own time off.
 */
export function isTicker(channels: string[] | undefined): boolean {
  // Optional-chained because a row delivered by an older server build, or a
  // fixture written before this field existed, has no `channels`. Those fall
  // to the banner, which is the safe side: a missed ticker item is an
  // announcement seen as a card, while a wrongly-tickered one scrolls past.
  return !!channels?.includes('ticker');
}

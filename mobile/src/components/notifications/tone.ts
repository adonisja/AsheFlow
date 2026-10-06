import type { ThemeColors } from '@theme/index';

/**
 * Server tone -> this surface's theme values (ADR-487 D4).
 *
 * PORTED FROM `frontend/src/components/notifications/tone.ts`, and deliberately
 * NOT identical to it. The web copy returns Tailwind class strings; this one
 * returns colour values off the active theme. That difference is the whole
 * reason the server sends a semantic ROLE instead of a colour:
 *
 *     // web
 *     bad: 'bg-danger/10 border-danger/30'
 *     // here
 *     bad: { bg: c.dangerLight, border: c.danger, text: c.danger }
 *
 * A hex value from a Python file could not serve both, and would land in one of
 * the two themes unreadable. `check_shared_copies` therefore does NOT pair these
 * two files — only `classify.ts`, which is genuinely identical logic.
 *
 * WHAT THIS REPLACES ON THIS SURFACE
 * ==================================
 *
 * `NotificationsScreen` carried TWO hardcoded tables: a 52-entry `TYPE_META`
 * (label + icon) and a `typeColor` chain of 20 string tests ending in
 * `type.includes('approved')`. Between them they covered 52 of the registry's
 * 86 types; the other 34 fell to a default by accident, not decision. And they
 * disagreed with web: `incident_critical` was `c.danger` here and a warning
 * tint there, for the same row from the same endpoint.
 */
export type NotificationTone = 'neutral' | 'good' | 'warn' | 'bad' | 'active';
export type NotificationSeverity = 'urgent' | 'action' | 'notice' | 'info';

export interface ToneStyle {
  /** Card fill. The `*Light` variants exist for exactly this. */
  bg: string;
  /** Border and the accent bar. */
  border: string;
  /** Icon and title text. */
  text: string;
}

export function toneStyle(tone: NotificationTone, c: ThemeColors): ToneStyle {
  switch (tone) {
    case 'good':
      return { bg: c.successLight, border: c.success, text: c.success };
    case 'warn':
      return { bg: c.warningLight, border: c.warning, text: c.warning };
    case 'bad':
      return { bg: c.dangerLight, border: c.danger, text: c.danger };
    case 'active':
      return { bg: c.infoLight, border: c.info, text: c.info };
    case 'neutral':
    default:
      // `default` as well as `neutral`: an unmapped tone must render SOMETHING.
      // On web the same gap produced the literal CSS class "undefined" — a
      // class that does not exist, so the text rendered at the inherited
      // colour with no error anywhere. Here it would be `undefined` passed to
      // a style prop, which RN ignores just as quietly.
      return { bg: c.surfaceMuted, border: c.border, text: c.mutedForeground };
  }
}

/**
 * URGENT overrides its tone's card styling.
 *
 * All four URGENT types are already `bad` or `warn`, so the tone map alone
 * would give them a card indistinguishable from a routine `_rejected` row. The
 * REGION is what carries "this is different" structurally; this gives it
 * matching weight with a thick left bar rather than only a tint.
 *
 * ADR-487 D4a rejected "the registry tone alone" for exactly this reason:
 * colour alone fails for a dispatcher whose eyes are on a truck list, and fails
 * outright for anyone with a colour-vision deficiency.
 */
export function urgentStyle(c: ThemeColors): ToneStyle & { barWidth: number } {
  return { bg: c.dangerLight, border: c.danger, text: c.danger, barWidth: 4 };
}

/** Does this severity belong in the region above the scroll? */
export function isUrgent(severity: NotificationSeverity | undefined): boolean {
  return severity === 'urgent';
}

/**
 * Does this notification scroll in the ticker rather than render as a card?
 *
 * NOT the same question as "is it INFO". 52 types are INFO and only 20 carry
 * `ticker` — the rule is about the message's SUBJECT:
 *
 *   INFO about the reader goes to the inbox. INFO about a third party or about
 *   the system goes to the ticker.
 *
 * Which is why this reads the server's channel list rather than deriving it
 * from severity. `pto_approved` is INFO and must not scroll past: it is a
 * decision about the reader's own time off.
 *
 * Optional-chained because a row delivered by an older server build, or a
 * fixture written before this field existed, has no `channels`. Those fall to
 * the inbox, which is the safe side: a missed ticker item is an announcement
 * seen as a card, while a wrongly-tickered one scrolls past.
 */
export function isTicker(channels: string[] | undefined): boolean {
  return !!channels?.includes('ticker');
}

import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { ChevronDown, ChevronUp } from 'lucide-react';
import type { Notification } from '../../contexts/NotificationContext';
import { useReducedMotion } from '../../hooks/useReducedMotion';

/**
 * Events that happened, scrolling past (ADR-487 D4b).
 *
 * THE TRADE, STATED HONESTLY
 * ==========================
 *
 * This is NOT a space saving, and an earlier draft of ADR-487 claimed it was.
 * ADR-275 D2 had already collapsed the informational set into one ~42px row
 * showing a preview of the newest item, expandable in place. The ticker is
 * ~28px. The real saving is ~14px against a control that is strictly MORE
 * informative:
 *
 *   |                        | collapsed row | ticker |
 *   |------------------------|---------------|--------|
 *   | vertical space         | ~42px         | ~28px  |
 *   | items visible at once  | 1 + a count   | several, in sequence |
 *   | expand in place        | yes           | no — tap goes to /notifications |
 *   | noticed without looking| NO            | YES    |
 *
 * The last row is the whole reason. A static row in a fixed position is
 * something people learn to stop seeing — banner blindness is a measured
 * effect, and the collapsed row has been in place long enough to have earned
 * it. Motion in peripheral vision is picked up without directed attention,
 * which is what an announcement to someone whose attention is on a truck
 * actually needs.
 *
 * WHAT IS GIVEN UP: expand-in-place, and the always-visible preview of the
 * newest item. `/notifications` remains the full archive (ADR-128), so nothing
 * becomes unreachable — it becomes one tap further away.
 *
 * THE REDUCED-MOTION PATH IS THE MORE INFORMATIVE ONE
 * ===================================================
 *
 * With motion reduced this renders as the collapsed row it replaced: a static
 * strip with a count and the newest item, expandable in place. That is not a
 * degraded fallback bolted on — it is the better-detail control from the table
 * above. Which also means this component is fully testable without animation.
 */
interface Props {
  items: Notification[];
  onDismissAll?: () => void;
}

export const NotificationTicker: React.FC<Props> = ({ items, onDismissAll }) => {
  const reduced = useReducedMotion();
  const [expanded, setExpanded] = useState(false);

  if (items.length === 0) return null;

  // Newest first is how the banner already sorts, so [0] is the latest.
  const newest = items[0];

  /* ---------------- reduced motion: the collapsed row ---------------- */
  if (reduced) {
    return (
      <div className="rounded-lg border border-border bg-accent/20 overflow-hidden">
        <button
          type="button"
          onClick={() => setExpanded(v => !v)}
          aria-expanded={expanded}
          className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-accent/30 transition-colors"
        >
          <span aria-hidden="true" className="shrink-0">{newest.icon}</span>
          <span className="flex-1 min-w-0 truncate text-xs text-muted-foreground">
            {newest.label} — {newest.message}
          </span>
          {items.length > 1 && (
            <span className="shrink-0 text-xs font-medium text-muted-foreground tabular-nums">
              +{items.length - 1}
            </span>
          )}
          {expanded
            ? <ChevronUp className="w-3.5 h-3.5 shrink-0 text-muted-foreground" />
            : <ChevronDown className="w-3.5 h-3.5 shrink-0 text-muted-foreground" />}
        </button>

        {expanded && (
          <ul className="border-t border-border/60 bg-background/40 px-3 py-2 space-y-1.5">
            {items.map(n => (
              <li key={n.id} className="flex items-start gap-2 text-xs text-muted-foreground">
                <span aria-hidden="true" className="shrink-0">{n.icon}</span>
                <span className="min-w-0">{n.message}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    );
  }

  /* ---------------- motion: the scrolling strip ---------------- */
  // One string, duplicated, so the translate can loop seamlessly. Rendering
  // each item as its own element and animating them individually would mean N
  // simultaneous animations for what reads as one line of text.
  const line = items.map(n => `${n.icon} ${n.message}`).join('   ·   ');

  return (
    <div
      className="group relative flex items-center gap-2 h-7 rounded-lg border border-border bg-accent/20 overflow-hidden"
      /* The region is a live announcement, but POLITE: these are events with no
         consequence for the reader, so interrupting a screen reader mid-sentence
         would be exactly wrong. The URGENT region above is where assertive
         belongs — and it is not a live region at all, because it is a card the
         reader is meant to act on rather than an announcement. */
      role="status"
      aria-live="polite"
    >
      <div className="flex-1 min-w-0 overflow-hidden">
        <div
          className="inline-flex whitespace-nowrap text-xs text-muted-foreground animate-ticker group-hover:[animation-play-state:paused]"
          /* Duration scales with content so a long line does not scroll faster
             than a short one — a fixed duration makes three items crawl and
             twelve items unreadable. ~22 chars/second is the readable-while-
             glancing rate; the floor stops a one-item ticker from being
             instant. */
          style={{ animationDuration: `${Math.max(18, Math.round(line.length / 22) * 2)}s` }}
        >
          {/* aria-hidden on the duplicate: it exists only so the loop has no
              visible gap, and a screen reader must not read the line twice. */}
          <span className="px-3">{line}</span>
          <span className="px-3" aria-hidden="true">{line}</span>
        </div>
      </div>

      <Link
        to="/notifications"
        className="shrink-0 pr-3 text-xs text-muted-foreground hover:text-foreground underline transition-colors"
      >
        View all
      </Link>
      {onDismissAll && (
        <button
          type="button"
          onClick={onDismissAll}
          className="shrink-0 pr-3 text-xs text-muted-foreground hover:text-foreground underline transition-colors"
        >
          Clear
        </button>
      )}
    </div>
  );
};

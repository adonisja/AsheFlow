import { useEffect, useRef } from 'react';

/**
 * Bring a page's error banner to the person who caused it (ADR-339).
 *
 * Every page here renders `{error && <div>...}` near the top while the controls
 * that set it sit far below. ADR-333 found the consequence on
 * DispatchDashboard: a correct 409 — "HUB has no dock assigned. Set a bay
 * before publishing." — painted several screens above the viewport and was
 * reported as a silent failure. The error was displayed. It was not seen, and
 * to a user those are the same event.
 *
 * Measured across the ten pages that share the shape, Assets is the worst case
 * at ~1934 lines between its banner and its furthest of 17 setError calls.
 *
 * A HOOK rather than a shared <ErrorBanner> component on purpose: the banner
 * markup differs page to page (three lack the danger border, only one has an
 * icon), so a component would restyle nine pages as a side effect of a scroll
 * fix — and a refactor whose review is "nothing moved" cannot also change how
 * nine pages look.
 *
 * Usage:
 *   const errorRef = useErrorBanner(error);
 *   {error && <div ref={errorRef} className="...unchanged...">{error}</div>}
 */
export function useErrorBanner(error: string | null | undefined) {
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    // Only on a real error. Without this, clearing the error (setError(null))
    // would scroll, and a page that polls would scroll-jack continuously.
    if (!error) return;

    // CLAUDE.md: an animation that ignores prefers-reduced-motion is a bug, not
    // a flourish. Still scrolls — only the smoothness is dropped.
    const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches;
    ref.current?.scrollIntoView({
      behavior: reduced ? 'auto' : 'smooth',
      block: 'center',
    });
    // Keyed on the error VALUE, so a re-render with the same error does not
    // re-scroll and fight the user for control of the viewport.
  }, [error]);

  return ref;
}

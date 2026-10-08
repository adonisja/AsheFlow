import { useEffect, useState } from 'react';

/**
 * Whether the viewer has asked for reduced motion — as a SUBSCRIPTION.
 *
 * WHY NOT THE ONE-SHOT READ ALREADY IN THE CODEBASE
 * =================================================
 *
 * `useErrorBanner.ts` reads the query once:
 *
 *     const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches;
 *
 * That is correct there: it decides whether to animate a banner that is about to
 * appear, and the decision is over in a moment.
 *
 * A ticker is different because it persists. A dispatcher who turns reduced
 * motion ON mid-shift — plausibly *because* the ticker is bothering them — would
 * keep the scrolling until the next full reload. Reading once at mount is the
 * bug ADR-487 D4b names explicitly, and mobile's `primitives.tsx` already does
 * the subscribing version with `reduceMotionChanged`; this is the web
 * equivalent.
 *
 * SSR / unsupported-browser safety: `matchMedia` is guarded, and the initial
 * state resolves to `false` (animate) rather than `true`. Defaulting to "reduce"
 * would silently disable motion for anyone whose browser does not report the
 * setting, which is the opposite of a progressive enhancement.
 */
export function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState<boolean>(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return false;
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  });

  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return;
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)');

    const onChange = (e: MediaQueryListEvent) => setReduced(e.matches);

    // Safari <14 only has the deprecated addListener. Feature-detect rather
    // than assume: the modern call throws on those versions, which would take
    // out the whole banner rather than just the subscription.
    if (mq.addEventListener) {
      mq.addEventListener('change', onChange);
      return () => mq.removeEventListener('change', onChange);
    }
    mq.addListener(onChange);
    return () => mq.removeListener(onChange);
  }, []);

  return reduced;
}
